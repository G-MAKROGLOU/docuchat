from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_corpus_stats_repository, get_ingestion_control
from app.api.schemas.status import StatusResponse
from app.application.ingestion_control import IngestionControl
from app.domain.corpus_stats import CorpusStatsRepository
from app.domain.documents import DocumentStatus

router = APIRouter(tags=["status"])


@router.get("/status")
async def corpus_status(
    repository: Annotated[CorpusStatsRepository, Depends(get_corpus_stats_repository)],
    control: Annotated[IngestionControl, Depends(get_ingestion_control)],
) -> StatusResponse:
    stats = await repository.stats()
    counts = await repository.document_counts()
    ingestion = await control.status()
    return StatusResponse(
        chunk_count=stats.chunk_count,
        token_count=stats.token_count,
        embedding_models=stats.embedding_models,
        ingestion_running=ingestion.running,
        ingestion_phase=ingestion.phase,
        next_run_at=ingestion.next_run_at,
        document_counts={status.value: counts.get(status.value, 0) for status in DocumentStatus},
    )
