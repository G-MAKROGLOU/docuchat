from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.documents import DocumentStatus


class DocumentSummary(BaseModel):
    id: UUID
    brand_name: str
    generic_name: str
    page_count: int | None
    status: DocumentStatus
    ingested_at: datetime | None
    failure_reason: str | None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int
    page_size: int
