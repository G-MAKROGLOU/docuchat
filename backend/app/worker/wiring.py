"""Composition root of the ingest worker and corpus-init. It must not import the chat code."""

from app.application.ingestion import IngestionService, IngestLimits
from app.application.page_locator import LocatorLimits
from app.config import Settings
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.database import Connections
from app.infrastructure.document_locks import PostgresDocumentLocks
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.models import ModelFactory
from app.infrastructure.pdf_parser import PyMuPdfParser
from app.infrastructure.spl_parser import SplXmlParser
from app.infrastructure.storage import shared_document_store
from app.infrastructure.text_splitting import SentenceTokenSplitter, TiktokenCounter
from app.runtime_defaults import with_models


def ingest_limits(settings: Settings) -> IngestLimits:
    return IngestLimits(
        anchor_words=settings.chunk_anchor_words,
        max_page_misses=settings.ingest_max_page_misses,
        failure_reason_max_chars=settings.failure_reason_max_chars,
        locator=LocatorLimits(
            window=settings.locator_window,
            min_piece=settings.locator_min_piece,
            slack=settings.locator_slack,
            max_span=settings.locator_max_span,
        ),
    )


def ingestion_service(
    settings: Settings, connections: Connections, runtime: RuntimeSettings
) -> IngestionService:
    effective = with_models(settings, runtime)
    return IngestionService(
        store=shared_document_store(settings),
        documents=PostgresDocumentRepository(connections),
        chunks=PostgresChunkRepository(connections),
        pdf_parser=PyMuPdfParser(settings.pdf_row_tolerance),
        label_parser=SplXmlParser(),
        splitter=SentenceTokenSplitter(
            chunk_tokens=runtime.chunk_tokens, overlap_tokens=runtime.overlap_tokens
        ),
        counter=TiktokenCounter(),
        embedder=ModelFactory(effective).embedder(),
        embedding_model=effective.embedding_model,
        embedding_prefix=settings.embedding_prefix,
        limits=ingest_limits(settings),
        locks=PostgresDocumentLocks(connections),
    )
