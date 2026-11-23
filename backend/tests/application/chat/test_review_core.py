"""Tests for the core review fixes: the chat turn deadline and the stream retry backoff."""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import replace
from typing import Any

import httpx

from app.application.chat import ChatService
from app.domain.entities import Message, ModelRole
from app.domain.runtime_settings import RuntimeSettings
from app.runtime_config import RuntimeConfig
from tests.support.factories import RUNTIME_DEFAULTS, make_chunk
from tests.support.fakes_ingestion import FakeRuntimeSettingsRepository
from tests.support.fakes_models import FakeModel, search_models
from tests.support.fakes_ports import (
    LIPITOR,
    Clock,
    FakeConversations,
    FakeDetector,
    FakeRetriever,
    FakeTracer,
)
from tests.support.http import GOOD, sse_response, stream_model
from tests.support.tuning import CHAT, SETTINGS


class SlowModel(FakeModel):
    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        await asyncio.sleep(5)
        yield "late"


def test_a_turn_past_its_deadline_ends_with_an_error_event() -> None:
    models = search_models()
    models.by_role[ModelRole.GENERATE] = SlowModel()
    store = FakeConversations()
    service = ChatService(
        store,
        models,
        FakeDetector(LIPITOR).source,
        FakeRetriever(make_chunk("10 mg")),
        FakeTracer(),
        limits=replace(CHAT, turn_deadline_seconds=0.2),
    )

    async def scenario() -> list[dict[str, Any]]:
        conversation = await service.start()
        return [e async for e in await service.ask(conversation, "What is the dose of Lipitor?")]

    events = asyncio.run(scenario())

    assert events[-1] == {"type": "error", "message": "The answer took too long. Please try again."}


def test_a_rate_limit_waits_for_retry_after_before_the_second_try() -> None:
    waits: list[float] = []
    replies = iter(
        [httpx.Response(429, headers={"retry-after": "3"}, text="slow down"), sse_response(GOOD)]
    )
    streamer = stream_model(lambda request: next(replies))
    streamer.sleep = _recorder(waits)

    async def run() -> str:
        return "".join([c.text async for c in streamer.astream([("user", "dose?")])])

    assert asyncio.run(run()) == "Take it daily [S1]."
    assert waits == [3.0]


def test_a_server_error_without_retry_after_waits_one_second() -> None:
    waits: list[float] = []
    replies = iter([httpx.Response(503, text="busy"), sse_response(GOOD)])
    streamer = stream_model(lambda request: next(replies))
    streamer.sleep = _recorder(waits)

    async def run() -> None:
        async for _ in streamer.astream([("user", "dose?")]):
            pass

    asyncio.run(run())

    assert waits == [1.0]


def _recorder(waits: list[float]) -> Any:
    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    return sleep


def test_a_failed_refresh_keeps_the_old_settings_and_tries_again() -> None:
    repository, clock = FakeRuntimeSettingsRepository(), Clock()
    builds: list[RuntimeSettings] = []
    fail = [True]

    async def rebuild(new: RuntimeSettings) -> Callable[[], None]:
        if new != RUNTIME_DEFAULTS and fail[0]:
            raise RuntimeError("S3 is down")
        builds.append(new)
        return lambda: None

    config = RuntimeConfig(
        repository,
        RUNTIME_DEFAULTS,
        rebuild,
        clock=clock,
        refresh_seconds=SETTINGS.runtime_refresh_seconds,
    )
    asyncio.run(config.load())
    repository.saved = {"top_k": 30}
    clock.now = 5.0

    assert asyncio.run(config.refresh()) is False
    assert config.current == RUNTIME_DEFAULTS

    fail[0] = False
    clock.now = 10.0
    assert asyncio.run(config.refresh()) is True
    assert config.current.top_k == 30
