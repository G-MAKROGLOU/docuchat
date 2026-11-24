"""Start-up steps that the API, the ingest worker and the corpus fill share."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.infrastructure.database import build_pool
from app.infrastructure.migrations import apply_migrations, check_vector_size
from app.infrastructure.runtime_settings_repository import PostgresRuntimeSettingsRepository
from app.runtime_config import Rebuild, RuntimeConfig
from app.runtime_defaults import default_runtime_settings

Pool = AsyncConnectionPool[psycopg.AsyncConnection[TupleRow]]


@asynccontextmanager
async def open_database(settings: Settings) -> AsyncIterator[Pool]:
    """Applies the migrations and checks the vector column size, then yields an open pool."""
    database_url = settings.database_url.get_secret_value()
    await asyncio.to_thread(apply_migrations, database_url)
    await asyncio.to_thread(check_vector_size, database_url, settings.embedding_dimensions)
    async with build_pool(settings) as pool:
        yield pool


async def load_runtime_config(
    settings: Settings,
    pool: Pool,
    rebuild: Rebuild,
    request_pass: Callable[[], Awaitable[bool]] | None = None,
) -> RuntimeConfig:
    """The saved runtime settings over the defaults, loaded; rebuild builds their services."""
    config = RuntimeConfig(
        PostgresRuntimeSettingsRepository(pool),
        default_runtime_settings(settings),
        rebuild,
        refresh_seconds=settings.runtime_refresh_seconds,
        request_pass=request_pass,
    )
    await config.load()
    return config
