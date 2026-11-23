from typing import Annotated, Protocol, cast

from fastapi import Depends, Request

from app.application.chat import ChatService
from app.application.ingestion_control import IngestionControl
from app.application.readiness import ReadinessCheck
from app.application.settings_service import EmbeddingChoices, KnownModels, SettingsService
from app.config import Settings
from app.domain.corpus_stats import CorpusStatsRepository
from app.domain.documents import DocumentRepository, PageRenderer
from app.domain.label_queue import LabelCatalog, LabelQueueRepository
from app.domain.ports import Cache
from app.domain.storage import DocumentStore
from app.infrastructure.cache import shared_cache
from app.infrastructure.database import DatabaseStatus
from app.infrastructure.models import ModelFactory
from app.infrastructure.pdf_thumbnail import PyMuPdfPageRenderer
from app.runtime_config import RuntimeConfig


class DatabaseProbe(Protocol):
    async def check(self) -> DatabaseStatus: ...


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database_probe(request: Request) -> DatabaseProbe:
    return cast(DatabaseProbe, request.app.state.database_probe)


def get_document_repository(request: Request) -> DocumentRepository:
    return cast(DocumentRepository, request.app.state.document_repository)


def get_corpus_stats_repository(request: Request) -> CorpusStatsRepository:
    return cast(CorpusStatsRepository, request.app.state.corpus_stats_repository)


def get_ingestion_control(request: Request) -> IngestionControl:
    return cast(IngestionControl, request.app.state.ingestion_control)


def get_document_store(request: Request) -> DocumentStore:
    return cast(DocumentStore, request.app.state.document_store)


def get_page_renderer() -> PageRenderer:
    return PyMuPdfPageRenderer()


async def get_chat_service(request: Request) -> ChatService:
    # Another process may have saved new settings; the refresh swaps the service then.
    await cast(RuntimeConfig, request.app.state.runtime_config).refresh()
    return cast(ChatService, request.app.state.chat_service)


def get_label_queue_repository(request: Request) -> LabelQueueRepository:
    return cast(LabelQueueRepository, request.app.state.label_queue_repository)


def get_label_catalog(request: Request) -> LabelCatalog:
    return cast(LabelCatalog, request.app.state.label_catalog)


async def get_runtime_config(request: Request) -> RuntimeConfig:
    config = cast(RuntimeConfig, request.app.state.runtime_config)
    await config.refresh()
    return config


def get_known_models(request: Request) -> KnownModels:
    return ModelFactory(request.app.state.settings).known_model_ids


def get_embedding_choices(request: Request) -> EmbeddingChoices:
    return ModelFactory(request.app.state.settings).embedding_choices


def get_settings_service(
    config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
    control: Annotated[IngestionControl, Depends(get_ingestion_control)],
    known_models: Annotated[KnownModels, Depends(get_known_models)],
    embedding_choices: Annotated[EmbeddingChoices, Depends(get_embedding_choices)],
) -> SettingsService:
    return SettingsService(config, control, known_models, embedding_choices)


def get_cache(request: Request) -> Cache:
    return shared_cache(request.app.state.settings)


def get_readiness_checks(request: Request) -> list[ReadinessCheck]:
    return cast(list[ReadinessCheck], request.app.state.readiness_checks)
