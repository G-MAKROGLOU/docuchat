import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.factory import create_api
from app.application.ingestion_control import IngestionControl
from app.application.readiness import ReadinessCheck
from app.config import Settings, get_settings
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.cache import close_caches
from app.infrastructure.corpus_stats_repository import (
    CachedCorpusStats,
    PostgresCorpusStatsRepository,
)
from app.infrastructure.dailymed import DailyMedCatalog
from app.infrastructure.database import PostgresProbe, build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.ingestion_state_repository import PostgresIngestionStateRepository
from app.infrastructure.label_queue_repository import PostgresLabelQueueRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.metrics import process_stopped, watch_pool
from app.infrastructure.migrations import apply_migrations, check_vector_size
from app.infrastructure.models import close_model_clients
from app.infrastructure.runtime_settings_repository import PostgresRuntimeSettingsRepository
from app.infrastructure.storage import build_document_store
from app.infrastructure.tracing import build_tracer
from app.runtime_config import RuntimeConfig
from app.wiring import chat_service, default_runtime_settings, heartbeat_limit


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pool = app.state.document_repository = None
    try:
        await asyncio.to_thread(
            apply_migrations, app.state.settings.database_url.get_secret_value()
        )
        await asyncio.to_thread(
            check_vector_size,
            app.state.settings.database_url.get_secret_value(),
            app.state.settings.embedding_dimensions,
        )
        app.state.pool = build_pool(app.state.settings)
        await app.state.pool.open()
        app.state.document_repository = PostgresDocumentRepository(app.state.pool)
        app.state.corpus_stats_repository = CachedCorpusStats(
            PostgresCorpusStatsRepository(app.state.pool),
            app.state.document_repository.ingested_version,
            min_interval=app.state.settings.detector_rebuild_seconds,
        )
        # Passes run in the ingest worker (app.ingest_worker); this process only asks for them.
        app.state.ingestion_control = IngestionControl(
            PostgresIngestionStateRepository(app.state.pool), heartbeat_limit(app.state.settings)
        )

        async def rebuild(new: RuntimeSettings) -> Callable[[], None]:
            chat = chat_service(app.state.settings, app.state.pool, app.state.tracer, new)

            def commit() -> None:
                app.state.chat_service = chat

            return commit

        app.state.runtime_config = RuntimeConfig(
            PostgresRuntimeSettingsRepository(app.state.pool),
            default_runtime_settings(app.state.settings),
            rebuild,
            refresh_seconds=app.state.settings.runtime_refresh_seconds,
            request_pass=lambda: app.state.ingestion_control.request(force=True),
        )
        await app.state.runtime_config.load()
        # The S3 adapter creates the bucket here when it is absent.
        app.state.document_store = await asyncio.to_thread(build_document_store, app.state.settings)
        app.state.label_queue_repository = PostgresLabelQueueRepository(app.state.pool)
        app.state.label_catalog = DailyMedCatalog(
            timeout_seconds=app.state.settings.catalog_timeout_seconds,
            max_bytes=app.state.settings.source_max_bytes,
        )
        app.state.readiness_checks = readiness_checks(app)
        pool_watch = asyncio.create_task(
            watch_pool(app.state.pool, app.state.settings.pool_metrics_interval_seconds)
        )
        yield
        pool_watch.cancel()
    finally:
        process_stopped()
        await close_model_clients()
        await close_caches()
        if app.state.pool is not None:
            await app.state.pool.close()
        # Flush buffered spans off the event loop; a slow or unreachable host must not block it.
        await asyncio.to_thread(app.state.tracer.shutdown)


def readiness_checks(app: FastAPI) -> list[ReadinessCheck]:
    pool, store, control = app.state.pool, app.state.document_store, app.state.ingestion_control
    limit = heartbeat_limit(app.state.settings).total_seconds()

    async def database() -> tuple[bool, str | None]:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True, None

    async def storage() -> tuple[bool, str | None]:
        # A HEAD for a key that does not exist: it proves the bucket answers.
        await asyncio.to_thread(store.exists, "readiness-probe")
        return True, None

    async def worker() -> tuple[bool, str | None]:
        age = await control.heartbeat_age()
        if age is None:
            return False, "no heartbeat"
        return age <= limit, f"last heartbeat {age:.0f} s ago"

    return [
        ReadinessCheck("database", True, database),
        ReadinessCheck("storage", True, storage),
        ReadinessCheck("worker", False, worker),
    ]


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    app = create_api(lifespan)
    app.state.settings = settings
    database_url = settings.database_url.get_secret_value()
    app.state.database_probe = PostgresProbe(database_url, settings.db_probe_timeout_seconds)
    app.state.thumbnail_slots = asyncio.Semaphore(settings.thumbnail_concurrency)
    app.state.tracer = build_tracer(settings)
    return app


app = create_app(get_settings())
