from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import (
    DatabaseProbe,
    get_app_settings,
    get_database_probe,
    get_readiness_checks,
)
from app.api.schemas.health import DatabaseHealth, HealthResponse, ReadyCheck, ReadyResponse
from app.application.readiness import ReadinessCheck, run_checks
from app.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    response: Response, probe: Annotated[DatabaseProbe, Depends(get_database_probe)]
) -> HealthResponse:
    db = await probe.check()
    if not db.connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if db.connected else "degraded",
        database=DatabaseHealth(connected=db.connected, extensions=db.extensions),
    )


@router.get(
    "/ready",
    responses={503: {"model": ReadyResponse, "description": "A required check failed."}},
)
async def ready(
    response: Response,
    checks: Annotated[list[ReadinessCheck], Depends(get_readiness_checks)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ReadyResponse:
    """Whether this process can serve requests: database and storage are required, the ingest
    worker is optional (a stale worker does not stop chat)."""
    is_ready, results = await run_checks(checks, settings.readiness_check_timeout_seconds)
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if is_ready else "not_ready",
        checks=[
            ReadyCheck(
                name=r.name,
                ok=r.ok,
                required=r.required,
                detail=r.detail,
                duration_ms=r.duration_ms,
            )
            for r in results
        ],
    )
