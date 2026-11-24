"""The runtime-settings defaults and loader that the API and the worker share."""

from app.application.runtime_settings import load_runtime_settings
from app.config import Settings
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.database import Connections
from app.infrastructure.runtime_settings_repository import PostgresRuntimeSettingsRepository


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


def with_models(settings: Settings, runtime: RuntimeSettings) -> Settings:
    """The settings with the models that the runtime settings select."""
    return settings.model_copy(
        update={
            "llm_chat_model": runtime.chat_model,
            "llm_rewrite_model": runtime.rewrite_model,
            "llm_grade_model": runtime.grade_model,
            "llm_generate_model": runtime.generate_model,
            "embedding_model": runtime.embedding_model,
        }
    )
