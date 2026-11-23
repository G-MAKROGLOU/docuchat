import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.api.dependencies import get_corpus_stats_repository, get_ingestion_control
from app.api.routers.chat import _sse
from app.infrastructure.metrics import LLM_METRICS
from app.main import app
from tests.support.fakes_ingestion import FakeCorpusStats, IdleControl
from tests.support.http import USAGE, sse_response, stream_chunk, stream_model


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_a_streamed_call_counts_time_tokens_and_cost_for_its_role() -> None:
    usage = {**USAGE, "cost": 0.25}
    body = stream_chunk("Take it.") + stream_chunk("", usage=usage) + "data: [DONE]\n\n"
    before = {
        "calls": value("docuchat_llm_calls_total", role="generate", status="ok"),
        "input": value("docuchat_llm_tokens_total", role="generate", kind="input"),
        "output": value("docuchat_llm_tokens_total", role="generate", kind="output"),
        "cost": value("docuchat_llm_cost_usd_total", role="generate"),
        "timed": value("docuchat_llm_call_seconds_count", role="generate"),
    }

    async def run() -> None:
        async for _ in stream_model(lambda request: sse_response(body)).astream(
            [("user", "dose?")], config={"callbacks": [LLM_METRICS]}
        ):
            pass

    asyncio.run(run())

    assert value("docuchat_llm_calls_total", role="generate", status="ok") == before["calls"] + 1
    assert value("docuchat_llm_tokens_total", role="generate", kind="input") == (
        before["input"] + 120
    )
    assert value("docuchat_llm_tokens_total", role="generate", kind="output") == (
        before["output"] + 7
    )
    assert value("docuchat_llm_cost_usd_total", role="generate") == pytest.approx(
        before["cost"] + 0.25
    )
    assert value("docuchat_llm_call_seconds_count", role="generate") == before["timed"] + 1


def test_a_failed_call_counts_as_an_error() -> None:
    before = value("docuchat_llm_calls_total", role="generate", status="error")

    async def run() -> None:
        failing = stream_model(lambda request: httpx.Response(400, text="bad"))
        async for _ in failing.astream([("user", "dose?")], config={"callbacks": [LLM_METRICS]}):
            pass

    with pytest.raises(Exception, match="400"):
        asyncio.run(run())

    assert value("docuchat_llm_calls_total", role="generate", status="error") == before + 1


async def events(*items: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    for item in items:
        yield item


def turn(*items: dict[str, Any]) -> list[bytes]:
    async def run() -> list[bytes]:
        return [part async for part in _sse(events(*items))]

    return asyncio.run(run())


@pytest.mark.parametrize(
    ("items", "outcome"),
    [
        (
            [
                {"type": "token", "text": "Take"},
                {"type": "final", "answer": "Take [S1]", "citations": ["S1"]},
            ],
            "answer",
        ),
        ([{"type": "final", "answer": "Hi!", "citations": []}], "reply"),
        ([{"type": "refusal", "reason": "no_valid_citation"}], "refusal_no_valid_citation"),
        ([{"type": "error", "message": "failed"}], "error"),
    ],
)
def test_each_turn_counts_once_by_outcome(items: list[dict[str, Any]], outcome: str) -> None:
    before = value("docuchat_chat_turns_total", outcome=outcome)

    payloads = turn(*items)

    assert [json.loads(p[6:])["type"] for p in payloads] == [i["type"] for i in items]
    assert value("docuchat_chat_turns_total", outcome=outcome) == before + 1


def test_the_first_token_time_is_recorded_for_answers() -> None:
    before = value("docuchat_chat_first_token_seconds_count")

    turn(
        {"type": "token", "text": "Take"},
        {"type": "final", "answer": "x [S1]", "citations": ["S1"]},
    )

    assert value("docuchat_chat_first_token_seconds_count") == before + 1


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_corpus_stats_repository] = FakeCorpusStats
    app.dependency_overrides[get_ingestion_control] = IdleControl
    yield TestClient(app)


def test_requests_are_counted_by_route_template_and_metrics_are_served(client: TestClient) -> None:
    # The route template as FastAPI keeps it, without the /api/v1 prefix.
    labels = {"method": "GET", "route": "/status", "status": "200"}
    before = value("docuchat_http_requests_total", **labels)

    assert client.get("/api/v1/status").status_code == 200
    response = client.get("/metrics")

    assert value("docuchat_http_requests_total", **labels) == before + 1
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "docuchat_http_requests_total" in response.text


def test_the_metrics_endpoint_is_not_in_the_api_contract(client: TestClient) -> None:
    assert "/metrics" not in client.get("/api/v1/openapi.json").json()["paths"]
