"""The pool replaces a connection that the server closed. Needs TEST_DATABASE_URL."""

import asyncio
import os

import psycopg
import pytest
from pydantic import SecretStr

from app.config import load_settings
from app.infrastructure.database import build_pool

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def test_the_pool_does_not_give_out_a_connection_that_the_server_closed() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    settings = load_settings().model_copy(update={"database_url": SecretStr(conninfo)})

    async def scenario() -> list[int]:
        async with build_pool(settings) as pool:
            await pool.wait()
            stats = pool.get_stats()
            # Hold all idle connections at once to learn the server PID of each one.
            async with pool.connection() as first, pool.connection() as second:
                pids = [first.info.backend_pid, second.info.backend_pid]
            assert stats["pool_size"] == 2
            # Same effect on the pooled connections as a server restart.
            async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as admin:
                await admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM unnest(%s::int[]) pid", (pids,)
                )
            results = []
            for _ in range(4):
                async with pool.connection() as conn:
                    row = await (await conn.execute("SELECT 1")).fetchone()
                    assert row is not None
                    results.append(row[0])
            return results

    assert asyncio.run(scenario()) == [1, 1, 1, 1]
