import asyncio
from typing import Any, cast

from app.config import load_settings
from app.domain.entities import ModelRole
from app.infrastructure import models
from app.infrastructure.cache import CachedChatModel
from app.infrastructure.models import ModelFactory, close_model_clients
from app.infrastructure.storage import shared_document_store
from app.runtime_defaults import default_runtime_settings
from app.worker.wiring import ingestion_service


def clients(factory: ModelFactory) -> dict[ModelRole, tuple[object, object]]:
    provider = factory.chat_models()
    # The chat and rewrite models sit behind the shared cache (CachedChatModel._inner).
    models: dict[ModelRole, Any] = {
        role: getattr(provider.for_role(role), "_inner", provider.for_role(role))
        for role in ModelRole
    }
    return {role: (m._client, m._streamer) for role, m in models.items()}


def test_a_settings_change_reuses_the_clients_of_unchanged_roles() -> None:
    settings = load_settings()
    before = clients(ModelFactory(settings))
    changed = settings.model_copy(update={"llm_grade_model": "vendor/another-grade-model"})

    after = clients(ModelFactory(changed))

    assert after[ModelRole.CHAT] == before[ModelRole.CHAT]
    assert after[ModelRole.GENERATE] == before[ModelRole.GENERATE]
    assert after[ModelRole.REWRITE] == before[ModelRole.REWRITE]
    assert after[ModelRole.GRADE] != before[ModelRole.GRADE]


def test_the_query_writing_roles_use_the_shared_cache() -> None:
    provider = ModelFactory(load_settings()).chat_models()

    cached = {role for role in ModelRole if isinstance(provider.for_role(role), CachedChatModel)}

    assert cached == {ModelRole.CHAT, ModelRole.REWRITE}


def test_the_embedder_is_reused_for_the_same_model() -> None:
    settings = load_settings()

    assert ModelFactory(settings).embedder() is ModelFactory(settings).embedder()


def test_the_document_store_is_built_once_per_settings() -> None:
    settings = load_settings()

    assert shared_document_store(settings) is shared_document_store(settings)


def test_closing_empties_the_client_cache() -> None:
    ModelFactory(load_settings()).chat_models()

    asyncio.run(close_model_clients())

    assert models._chat_clients == {}


def test_the_ingestion_service_uses_the_shared_store() -> None:
    settings = load_settings()
    service = ingestion_service(settings, cast(Any, None), default_runtime_settings(settings))

    assert service.store is shared_document_store(settings)
