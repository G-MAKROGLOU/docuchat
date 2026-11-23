"""Postgres adapter for LabelQueueRepository."""

from collections.abc import Sequence
from typing import Any

from app.domain.label_queue import QueueEntry, QueueListing, QueueStatus
from app.infrastructure.database import Connections


def _entry(row: tuple[Any, ...]) -> QueueEntry:
    return QueueEntry(
        set_id=row[0],
        title=row[1],
        status=QueueStatus(row[2]),
        failure_reason=row[3],
        created_at=row[4],
    )


class PostgresLabelQueueRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def add(self, set_id: str, title: str) -> bool:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO label_queue (set_id, title, status) VALUES (%s, %s, 'queued') "
                "ON CONFLICT (set_id) DO UPDATE SET status = 'queued', failure_reason = NULL "
                "WHERE label_queue.status = 'failed'",
                (set_id, title),
            )
            return cursor.rowcount == 1

    async def list_page(self, page: int, page_size: int) -> QueueListing:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT set_id, title, status, failure_reason, created_at FROM label_queue "
                "ORDER BY (status = 'added'), created_at DESC, set_id LIMIT %s OFFSET %s",
                (page_size, (page - 1) * page_size),
            )
            entries = [_entry(row) for row in await cursor.fetchall()]
            cursor = await conn.execute("SELECT status, count(*) FROM label_queue GROUP BY status")
            counts = {row[0]: int(row[1]) for row in await cursor.fetchall()}
        return QueueListing(
            entries=entries,
            queued_total=counts.get("queued", 0),
            added_total=counts.get("added", 0),
            failed_total=counts.get("failed", 0),
        )

    async def next_queued(self, limit: int) -> list[QueueEntry]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT set_id, title, status, failure_reason, created_at "
                "FROM label_queue WHERE status = 'queued' "
                "ORDER BY created_at, set_id LIMIT %s",
                (limit,),
            )
            return [_entry(row) for row in await cursor.fetchall()]

    async def mark(self, set_id: str, status: QueueStatus, failure_reason: str | None) -> None:
        async with self._connections.connection() as conn:
            await conn.execute(
                "UPDATE label_queue SET status = %s, failure_reason = %s WHERE set_id = %s",
                (status.value, failure_reason, set_id),
            )

    async def known(self, set_ids: Sequence[str]) -> set[str]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT set_id FROM label_queue WHERE set_id = ANY(%s)", (list(set_ids),)
            )
            return {row[0] for row in await cursor.fetchall()}

    async def remove(self, set_id: str) -> bool:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM label_queue WHERE set_id = %s AND status <> 'added'", (set_id,)
            )
            return cursor.rowcount == 1
