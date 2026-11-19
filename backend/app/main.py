import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.factory import create_api
from app.config import Settings, get_settings
from app.infrastructure.database import PostgresProbe
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.migrations import apply_migrations
from app.infrastructure.storage import build_document_store
from app.infrastructure.tracing import build_tracer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await asyncio.to_thread(
            apply_migrations, app.state.settings.database_url.get_secret_value()
        )
        # The S3 adapter creates the bucket here when it is absent.
        app.state.document_store = await asyncio.to_thread(build_document_store, app.state.settings)
        yield
    finally:
        # Flush buffered spans off the event loop; a slow or unreachable host must not block it.
        await asyncio.to_thread(app.state.tracer.shutdown)


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    app = create_api(lifespan)
    app.state.settings = settings
    database_url = settings.database_url.get_secret_value()
    app.state.database_probe = PostgresProbe(database_url)
    app.state.document_repository = PostgresDocumentRepository(database_url)
    app.state.tracer = build_tracer(settings)
    return app


app = create_app(get_settings())
