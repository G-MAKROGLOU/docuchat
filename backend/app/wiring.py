"""Composition root: the API and the commands build their services here."""

from collections.abc import Iterable
from datetime import UTC, datetime

from app.application.chat import ChatService, Retriever
from app.application.drug_detection import DetectorCache, DrugDetector, DrugEntry
from app.application.ingestion import IngestionService
from app.application.retrieval import TOP_K, RetrievalService
from app.application.runtime_settings import load_runtime_settings
from app.config import Settings
from app.domain.documents import Document, DocumentStatus
from app.domain.ports import TurnTracer
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.chunk_search import PostgresChunkSearch
from app.infrastructure.conversation_repository import PostgresConversationRepository
from app.infrastructure.database import Connections
from app.infrastructure.document_locks import PostgresDocumentLocks
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.models import ModelFactory
from app.infrastructure.name_similarity import RapidFuzzSimilarity
from app.infrastructure.pdf_parser import PyMuPdfParser
from app.infrastructure.runtime_settings_repository import PostgresRuntimeSettingsRepository
from app.infrastructure.spl_parser import SplXmlParser
from app.infrastructure.storage import shared_document_store
from app.infrastructure.text_splitting import SentenceTokenSplitter, TiktokenCounter


def drug_detector(documents: Iterable[Document]) -> DrugDetector:
    """The catalog: one entry per ingested label, named by brand, else by generic name. Brand
    labels come first, then the newest: the first label of a product answers for it."""
    ingested = [d for d in documents if d.status is DocumentStatus.INGESTED]
    ingested.sort(key=lambda d: d.ingested_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    ingested.sort(key=lambda d: not _is_brand(d))  # stable: newest first within each group
    return DrugDetector(
        [
            DrugEntry(
                name=d.brand_name or d.generic_name,
                brand=d.brand_name,
                generic=d.generic_name,
                label=d.id,
                form=d.dosage_form,
            )
            for d in ingested
        ],
        RapidFuzzSimilarity(),
    )


def _is_brand(document: Document) -> bool:
    brand = document.brand_name.strip().casefold()
    return bool(brand) and brand != document.generic_name.strip().casefold()


def default_runtime_settings(settings: Settings) -> RuntimeSettings:
    """The values that apply until the user saves others."""
    return RuntimeSettings(
        chunk_tokens=500,
        overlap_tokens=50,
        top_k=TOP_K,
        embedding_model=settings.embedding_model,
        chat_model=settings.llm_chat_model,
        rewrite_model=settings.llm_rewrite_model,
        grade_model=settings.llm_grade_model,
        generate_model=settings.llm_generate_model,
        reasoning_effort="low",
        grader_mode=settings.grader_mode,
    )


async def runtime_settings(settings: Settings, connections: Connections) -> RuntimeSettings:
    """The saved runtime settings over the defaults."""
    return await load_runtime_settings(
        default_runtime_settings(settings), PostgresRuntimeSettingsRepository(connections)
    )


def _with_models(settings: Settings, runtime: RuntimeSettings) -> Settings:
    return settings.model_copy(
        update={
            "llm_chat_model": runtime.chat_model,
            "llm_rewrite_model": runtime.rewrite_model,
            "llm_grade_model": runtime.grade_model,
            "llm_generate_model": runtime.generate_model,
            "embedding_model": runtime.embedding_model,
        }
    )


def retrieval_service(
    settings: Settings, connections: Connections, runtime: RuntimeSettings
) -> RetrievalService:
    effective = _with_models(settings, runtime)
    return RetrievalService(
        PostgresChunkSearch(connections, effective.embedding_model),
        ModelFactory(effective).embedder(),
        top_k=runtime.top_k,
    )


def chat_service(
    settings: Settings,
    connections: Connections,
    tracer: TurnTracer,
    runtime: RuntimeSettings,
    retriever: Retriever | None = None,
) -> ChatService:
    """retriever replaces the default search, for the eval ablations."""
    documents = PostgresDocumentRepository(connections)

    async def build() -> DrugDetector:
        return drug_detector(await documents.list_all())

    return ChatService(
        PostgresConversationRepository(connections),
        ModelFactory(
            _with_models(settings, runtime), reasoning_effort=runtime.reasoning_effort
        ).chat_models(),
        DetectorCache(documents.ingested_version, build),
        retriever or retrieval_service(settings, connections, runtime),
        tracer,
        grader_mode=runtime.grader_mode,
    )


def ingestion_service(
    settings: Settings, connections: Connections, runtime: RuntimeSettings
) -> IngestionService:
    effective = _with_models(settings, runtime)
    return IngestionService(
        store=shared_document_store(settings),
        documents=PostgresDocumentRepository(connections),
        chunks=PostgresChunkRepository(connections),
        pdf_parser=PyMuPdfParser(),
        label_parser=SplXmlParser(),
        splitter=SentenceTokenSplitter(
            chunk_tokens=runtime.chunk_tokens, overlap_tokens=runtime.overlap_tokens
        ),
        counter=TiktokenCounter(),
        embedder=ModelFactory(effective).embedder(),
        embedding_model=effective.embedding_model,
        embedding_prefix=settings.embedding_prefix,
        locks=PostgresDocumentLocks(connections),
    )
