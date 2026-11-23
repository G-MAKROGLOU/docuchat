"""Runs against a real Postgres when TEST_DATABASE_URL is set (Compose, CI service)."""

import asyncio
import os
import uuid

import pytest

from app.domain.entities import MessageRole
from app.infrastructure.conversation_repository import PostgresConversationRepository
from app.infrastructure.migrations import apply_migrations
from tests.support.db import DirectConnections

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def test_turns_round_trip_in_order_with_a_limit() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    repository = PostgresConversationRepository(DirectConnections(conninfo))

    async def scenario() -> None:
        conversation_id = await repository.create()
        assert await repository.exists(conversation_id)
        assert not await repository.exists(uuid.uuid4())

        await repository.add_turn(conversation_id, MessageRole.USER, "first")
        await repository.add_turn(conversation_id, MessageRole.ASSISTANT, "second", ["S1", "S2"])
        await repository.add_turn(conversation_id, MessageRole.USER, "third")

        turns = await repository.turns(conversation_id)
        assert [t.text for t in turns] == ["first", "second", "third"]
        assert turns[1].role is MessageRole.ASSISTANT
        assert turns[1].citations == ("S1", "S2")

        newest = await repository.turns(conversation_id, limit=2)
        assert [t.text for t in newest] == ["second", "third"]

    asyncio.run(scenario())


def test_delete_removes_the_conversation_and_its_turns() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    repository = PostgresConversationRepository(DirectConnections(conninfo))

    async def scenario() -> None:
        conversation_id = await repository.create()
        await repository.add_turn(conversation_id, MessageRole.USER, "first")

        assert await repository.delete(conversation_id)
        assert not await repository.exists(conversation_id)
        assert await repository.turns(conversation_id) == []
        assert not await repository.delete(conversation_id)

    asyncio.run(scenario())
