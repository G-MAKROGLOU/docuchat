"""Source documents (drug labels) and their repository port. No framework imports."""

from contextlib import AbstractAsyncContextManager
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
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentPage:
    """One page of a document list, plus the number of all matches."""

    items: list[Document]
    total: int


class LabelSource(Protocol):
    """A public source of labels, addressed by its own document ID."""

    def fetch_pdf(self, source_id: str) -> bytes: ...

    def fetch_label(self, source_id: str) -> bytes:
        """The structured label (SPL XML)."""
        ...


class DocumentLocks(Protocol):
    def hold(self, document_id: UUID) -> AbstractAsyncContextManager[bool]:
        """Holds the document's lock while the block runs; yields False when another process
        holds it already."""
        ...


class IngestionStatusRepository(Protocol):
    async def update_ingestion(
        self,
        document_id: UUID,
        status: DocumentStatus,
        page_count: int | None = None,
        ingested_at: datetime | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """Set the status and the failure reason (cleared when None); set page_count and
        ingested_at only when given."""
        ...


class DocumentRepository(IngestionStatusRepository, Protocol):
    async def add(self, document: Document) -> None: ...

    async def list_all(self) -> list[Document]: ...

    async def known_source_ids(self, source_ids: list[str]) -> set[str]:
        """The given set IDs that the library holds already."""
        ...

    async def get(self, document_id: UUID) -> Document | None: ...

    async def find_by_source_id(self, source_id: str) -> Document | None: ...

    async def find_by_sha256(self, sha256: str) -> Document | None: ...

    async def replace_content(
        self, document_id: UUID, storage_key: str, sha256: str, size_bytes: int
    ) -> None:
        """Point the document at new content and set it back to stored, to be ingested again."""
        ...

    async def search(self, query: str, limit: int, offset: int) -> DocumentPage:
        """Documents whose brand or generic name contains the query, case-insensitive.
        An empty query matches all. Order: brand name (generic name if empty), then ID."""
        ...


class PageRenderer(Protocol):
    def render_first_page(self, pdf: bytes, width: int) -> bytes:
        """Page 1 of the PDF as a PNG, scaled to the width in pixels."""
        ...
