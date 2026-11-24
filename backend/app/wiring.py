"""Composition root of the API: chat, retrieval and the drug detector."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from app.application.chat import ChatLimits, ChatService, Retriever
from app.application.drug_detection import DetectorThresholds, DrugDetector, DrugEntry
from app.application.fusion import SearchLimits
from app.application.retrieval import RetrievalService
from app.application.versioned_cache import VersionedCache
from app.config import Settings
from app.domain.documents import Document, DocumentStatus
from app.domain.ports import TurnTracer
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.chunk_search import PostgresChunkSearch
from app.infrastructure.conversation_repository import PostgresConversationRepository
from app.infrastructure.database import Connections
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.models import ModelFactory
from app.infrastructure.name_similarity import RapidFuzzSimilarity
from app.runtime_defaults import with_models


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
                name=d.display_name,
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


def retrieval_service(
    settings: Settings, connections: Connections, runtime: RuntimeSettings
) -> RetrievalService:
    effective = with_models(settings, runtime)
    return RetrievalService(
        PostgresChunkSearch(
            connections,
            effective.embedding_model,
            title_boost=settings.search_title_boost,
            phrase_boost=settings.search_phrase_boost,
            hnsw_ef_search=settings.search_hnsw_ef_search,
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
            with_models(settings, runtime), reasoning_effort=runtime.reasoning_effort
        ).chat_models(),
        VersionedCache(
            documents.ingested_version, build, min_interval=settings.detector_rebuild_seconds
        ),
        retriever or retrieval_service(settings, connections, runtime),
        tracer,
        limits=chat_limits(settings),
        grader_mode=runtime.grader_mode,
    )
