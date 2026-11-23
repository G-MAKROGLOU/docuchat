from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_embedding_choices,
    get_ingestion_control,
    get_known_models,
    get_runtime_config,
)
from app.api.schemas.settings import (
    SettingsOptions,
    SettingsResponse,
    SettingsSaved,
    SettingsUpdate,
)
from app.application.ingestion_control import IngestionControl
from app.application.runtime_settings import index_changed
from app.domain.runtime_settings import RuntimeSettings
from app.runtime_config import RuntimeConfig

router = APIRouter(tags=["settings"])

KnownModels = Callable[[], Awaitable[set[str] | None]]
EmbeddingChoices = Callable[[str], Awaitable[list[str]]]


@router.get("/settings")
async def read_settings(
    config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
) -> SettingsResponse:
    return SettingsResponse(**asdict(config.current))


@router.get("/settings/options")
async def read_options(
    config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
    known_models: Annotated[KnownModels, Depends(get_known_models)],
    embedding_choices: Annotated[EmbeddingChoices, Depends(get_embedding_choices)],
) -> SettingsOptions:
    chat = await known_models()
    embedding = await embedding_choices(config.current.embedding_model)
    return SettingsOptions(chat_models=sorted(chat or ()), embedding_models=embedding)


@router.put(
    "/settings",
    responses={
        422: {"description": "A value is invalid, or OpenRouter does not list a model ID."},
        409: {"description": "A chunk change needs confirmation, or a pass is running."},
    },
)
async def update_settings(
    body: SettingsUpdate,
    config: Annotated[RuntimeConfig, Depends(get_runtime_config)],
    control: Annotated[IngestionControl, Depends(get_ingestion_control)],
    known_models: Annotated[KnownModels, Depends(get_known_models)],
    embedding_choices: Annotated[EmbeddingChoices, Depends(get_embedding_choices)],
) -> SettingsSaved:
    values = body.model_dump(exclude={"reingest_confirmed"})
    values["embedding_model"] = body.embedding_model or config.current.embedding_model
    new = RuntimeSettings(**values)
    await _check_models(config.current, new, known_models, embedding_choices)
    reindex = index_changed(config.current, new)
    if reindex and not body.reingest_confirmed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A chunk or embedding change embeds every document again: confirm it.",
        )
    if reindex and (await control.status()).running:
        raise HTTPException(status.HTTP_409_CONFLICT, "An ingestion pass is running.")
    started = await config.apply(new, reingest=reindex)
    return SettingsSaved(**asdict(new), reingest_started=started)


async def _check_models(
    old: RuntimeSettings,
    new: RuntimeSettings,
    known_models: KnownModels,
    embedding_choices: EmbeddingChoices,
) -> None:
    """Refuse a chat model ID that OpenRouter does not list, and an embedding model that the page
    does not offer. A chat list that is not available does not block the save."""
    if new.embedding_model != old.embedding_model:
        offered = await embedding_choices(old.embedding_model)
        if new.embedding_model not in offered:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"The embedding model {new.embedding_model} is not offered.",
            )
    names = {new.chat_model, new.rewrite_model, new.grade_model, new.generate_model}
    changed = names - {old.chat_model, old.rewrite_model, old.grade_model, old.generate_model}
    if not changed:
        return
    known = await known_models()
    unknown = sorted(changed - known) if known is not None else []
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"OpenRouter does not list: {', '.join(unknown)}"
        )
