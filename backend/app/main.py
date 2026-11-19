from fastapi import FastAPI

from app.api.factory import create_api
from app.config import Settings, get_settings
from app.infrastructure.database import PostgresProbe
from app.infrastructure.logging import configure_logging
from app.infrastructure.tracing import NoopTracer


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    app = create_api()
    app.state.settings = settings
    app.state.database_probe = PostgresProbe(settings.database_url.get_secret_value())
    app.state.tracer = NoopTracer()
    return app


app = create_app(get_settings())
