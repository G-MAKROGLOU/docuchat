"""Composition root: the API and the commands build their services here."""

from collections.abc import Iterable

from app.application.drug_detection import DrugDetector, DrugEntry
from app.application.ingestion import IngestionService
from app.application.retrieval import RetrievalService
from app.config import Settings
from app.domain.documents import Document, DocumentStatus
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.chunk_search import PostgresChunkSearch
from app.infrastructure.database import Connections
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.models import ModelFactory
from app.infrastructure.name_similarity import RapidFuzzSimilarity
from app.infrastructure.pdf_parser import PyMuPdfParser
from app.infrastructure.storage import build_document_store
from app.infrastructure.text_splitting import SentenceTokenSplitter, TiktokenCounter


def drug_detector(documents: Iterable[Document]) -> DrugDetector:
    """The catalog: one entry per ingested label, named by brand, else by generic name."""
    return DrugDetector(
        [
            DrugEntry(
                name=d.brand_name or d.generic_name, brand=d.brand_name, generic=d.generic_name
            )
            for d in documents
            if d.status is DocumentStatus.INGESTED
        ],
        RapidFuzzSimilarity(),
    )


def retrieval_service(settings: Settings, connections: Connections) -> RetrievalService:
    return RetrievalService(
        PostgresChunkSearch(connections),
        ModelFactory(settings).embedder(),
        settings.embedding_model,
    )


def ingestion_service(settings: Settings, connections: Connections) -> IngestionService:
    return IngestionService(
        store=build_document_store(settings),
        documents=PostgresDocumentRepository(connections),
        chunks=PostgresChunkRepository(connections),
        parser=PyMuPdfParser(),
        splitter=SentenceTokenSplitter(chunk_tokens=500, overlap_tokens=50),
        counter=TiktokenCounter(),
        embedder=ModelFactory(settings).embedder(),
        embedding_model=settings.embedding_model,
        embedding_prefix=settings.embedding_prefix,
    )
