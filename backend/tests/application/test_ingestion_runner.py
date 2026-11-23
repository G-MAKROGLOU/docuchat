import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_corpus_stats_repository, get_ingestion_control
from app.application.corpus_update import UpdateReport
from app.application.ingestion_runner import IngestionRunner
from app.application.label_queue import QueueReport
from app.main import app
from tests.support.fakes_ingestion import FakeCorpusStats, ListedDocuments, StubIngestionControl


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
        cast(Any, service), cast(Any, ListedDocuments()), no_updates, no_queue, NeverStale()
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
