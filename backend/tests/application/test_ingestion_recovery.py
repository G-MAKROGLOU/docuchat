"""Ingestion across processes: the per-document lock, safe failure reasons and the CLI pass."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.application.ingestion import IngestResult, public_reason
from app.infrastructure.storage import FileSystemDocumentStore
from app.ingest import ingest_documents
from tests.support.fakes_ingestion import (
    NODES,
    FakeChunkRepository,
    FakeEmbedder,
    FakeLabelParser,
    FakeTracker,
    SingleDocumentRepository,
    ingestion_service,
    stored_label_document,
)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[SingleDocumentRepository, FileSystemDocumentStore]:
    return stored_label_document(tmp_path)


class Locks:
    def __init__(self, *, free: bool) -> None:
        self.free = free
        self.held: list[uuid.UUID] = []

    @asynccontextmanager
    async def hold(self, document_id: uuid.UUID) -> AsyncIterator[bool]:
        if self.free:
            self.held.append(document_id)
        yield self.free


def test_a_document_that_another_process_ingests_is_skipped_untouched(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    busy = replace(
        ingestion_service(
            documents, store, FakeChunkRepository(), FakeLabelParser(NODES), FakeEmbedder()
        ),
        locks=Locks(free=False),
    )

    result = asyncio.run(busy.ingest(documents.document))

    assert result.skipped
    assert documents.statuses == []


def test_a_free_document_is_ingested_under_its_lock(
    setup: tuple[SingleDocumentRepository, FileSystemDocumentStore],
) -> None:
    documents, store = setup
    locks = Locks(free=True)
    free = replace(
        ingestion_service(
            documents, store, FakeChunkRepository(), FakeLabelParser(NODES), FakeEmbedder()
        ),
        locks=locks,
    )

    result = asyncio.run(free.ingest(documents.document))

    assert result.chunks > 0
    assert locks.held == [documents.document.id]


def test_a_failure_reason_keeps_our_own_message_but_not_driver_text() -> None:
    assert public_reason(ValueError("The label gave no chunks")) == "The label gave no chunks"
    leak = ConnectionError("connect to http://storage:8333/bucket failed")
    assert public_reason(leak) == "ConnectionError"
    assert len(public_reason(ValueError("x" * 900))) == 500


class Service:
    def __init__(self, *, fail: str | None = None) -> None:
        self.forced: list[bool] = []
        self._fail = fail

    async def ingest(self, document: Any, *, force: bool = False) -> IngestResult:
        self.forced.append(force)
        if document.source_id == self._fail:
            return IngestResult(document.id, error="ValueError")
        return IngestResult(document.id, chunks=1)


DOCS = [SimpleNamespace(id=uuid.uuid4(), source_id=s) for s in ("a", "b")]


@pytest.mark.parametrize(
    ("stale", "force", "forced", "marked"),
    [
        (True, False, [True, True], 1),
        (False, True, [True, True], 1),
        (False, False, [False, False], 0),
    ],
)
def test_the_cli_pass_embeds_a_stale_index_again_and_marks_it_done(
    stale: bool, force: bool, forced: list[bool], marked: int
) -> None:
    service, tracker = Service(), FakeTracker(stale=stale)

    asyncio.run(ingest_documents(cast(Any, DOCS), cast(Any, service), tracker, force=force))

    assert service.forced == forced
    assert tracker.marked == marked


def test_a_failed_document_leaves_the_stale_marker(tmp_path: Path) -> None:
    service, tracker = Service(fail="b"), FakeTracker(stale=True)

    asyncio.run(ingest_documents(cast(Any, DOCS), cast(Any, service), tracker, force=False))

    assert tracker.marked == 0


class SlowService:
    """Finishes the documents in reverse order; raises for one source ID."""

    def __init__(self, raises: str) -> None:
        self.active = 0
        self.most = 0
        self._raises = raises

    async def ingest(self, document: Any, *, force: bool = False) -> IngestResult:
        self.active += 1
        self.most = max(self.most, self.active)
        try:
            await asyncio.sleep(0.05 - 0.01 * int(document.source_id))
            if document.source_id == self._raises:
                raise ConnectionError("connect to http://storage:8333 failed")
            return IngestResult(document.id, chunks=2, tokens=10)
        finally:
            self.active -= 1


def test_the_cli_pass_runs_documents_at_once_and_reports_each_in_order() -> None:
    docs = [SimpleNamespace(id=uuid.uuid4(), source_id=str(i)) for i in range(5)]
    service, tracker = SlowService(raises="1"), FakeTracker(stale=False)

    results = asyncio.run(
        ingest_documents(cast(Any, docs), cast(Any, service), tracker, force=True, concurrency=3)
    )

    assert service.most == 3
    assert [d.source_id for d, _ in results] == ["0", "1", "2", "3", "4"]
    assert [r.error for _, r in results] == [None, "ConnectionError", None, None, None]
    assert sum(r.chunks for _, r in results) == 8
    assert tracker.marked == 0
