from fastapi import FastAPI
from starlette.types import Lifespan

from app.api import contract
from app.api.middleware import RequestIdMiddleware
from app.api.routers import documents, health

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
    return app
