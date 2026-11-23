from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_ingestion_control
from app.api.schemas.status import IngestionStarted
from app.application.ingestion_control import IngestionControl

router = APIRouter(tags=["ingestion"])


@router.post(
    "/ingestion",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"description": "An ingestion pass is already running."}},
)
async def start_ingestion(
    control: Annotated[IngestionControl, Depends(get_ingestion_control)],
) -> IngestionStarted:
    if not await control.request():
        raise HTTPException(status.HTTP_409_CONFLICT, "An ingestion pass is already running.")
    return IngestionStarted(running=True)
