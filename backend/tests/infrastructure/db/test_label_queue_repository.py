"""Runs against a real Postgres when TEST_DATABASE_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid

import pytest

from app.domain.label_queue import QueueStatus
from app.infrastructure.label_queue_repository import PostgresLabelQueueRepository
from app.infrastructure.migrations import apply_migrations
from tests.support.db import DirectConnections

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def test_the_queue_round_trips_and_a_failed_entry_can_be_queued_again() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    repository = PostgresLabelQueueRepository(DirectConnections(conninfo))
    set_id = str(uuid.uuid4())

    async def scenario() -> None:
        assert await repository.add(set_id, "title")
        assert not await repository.add(set_id, "title")
        assert await repository.known([set_id, "other"]) == {set_id}
        assert set_id in [e.set_id for e in await repository.next_queued(1000)]
        assert set_id in [e.set_id for e in (await repository.list_page(1, 1000)).entries]
        await repository.mark(set_id, QueueStatus.FAILED, "reason")
        assert set_id not in [e.set_id for e in await repository.next_queued(1000)]
        assert await repository.add(set_id, "title")
        await repository.mark(set_id, QueueStatus.ADDED, None)
        listing = await repository.list_page(1, 1)
        assert listing.added_total >= 1
        assert listing.total == listing.queued_total + listing.added_total + listing.failed_total
        assert len(listing.entries) == 1
        assert not await repository.remove(set_id)
        await repository.mark(set_id, QueueStatus.QUEUED, None)
        assert await repository.remove(set_id)

    asyncio.run(scenario())
