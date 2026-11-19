from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api.factory import create_api
from app.config import Settings, get_settings
from app.infrastructure.database import PostgresProbe
from app.infrastructure.logging import configure_logging
from app.infrastructure.storage import build_document_store
from app.infrastructure.tracing import NoopTracer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The S3 adapter creates the bucket here when it is absent.
    app.state.document_store = await run_in_threadpool(build_document_store, app.state.settings)
    yield


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    app = create_api(lifespan)
    app.state.settings = settings
    app.state.database_probe = PostgresProbe(settings.database_url.get_secret_value())
    app.state.tracer = NoopTracer()
    return app


app = create_app(get_settings())
