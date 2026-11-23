"""Composition root: the API and the commands build their services here."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from app.application.chat import ChatLimits, ChatService, Retriever
from app.application.drug_detection import (
    DetectorCache,
    DetectorThresholds,
    DrugDetector,
    DrugEntry,
)
from app.application.fusion import SearchLimits
from app.application.ingestion import IngestionService, IngestLimits
from app.application.page_locator import LocatorLimits
from app.application.retrieval import RetrievalService
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


def chat_limits(settings: Settings) -> ChatLimits:
    return ChatLimits(
        history_turns=settings.chat_history_turns,
        max_query_chars=settings.chat_max_query_chars,
        grade_retries=settings.chat_grade_retries,
        turn_deadline_seconds=settings.chat_turn_deadline_seconds,
        max_reply_chars=settings.chat_max_reply_chars,
        intake_list_max=settings.chat_intake_list_max,
        max_suggestions=settings.chat_max_suggestions,
        max_suggestion_chars=settings.chat_max_suggestion_chars,
    )


def search_limits(settings: Settings) -> SearchLimits:
    return SearchLimits(
        rrf_k=settings.search_rrf_k,
        max_chunks=settings.search_max_chunks,
        token_budget=settings.search_token_budget,
        min_per_drug=settings.search_min_per_drug,
        leg_timeout_seconds=settings.search_leg_timeout_seconds,
    )


def detector_thresholds(settings: Settings) -> DetectorThresholds:
    return DetectorThresholds(
        min_key_length=settings.detector_min_key_length,
        min_tail_length=settings.detector_min_tail_length,
        fuzzy_threshold=settings.detector_fuzzy_threshold,
        candidate_floor=settings.detector_candidate_floor,
        ambiguity_margin=settings.detector_ambiguity_margin,
        max_choices=settings.detector_max_choices,
    )


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


def heartbeat_limit(settings: Settings) -> timedelta:
    return timedelta(seconds=settings.worker_heartbeat_limit_seconds)


def drug_detector(documents: Iterable[Document], thresholds: DetectorThresholds) -> DrugDetector:
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
        thresholds,
    )


def _is_brand(document: Document) -> bool:
    brand = document.brand_name.strip().casefold()
    return bool(brand) and brand != document.generic_name.strip().casefold()


def default_runtime_settings(settings: Settings) -> RuntimeSettings:
    """The values that apply until the user saves others."""
    return RuntimeSettings(
        chunk_tokens=settings.default_chunk_tokens,
        overlap_tokens=settings.default_overlap_tokens,
        top_k=settings.default_top_k,
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
        PostgresChunkSearch(
            connections,
            effective.embedding_model,
            title_boost=settings.search_title_boost,
            phrase_boost=settings.search_phrase_boost,
        ),
        ModelFactory(effective).embedder(),
        top_k=runtime.top_k,
        limits=search_limits(settings),
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
        return drug_detector(await documents.list_all(), detector_thresholds(settings))

    return ChatService(
        PostgresConversationRepository(connections),
        ModelFactory(
            _with_models(settings, runtime), reasoning_effort=runtime.reasoning_effort
        ).chat_models(),
        DetectorCache(
            documents.ingested_version, build, min_interval=settings.detector_rebuild_seconds
        ),
        retriever or retrieval_service(settings, connections, runtime),
        tracer,
        limits=chat_limits(settings),
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
