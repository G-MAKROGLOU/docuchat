from datetime import datetime

from pydantic import BaseModel

from app.domain.ingestion_state import IngestionPhase


class StatusResponse(BaseModel):
    chunk_count: int
    token_count: int
    embedding_models: list[str]
    ingestion_running: bool
    ingestion_phase: IngestionPhase
    next_run_at: datetime | None
    # Documents by status (stored, ingesting, ingested, failed), so a client needs no list.
    document_counts: dict[str, int]


class IngestionStarted(BaseModel):
    running: bool
