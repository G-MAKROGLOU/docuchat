"""Database connections: the shared pool and the connectivity check."""

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from app.config import Settings

logger = logging.getLogger(__name__)


class Connections(Protocol):
    def connection(self) -> AbstractAsyncContextManager[psycopg.AsyncConnection[Any]]: ...


# A slow query or a long wait for a connection fails the request instead of holding it.
STATEMENT_TIMEOUT_MS = 30_000
POOL_TIMEOUT_SECONDS = 10.0
POOL_MAX_WAITING = 256


def build_pool(settings: Settings) -> AsyncConnectionPool[psycopg.AsyncConnection[TupleRow]]:
    # Closed: the owner opens it in its own event loop. One retrieval uses 2 connections at once.
    return AsyncConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=2,
        max_size=10,
        open=False,
        kwargs={"options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"},
        timeout=POOL_TIMEOUT_SECONDS,
        max_waiting=POOL_MAX_WAITING,
    )


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
