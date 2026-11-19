"""Database connectivity check."""

import asyncio
import logging
from dataclasses import dataclass

import psycopg

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    connected: bool
    extensions: list[str]


class PostgresProbe:
    def __init__(self, database_url: str, timeout_seconds: int = 3) -> None:
        self._database_url = database_url
        self._timeout_seconds = timeout_seconds

    async def check(self) -> DatabaseStatus:
        try:
            # One limit for connect and query, so a stalled server cannot hang /health.
            async with asyncio.timeout(self._timeout_seconds):
                async with await psycopg.AsyncConnection.connect(
                    self._database_url, connect_timeout=self._timeout_seconds
                ) as conn:
                    cursor = await conn.execute("SELECT extname FROM pg_extension ORDER BY extname")
                    rows = await cursor.fetchall()
        except (psycopg.Error, TimeoutError) as exc:
            logger.warning("database check failed", extra={"error": type(exc).__name__})
            return DatabaseStatus(connected=False, extensions=[])
        return DatabaseStatus(connected=True, extensions=[str(row[0]) for row in rows])
