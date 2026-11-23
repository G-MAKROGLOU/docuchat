"""Postgres adapter for ConversationRepository."""

import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.domain.conversations import Turn
from app.domain.entities import MessageRole
from app.infrastructure.database import Connections


def _to_turn(row: dict[str, Any]) -> Turn:
    return Turn(**{**row, "role": MessageRole(row["role"]), "citations": tuple(row["citations"])})


class PostgresConversationRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def create(self) -> UUID:
        conversation_id = uuid.uuid4()
        async with self._connections.connection() as conn:
            await conn.execute("INSERT INTO conversations (id) VALUES (%s)", (conversation_id,))
        return conversation_id

    async def exists(self, conversation_id: UUID) -> bool:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM conversations WHERE id = %s", (conversation_id,)
            )
            return await cursor.fetchone() is not None

    async def delete(self, conversation_id: UUID) -> bool:
        # The turns go with it (ON DELETE CASCADE).
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM conversations WHERE id = %s", (conversation_id,)
            )
            return cursor.rowcount > 0

    async def add_turn(
        self,
        conversation_id: UUID,
        role: MessageRole,
        text: str,
        citations: Sequence[str] = (),
    ) -> Turn:
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "INSERT INTO conversation_turns (id, conversation_id, role, text, citations) "
                "VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id, conversation_id, role, text, citations, created_at",
                (uuid.uuid4(), conversation_id, role.value, text, list(citations)),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING gave no row")
        return _to_turn(row)

    async def turns(self, conversation_id: UUID, limit: int | None = None) -> list[Turn]:
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT id, conversation_id, role, text, citations, created_at "
                "FROM conversation_turns WHERE conversation_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (conversation_id, limit),
            )
            rows = await cursor.fetchall()
        return [_to_turn(row) for row in reversed(rows)]
