from fastapi import FastAPI

from app.api.middleware import RequestIdMiddleware
from app.api.routers import health
from app.config import Settings, get_settings
from app.infrastructure.database import PostgresProbe
from app.infrastructure.logging import configure_logging
from app.infrastructure.tracing import NoopTracer


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    app = FastAPI(title="backend")
    app.state.settings = settings
    app.state.database_probe = PostgresProbe(settings.database_url.get_secret_value())
    app.state.tracer = NoopTracer()
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    return app


app = create_app(get_settings())
