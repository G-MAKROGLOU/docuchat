"""Ingest one stored label: parse, split into sections and chunks, embed, store. Idempotent.
The corpus command and the upload endpoint use this service."""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.chunking import build_chunks, embedding_input
from app.application.label_sections import split_sections
from app.domain.documents import Document, DocumentStatus, IngestionStatusRepository
from app.domain.ports import ChunkRepository, DocumentParser, Embedder, TextSplitter, TokenCounter
from app.domain.storage import DocumentStore

logger = logging.getLogger(__name__)


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
    parser: DocumentParser
    splitter: TextSplitter
    counter: TokenCounter
    embedder: Embedder
    embedding_model: str
    embedding_prefix: bool

    async def ingest(self, document: Document, *, force: bool = False) -> IngestResult:
        """force: ingest again even when done, after a parser or embedding-input change."""
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
            await self.documents.update_ingestion(document.id, DocumentStatus.FAILED)
            return IngestResult(document.id, error=f"{type(exc).__name__}: {exc}")

    async def _ingest(self, document: Document) -> IngestResult:
        data = await asyncio.to_thread(
            lambda: b"".join(self.store.get_stream(document.storage_key))
        )
        page_count, lines = await asyncio.to_thread(self.parser.extract_lines, data)
        drug_name = document.brand_name or document.generic_name
        drafts = build_chunks(
            document.id, drug_name, split_sections(lines), self.splitter, self.counter
        )
        if not drafts:
            raise ValueError("The label gave no chunks")

        inputs = [
            embedding_input(
                document.brand_name,
                document.generic_name,
                f"{c.section_number} {c.section_title}",
                c.content,
                prefix=self.embedding_prefix,
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
            document.id, DocumentStatus.INGESTED, page_count, datetime.now(UTC)
        )
        return IngestResult(
            document.id, chunks=len(chunks), tokens=sum(self.counter.count(t) for t in inputs)
        )
