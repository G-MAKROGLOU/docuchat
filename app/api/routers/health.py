from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import DatabaseProbe, get_database_probe
from app.api.schemas.health import DatabaseHealth, HealthResponse

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
