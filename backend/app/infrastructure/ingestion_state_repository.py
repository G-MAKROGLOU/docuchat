"""Postgres adapter for IngestionStateRepository: the one row in ingestion_state."""

from datetime import datetime
from typing import cast

from app.domain.ingestion_state import IngestionPhase, IngestionState
from app.infrastructure.database import Connections


class PostgresIngestionStateRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def load(self) -> IngestionState:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT phase, requested_at IS NOT NULL, next_run_at, heartbeat_at "
                "FROM ingestion_state WHERE id = 1"
            )
            row = await cursor.fetchone()
        if row is None:
            return IngestionState("idle", requested=False, next_run_at=None, heartbeat_at=None)
        return IngestionState(cast(IngestionPhase, row[0]), row[1], row[2], row[3])

    async def request(self, *, force: bool) -> None:
        async with self._connections.connection() as conn:
            await conn.execute(
                "UPDATE ingestion_state SET requested_at = coalesce(requested_at, now()), "
                "force_requested = force_requested OR %s WHERE id = 1",
                (force,),
            )

    async def take(self) -> bool | None:
        async with self._connections.connection() as conn:
            # The subquery reads the flag before the update clears it.
            cursor = await conn.execute(
                "UPDATE ingestion_state s SET requested_at = NULL, force_requested = false "
                "FROM (SELECT force_requested FROM ingestion_state "
                "      WHERE id = 1 AND requested_at IS NOT NULL FOR UPDATE) old "
                "WHERE s.id = 1 RETURNING old.force_requested"
            )
            row = await cursor.fetchone()
        return None if row is None else bool(row[0])

    async def report(self, phase: IngestionPhase, next_run_at: datetime | None) -> None:
        async with self._connections.connection() as conn:
            await conn.execute(
                "UPDATE ingestion_state SET phase = %s, next_run_at = %s, heartbeat_at = now() "
                "WHERE id = 1",
                (phase, next_run_at),
            )
