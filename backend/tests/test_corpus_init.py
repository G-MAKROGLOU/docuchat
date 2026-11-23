import asyncio
from typing import Any, cast

from app.application.corpus import CorpusEntry
from app.application.label_queue import queue_manifest
from app.domain.label_queue import QueueStatus
from tests.support.factories import make_document
from tests.support.fakes_ingestion import FakeDocumentRepository, FakeQueue


class FakeState:
    def __init__(self) -> None:
        self.requests: list[bool] = []

    async def request(self, *, force: bool) -> None:
        self.requests.append(force)


def entry(set_id: str, brand: str = "", generic: str = "g") -> CorpusEntry:
    return CorpusEntry(
        brand_name=brand,
        generic_name=generic,
        manufacturer="m",
        source_id=set_id,
    )


def run(queue: FakeQueue, documents: FakeDocumentRepository, entries: list[CorpusEntry]) -> int:
    state = FakeState()
    queued = asyncio.run(queue_manifest(entries, queue, cast(Any, documents), state))
    assert state.requests == ([False] if queued else [])
    return queued


def test_an_empty_library_queues_every_manifest_label_and_asks_for_a_pass() -> None:
    queue = FakeQueue()

    queued = run(queue, FakeDocumentRepository(), [entry("a", "Brand"), entry("b")])

    assert queued == 2
    assert {s: e.title for s, e in queue.entries.items()} == {"a": "Brand", "b": "g"}


def test_a_library_with_every_manifest_label_is_left_alone() -> None:
    documents = FakeDocumentRepository(make_document(source_id="a"))

    assert run(FakeQueue(), documents, [entry("a")]) == 0


def test_a_failed_label_is_queued_again_and_a_waiting_one_is_not_added_twice() -> None:
    queue = FakeQueue()
    asyncio.run(queue.add("failed", "t"))
    asyncio.run(queue.mark("failed", QueueStatus.FAILED, "timeout"))
    asyncio.run(queue.add("waiting", "t"))

    queued = run(queue, FakeDocumentRepository(), [entry("failed"), entry("waiting")])

    assert queued == 1
    assert queue.entries["failed"].status is QueueStatus.QUEUED
