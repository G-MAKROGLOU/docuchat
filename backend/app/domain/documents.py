"""Source documents (drug labels) and their repository port. No framework imports."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class DocumentStatus(StrEnum):
    STORED = "stored"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Document:
    id: UUID
    brand_name: str
    generic_name: str
    manufacturer: str
    source_id: str
    storage_key: str
    sha256: str
    size_bytes: int
    status: DocumentStatus
    page_count: int | None = None
    ingested_at: datetime | None = None


class LabelSource(Protocol):
    """A public source of label PDFs, addressed by its own document ID."""

    def fetch_pdf(self, source_id: str) -> bytes: ...


class DocumentRepository(Protocol):
    async def add(self, document: Document) -> None: ...

    async def get(self, document_id: UUID) -> Document | None: ...

    async def find_by_source_id(self, source_id: str) -> Document | None: ...

    async def find_by_sha256(self, sha256: str) -> Document | None: ...
