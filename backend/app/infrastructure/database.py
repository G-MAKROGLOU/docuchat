"""Database connections: the shared pool and the connectivity check."""

import asyncio
import logging
import math
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


def build_pool(settings: Settings) -> AsyncConnectionPool[psycopg.AsyncConnection[TupleRow]]:
    # Closed: the owner opens it in its own event loop. One retrieval uses 2 connections at once.
    # A slow query or a long wait for a connection fails the request instead of holding it.
    return AsyncConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        open=False,
        kwargs={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
        timeout=settings.db_pool_timeout_seconds,
        max_waiting=settings.db_pool_max_waiting,
        # One empty query per checkout: a connection that the server closed is replaced.
        check=AsyncConnectionPool.check_connection,
    )


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    connected: bool
    extensions: list[str]


class PostgresProbe:
    def __init__(self, database_url: str, timeout_seconds: float) -> None:
        self._database_url = database_url
        self._timeout_seconds = timeout_seconds

    async def check(self) -> DatabaseStatus:
        try:
            # One limit for connect and query, so a stalled server cannot hang /health.
            async with asyncio.timeout(self._timeout_seconds):
                async with await psycopg.AsyncConnection.connect(
                    self._database_url, connect_timeout=math.ceil(self._timeout_seconds)
                ) as conn:
                    cursor = await conn.execute("SELECT extname FROM pg_extension ORDER BY extname")
                    rows = await cursor.fetchall()
        except (psycopg.Error, TimeoutError) as exc:
            logger.warning("database check failed", extra={"error": type(exc).__name__})
            return DatabaseStatus(connected=False, extensions=[])
        return DatabaseStatus(connected=True, extensions=[str(row[0]) for row in rows])
