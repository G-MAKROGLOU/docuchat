"""Tests for the scale review fixes: DailyMed retries, the parallel update check and the
detector rebuild limit."""

import asyncio
import io
import time
import urllib.error
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.application.corpus_update import check_for_updates
from app.application.drug_detection import DetectorCache
from app.infrastructure.corpus_stats_repository import CachedCorpusStats
from app.infrastructure.dailymed import DailyMedClient

TEMPLATE = "https://labels.test/{source_id}"


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://labels.test/x", code, "error", {}, io.BytesIO())  # type: ignore[arg-type]


class Opener:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request: Any, timeout: float) -> io.BytesIO:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)  # type: ignore[arg-type]


def dailymed_client(opener: Opener, waits: list[float]) -> DailyMedClient:
    return DailyMedClient(
        TEMPLATE,
        TEMPLATE,
        timeout_seconds=60,
        max_bytes=1024,
        attempts=3,
        first_backoff_seconds=1.0,
        opener=opener,
        sleep=waits.append,
    )


def test_a_server_error_or_a_timeout_is_tried_again_with_backoff() -> None:
    waits: list[float] = []
    opener = Opener(http_error(503), TimeoutError(), b"label")

    assert dailymed_client(opener, waits).fetch_label("abc") == b"label"
    assert opener.calls == 3
    assert waits == [1.0, 2.0]


def test_a_rate_limit_is_tried_again() -> None:
    waits: list[float] = []

    assert dailymed_client(Opener(http_error(429), b"pdf"), waits).fetch_pdf("abc") == b"pdf"
    assert waits == [1.0]


def test_a_not_found_fails_at_once() -> None:
    waits: list[float] = []
    opener = Opener(http_error(404))

    with pytest.raises(urllib.error.HTTPError):
        dailymed_client(opener, waits).fetch_label("abc")
    assert opener.calls == 1
    assert waits == []


def test_the_last_error_is_raised_after_the_last_try() -> None:
    waits: list[float] = []
    opener = Opener(http_error(503), http_error(503), http_error(502))

    with pytest.raises(urllib.error.HTTPError):
        dailymed_client(opener, waits).fetch_label("abc")
    assert opener.calls == 3


class SlowSource:
    """Counts how many label fetches run at the same time."""

    def __init__(self) -> None:
        self.running = 0
        self.peak = 0

    def fetch_label(self, source_id: str) -> bytes:
        self.running += 1
        self.peak = max(self.peak, self.running)
        time.sleep(0.05)
        self.running -= 1
        raise ValueError("stop here")

    def fetch_pdf(self, source_id: str) -> bytes:
        raise AssertionError("not reached")


class Documents:
    def __init__(self, count: int) -> None:
        self.items = [SimpleNamespace(id=i, source_id=f"s{i}") for i in range(count)]

    async def list_all(self) -> list[SimpleNamespace]:
        return self.items


def test_the_update_check_runs_a_few_labels_at_once_and_counts_each() -> None:
    source = SlowSource()

    report = asyncio.run(
        check_for_updates(
            source,
            cast(Any, None),
            cast(Any, Documents(12)),
            delay_seconds=0,
            concurrency=4,
        )
    )

    assert (report.checked, report.failed) == (12, 12)
    assert 1 < source.peak <= 4


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_new_library_version_rebuilds_only_after_the_minimum_interval() -> None:
    clock, version, builds = Clock(), [1], [0]

    async def current() -> object:
        return version[0]

    async def build() -> int:
        builds[0] += 1
        return builds[0]

    cache = DetectorCache(current, build, min_interval=30.0, clock=clock)

    async def scenario() -> list[int]:
        first = await cache()
        version[0] = 2  # one document ingested
        clock.now = 10.0
        early = await cache()
        clock.now = 31.0
        late = await cache()
        return [first, early, late]

    assert asyncio.run(scenario()) == [1, 1, 2]


class CountingStats:
    def __init__(self) -> None:
        self.scans = 0

    async def stats(self) -> object:
        self.scans += 1
        return self.scans

    async def document_counts(self) -> dict[str, int]:
        return {"ingested": 1}


def test_corpus_totals_are_scanned_once_per_library_version() -> None:
    inner, version = CountingStats(), [1]

    async def current() -> object:
        return version[0]

    cached = CachedCorpusStats(cast(Any, inner), current, min_interval=0)

    async def scenario() -> list[object]:
        first, again = await cached.stats(), await cached.stats()
        version[0] = 2
        return [first, again, await cached.stats(), await cached.document_counts()]

    assert asyncio.run(scenario()) == [1, 1, 2, {"ingested": 1}]


@pytest.mark.parametrize("set_id", ["", "abc", "not-a-set-id-at-all-0000000000000000"])
def test_adding_a_label_needs_a_set_id_in_the_dailymed_format(
    label_client: TestClient,
    set_id: str,
) -> None:
    assert label_client.post("/api/v1/labels", json={"set_id": set_id}).status_code == 422


def test_a_clarify_turn_keeps_its_outcome_after_the_final_event() -> None:
    from prometheus_client import REGISTRY  # noqa: PLC0415

    from app.api.routers.chat import _sse  # noqa: PLC0415  # router helper under test

    before = REGISTRY.get_sample_value("docuchat_chat_turns_total", {"outcome": "clarify"}) or 0

    async def events() -> Any:
        for event in (
            {"type": "clarify", "candidates": ["A", "B"]},
            {"type": "token", "text": "Which one?"},
            {"type": "final", "answer": "Which one?", "citations": []},
        ):
            yield event

    async def run() -> None:
        async for _ in _sse(events()):
            pass

    asyncio.run(run())

    after = REGISTRY.get_sample_value("docuchat_chat_turns_total", {"outcome": "clarify"})
    assert after == before + 1


@pytest.mark.parametrize("text", ["   ", "\n\t "])
def test_a_question_of_only_spaces_is_rejected_by_the_schema(text: str) -> None:
    from pydantic import ValidationError  # noqa: PLC0415

    from app.api.schemas.chat import AskRequest  # noqa: PLC0415

    with pytest.raises(ValidationError):
        AskRequest(text=text)


def test_the_question_limit_is_one_constant() -> None:
    from app.api.schemas.chat import AskRequest  # noqa: PLC0415
    from app.application.chat import MAX_QUESTION_CHARS  # noqa: PLC0415

    assert AskRequest(text="x" * MAX_QUESTION_CHARS).text
    with pytest.raises(Exception, match="at most"):
        AskRequest(text="x" * (MAX_QUESTION_CHARS + 1))
