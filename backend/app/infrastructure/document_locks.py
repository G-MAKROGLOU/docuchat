"""DocumentLocks adapter: one Postgres advisory lock per document, held on one pooled
connection while the document is ingested. The key is the low 63 bits of the document ID."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.infrastructure.database import Connections

# The same key in SQL, for statements that test the lock (see PostgresDocumentRepository).
LOCK_KEY_SQL = (
    "(('x' || right(replace(id::text, '-', ''), 16))::bit(64)::bigint & 9223372036854775807)"
)


def lock_key(document_id: UUID) -> int:
    return document_id.int & (2**63 - 1)


class PostgresDocumentLocks:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    @asynccontextmanager
    async def hold(self, document_id: UUID) -> AsyncIterator[bool]:
        key = lock_key(document_id)
        async with self._connections.connection() as conn:
            cursor = await conn.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = await cursor.fetchone()
            held = bool(row and row[0])
            try:
                yield held
            finally:
                if held:
                    await conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
