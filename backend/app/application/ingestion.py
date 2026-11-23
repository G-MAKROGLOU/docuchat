"""Ingest one stored label: sections from the SPL XML, pages from the PDF, then chunks,
embeddings and storage. Idempotent."""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.chunking import build_chunks, embedding_input
from app.application.label_sections import split_sections
from app.application.page_locator import PageLocator
from app.domain.documents import (
    Document,
    DocumentLocks,
    DocumentStatus,
    IngestionStatusRepository,
)
from app.domain.entities import Chunk
from app.domain.ports import (
    ChunkRepository,
    DocumentParser,
    Embedder,
    LabelParser,
    TextSplitter,
    TokenCounter,
)
from app.domain.storage import DocumentStore, ObjectNotFoundError, label_key

logger = logging.getLogger(__name__)
# More chunks than this share without a page match means the PDF is another version.
MAX_PAGE_MISSES = 0.2
FAILURE_REASON_MAX = 500


def public_reason(exc: Exception) -> str:
    """The failure text that the API returns. Our own checks raise ValueError with a message
    for the user; driver, S3 and HTTP messages can hold hosts or SQL, so only their type."""
    text = str(exc) if isinstance(exc, ValueError) else ""
    return (text or type(exc).__name__)[:FAILURE_REASON_MAX]


@dataclass(frozen=True, slots=True)
class IngestResult:
    document_id: UUID
    skipped: bool = False
    chunks: int = 0
    tokens: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionService:
    store: DocumentStore
    documents: IngestionStatusRepository
    chunks: ChunkRepository
    pdf_parser: DocumentParser
    label_parser: LabelParser
    splitter: TextSplitter
    counter: TokenCounter
    embedder: Embedder
    embedding_model: str
    embedding_prefix: bool
    # Keeps the ingest worker and the ingest command off the same document.
    locks: DocumentLocks | None = None

    async def ingest(self, document: Document, *, force: bool = False) -> IngestResult:
        """force: ingest again even when done, after a parser or embedding-input change."""
        if self.locks is None:
            return await self._ingest_unlocked(document, force=force)
        async with self.locks.hold(document.id) as held:
            if not held:
                return IngestResult(document.id, skipped=True)
            return await self._ingest_unlocked(document, force=force)

    async def _ingest_unlocked(self, document: Document, *, force: bool) -> IngestResult:
        if (
            not force
            and document.status is DocumentStatus.INGESTED
            and await self.chunks.embedding_models(document.id) == {self.embedding_model}
        ):
            return IngestResult(document.id, skipped=True)

        await self.documents.update_ingestion(document.id, DocumentStatus.INGESTING)
        try:
            return await self._ingest(document)
        except Exception as exc:
            logger.exception("ingestion failed", extra={"document_id": str(document.id)})
            error = public_reason(exc)
            await self.documents.update_ingestion(
                document.id, DocumentStatus.FAILED, failure_reason=error
            )
            return IngestResult(document.id, error=error)

    async def _ingest(self, document: Document) -> IngestResult:
        page_count, form, drafts = await asyncio.to_thread(self._chunks, document)

        inputs = [
            embedding_input(
                document.brand_name,
                document.generic_name,
                f"{c.section_number} {c.section_title}",
                c.content,
                prefix=self.embedding_prefix,
                context=c.table_header,
            )
            for c in drafts
        ]
        vectors = await self.embedder.embed_documents(inputs)
        chunks = [
            replace(c, embedding=tuple(v), embedding_model=self.embedding_model)
            for c, v in zip(drafts, vectors, strict=True)
        ]
        await self.chunks.replace_for_document(document.id, chunks)
        await self.documents.update_ingestion(
            document.id,
            DocumentStatus.INGESTED,
            page_count,
            datetime.now(UTC),
            dosage_form=form,
        )
        return IngestResult(
            document.id, chunks=len(chunks), tokens=sum(self.counter.count(t) for t in inputs)
        )

    def _chunks(self, document: Document) -> tuple[int, str, list[Chunk]]:
        """Parse, split and locate in a worker thread: this is CPU work."""
        pdf = b"".join(self.store.get_stream(document.storage_key))
        try:
            label = b"".join(self.store.get_stream(label_key(document.id)))
        except ObjectNotFoundError as exc:
            raise ValueError("The label XML is not stored; run the corpus download") from exc
        pages = self.pdf_parser.page_texts(pdf)
        sections = split_sections(self.label_parser.sections(label))
        locator = PageLocator(pages)
        drafts = build_chunks(document, sections, self.splitter, self.counter, locator.locate_all)
        if not drafts:
            raise ValueError("The label gave no chunks")
        if locator.misses > MAX_PAGE_MISSES * len(drafts):
            raise ValueError(
                f"The PDF does not match the label XML: {locator.misses} of {len(drafts)} "
                "chunks are not in the PDF"
            )
        if locator.misses:
            logger.info(
                "chunk pages not found",
                extra={"document_id": str(document.id), "misses": locator.misses},
            )
        return len(pages), self.label_parser.dosage_form(label), drafts
