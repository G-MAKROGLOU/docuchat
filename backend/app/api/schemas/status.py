from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class StatusResponse(BaseModel):
    chunk_count: int
    token_count: int
    embedding_models: list[str]
    ingestion_running: bool
    ingestion_phase: Literal["idle", "checking", "downloading", "ingesting"]
    next_run_at: datetime | None
    # Documents by status (stored, ingesting, ingested, failed), so a client needs no list.
    document_counts: dict[str, int]


class IngestionStarted(BaseModel):
    running: bool
