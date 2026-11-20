"""A new connection per use: the tests call asyncio.run many times, and a pool binds one loop."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg


class DirectConnections:
    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        async with await psycopg.AsyncConnection.connect(self._conninfo) as conn:
            yield conn
