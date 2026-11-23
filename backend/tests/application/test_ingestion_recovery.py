"""Ingestion across processes: the per-document lock, safe failure reasons and the CLI pass."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from app.application.ingestion import public_reason
from app.infrastructure.storage import FileSystemDocumentStore
from tests.support.fakes_ingestion import (
    NODES,
    FakeChunkRepository,
    FakeEmbedder,
    FakeLabelParser,
    SingleDocumentRepository,
    ingestion_service,
    stored_label_document,
)
from tests.support.tuning import SETTINGS


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
    assert (
        public_reason(ValueError("The label gave no chunks"), SETTINGS.failure_reason_max_chars)
        == "The label gave no chunks"
    )
    leak = ConnectionError("connect to http://storage:8333/bucket failed")
    assert public_reason(leak, SETTINGS.failure_reason_max_chars) == "ConnectionError"
    assert len(public_reason(ValueError("x" * 900), SETTINGS.failure_reason_max_chars)) == 500
