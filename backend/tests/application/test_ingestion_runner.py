import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_corpus_stats_repository, get_ingestion_control
from app.application.corpus_update import UpdateReport
from app.application.ingestion import IngestResult
from app.application.ingestion_runner import IngestionRunner
from app.application.label_queue import QueueReport
from app.main import app
from tests.support.fakes_ingestion import (
    FakeCorpusStats,
    FakeTracker,
    ListedDocuments,
    StubIngestionControl,
)
from tests.support.tuning import SETTINGS


class FakeService:
    def __init__(self) -> None:
        self.ingested: list[str] = []
        self.release = asyncio.Event()

    async def ingest(self, document: Any, *, force: bool = False) -> None:
        await self.release.wait()
        self.ingested.append(document.source_id)


class NeverStale:
    async def stale(self) -> bool:
        return False

    async def mark_embedded(self) -> None:
        pass


def make_runner(service: FakeService) -> IngestionRunner:
    async def no_queue() -> QueueReport:
        return QueueReport()

    async def no_updates() -> UpdateReport:
        await asyncio.sleep(0.1)  # long enough to observe the checking phase
        return UpdateReport()

    return IngestionRunner(
        cast(Any, service),
        cast(Any, ListedDocuments()),
        no_updates,
        no_queue,
        NeverStale(),
        concurrency=SETTINGS.ingest_concurrency,
    )


def test_a_second_start_is_refused_while_a_pass_runs() -> None:
    async def scenario() -> tuple[bool, bool, bool, bool, list[str]]:
        service = FakeService()
        runner = make_runner(service)
        first = runner.start()
        second = runner.start()
        running = runner.running
        service.release.set()
        await runner._task  # type: ignore[misc]
        return first, second, running, runner.running, service.ingested

    first, second, running, running_after, ingested = asyncio.run(scenario())

    assert (first, second, running, running_after) == (True, False, True, False)
    assert ingested == ["a", "b"]


@pytest.fixture
def runner() -> Iterator[StubIngestionControl]:
    stub = StubIngestionControl(running=False)
    app.dependency_overrides[get_ingestion_control] = lambda: stub
    app.dependency_overrides[get_corpus_stats_repository] = FakeCorpusStats
    yield stub


def test_post_starts_a_pass_then_conflicts(runner: StubIngestionControl) -> None:
    client = TestClient(app)

    first = client.post("/api/v1/ingestion")
    second = client.post("/api/v1/ingestion")

    assert first.status_code == 202
    assert first.json() == {"running": True}
    assert second.status_code == 409
    assert runner.started == 1
    assert client.get("/api/v1/status").json()["ingestion_running"] is True


def test_the_schedule_starts_a_pass_each_interval_and_reports_the_next_run() -> None:
    async def scenario() -> tuple[bool, list[str], bool]:
        service = FakeService()
        service.release.set()
        runner = make_runner(service)
        assert runner.next_run_at is None
        runner.start_schedule(timedelta(milliseconds=50))
        await asyncio.sleep(0)
        scheduled = runner.next_run_at is not None
        # The update check paces its requests, so the first pass takes about a second.
        for _ in range(100):
            if len(service.ingested) >= 2:
                break
            await asyncio.sleep(0.05)
        ingested = list(service.ingested)
        await runner.stop()
        return scheduled, ingested, runner.next_run_at is None

    scheduled, ingested, cleared = asyncio.run(scenario())

    assert scheduled
    assert ingested[:2] == ["a", "b"]
    assert cleared


def test_the_phase_follows_the_pass() -> None:
    async def scenario() -> list[str]:
        service = FakeService()
        runner = make_runner(service)
        seen: list[str] = [runner.phase]
        runner.start()
        await asyncio.sleep(0.05)
        seen.append(runner.phase)
        # The update check paces its requests; the pass then waits in the ingestion.
        for _ in range(100):
            if runner.phase == "ingesting":
                break
            await asyncio.sleep(0.05)
        seen.append(runner.phase)
        service.release.set()
        await runner._task  # type: ignore[misc]
        seen.append(runner.phase)
        return seen

    assert asyncio.run(scenario()) == ["idle", "checking", "ingesting", "idle"]


def test_each_ingested_document_is_reported_with_its_time() -> None:
    seen: list[tuple[object, float]] = []

    async def scenario() -> None:
        service = FakeService()
        service.release.set()
        runner = make_runner(service)
        runner.observe = lambda result, seconds: seen.append((result, seconds))
        runner.start()
        await runner._task  # type: ignore[misc]

    asyncio.run(scenario())

    assert len(seen) == 2
    assert all(isinstance(seconds, float) and seconds >= 0 for _, seconds in seen)


class ParallelService:
    """Counts the documents in progress; fails or raises for the named source IDs."""

    def __init__(self, *, fail: str = "", explode: str = "") -> None:
        self.active = 0
        self.most = 0
        self.ingested: list[str] = []
        self._fail = fail
        self._explode = explode

    async def ingest(self, document: Any, *, force: bool = False) -> IngestResult:
        self.active += 1
        self.most = max(self.most, self.active)
        try:
            await asyncio.sleep(0.01)
            if document.source_id == self._explode:
                raise ConnectionError("pool timeout")
            self.ingested.append(document.source_id)
            if document.source_id == self._fail:
                return IngestResult(document.id, error="ValueError")
            return IngestResult(document.id, chunks=1)
        finally:
            self.active -= 1


def run_parallel(
    service: ParallelService, *, concurrency: int, force: bool = False
) -> tuple[list[IngestResult], FakeTracker, str]:
    async def no_queue() -> QueueReport:
        return QueueReport()

    async def no_updates() -> UpdateReport:
        return UpdateReport()

    tracker = FakeTracker(stale=False)
    seen: list[IngestResult] = []

    async def scenario() -> str:
        runner = IngestionRunner(
            cast(Any, service),
            cast(Any, ListedDocuments(*"abcdefg")),
            no_updates,
            no_queue,
            tracker,
            concurrency=concurrency,
        )
        runner.observe = lambda result, seconds: seen.append(result)
        runner.start(force=force)
        await runner._task  # type: ignore[misc]
        return runner.phase

    phase = asyncio.run(scenario())
    return seen, tracker, phase


def test_a_pass_ingests_at_most_the_limit_of_documents_at_once() -> None:
    service = ParallelService()

    seen, _, _ = run_parallel(service, concurrency=3)

    assert service.most == 3
    assert sorted(service.ingested) == list("abcdefg")
    assert len(seen) == 7


def test_a_limit_of_one_ingests_one_document_at_a_time_in_order() -> None:
    service = ParallelService()

    run_parallel(service, concurrency=1)

    assert service.most == 1
    assert service.ingested == list("abcdefg")


def test_a_failed_document_does_not_stop_the_others_and_is_counted() -> None:
    service = ParallelService(fail="b")

    seen, tracker, phase = run_parallel(service, concurrency=3, force=True)

    assert sorted(service.ingested) == list("abcdefg")
    assert sum(1 for r in seen if r.error) == 1
    assert sum(r.chunks for r in seen) == 6
    # Stored as failed: the next pass takes it again, so the marker moves as before.
    assert tracker.marked == 1
    assert phase == "idle"


def test_a_document_that_raises_does_not_stop_the_others_and_keeps_the_marker() -> None:
    service = ParallelService(explode="c")

    seen, tracker, phase = run_parallel(service, concurrency=3, force=True)

    assert sorted(service.ingested) == list("abdefg")
    assert len(seen) == 6
    # Its status did not change, so it can still hold chunks of the old index.
    assert tracker.marked == 0
    assert phase == "idle"


def test_stopping_a_pass_cancels_the_documents_in_progress() -> None:
    class Blocked:
        def __init__(self) -> None:
            self.started = 0
            self.cancelled = 0

        async def ingest(self, document: Any, *, force: bool = False) -> None:
            self.started += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise

    async def scenario() -> tuple[int, int, bool]:
        service = Blocked()
        runner = make_runner(cast(Any, service))
        runner.start()
        for _ in range(100):
            if service.started == 2:
                break
            await asyncio.sleep(0.05)
        await runner.stop()
        return service.started, service.cancelled, runner.running

    assert asyncio.run(scenario()) == (2, 2, False)


def test_a_pass_takes_the_queue_until_it_is_empty_before_it_ingests() -> None:
    reports = [QueueReport(added=50), QueueReport(added=2, failed=1), QueueReport()]
    taken: list[QueueReport] = []

    async def take_queue() -> QueueReport:
        taken.append(reports[len(taken)])
        return taken[-1]

    async def no_updates() -> UpdateReport:
        return UpdateReport()

    service = ParallelService()

    async def scenario() -> None:
        runner = IngestionRunner(
            cast(Any, service),
            cast(Any, ListedDocuments("a")),
            no_updates,
            take_queue,
            FakeTracker(stale=False),
            concurrency=SETTINGS.ingest_concurrency,
        )
        runner.start()
        await runner._task  # type: ignore[misc]

    asyncio.run(scenario())

    assert taken == reports
