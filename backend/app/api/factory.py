from fastapi import FastAPI, Response
from starlette.types import Lifespan

from app.api import contract
from app.api.middleware import RequestIdMiddleware
from app.api.routers import chat, documents, health, ingestion, labels, settings, status
from app.infrastructure.metrics import render

API_PREFIX = "/api/v1"


def create_api(lifespan: Lifespan[FastAPI] | None = None) -> FastAPI:
    """Routes and OpenAPI metadata only. Needs no settings, so the contract export can use it."""
    app = FastAPI(
        title="backend",
        version="1",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(contract.router, prefix=API_PREFIX)
    app.include_router(documents.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)
    app.include_router(status.router, prefix=API_PREFIX)
    app.include_router(ingestion.router, prefix=API_PREFIX)
    app.include_router(labels.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        # Outside /api: the frontend proxy does not forward it; only Prometheus reads it.
        body, content_type = render()
        return Response(body, media_type=content_type)

    return app
