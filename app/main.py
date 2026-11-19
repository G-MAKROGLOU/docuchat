from fastapi import FastAPI

from app.api import contract
from app.api.middleware import RequestIdMiddleware
from app.api.routers import health
from app.config import Settings, get_settings
from app.infrastructure.database import PostgresProbe
from app.infrastructure.logging import configure_logging
from app.infrastructure.tracing import NoopTracer

API_PREFIX = "/api/v1"


def create_api() -> FastAPI:
    """Routes and OpenAPI metadata only. Needs no settings, so the contract export can use it."""
    app = FastAPI(
        title="backend",
        version="1",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(contract.router, prefix=API_PREFIX)
    return app


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    app = create_api()
    app.state.settings = settings
    app.state.database_probe = PostgresProbe(settings.database_url.get_secret_value())
    app.state.tracer = NoopTracer()
    return app


app = create_app(get_settings())
