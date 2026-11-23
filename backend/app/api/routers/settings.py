from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_embedding_choices,
    get_known_models,
    get_runtime_config,
    get_settings_service,
)
from app.api.schemas.settings import (
    SettingsOptions,
    SettingsResponse,
    SettingsSaved,
    SettingsUpdate,
)
from app.application.settings_service import EmbeddingChoices, KnownModels, SettingsService
from app.domain.runtime_settings import (
    InvalidSettingsError,
    RuntimeSettings,
    SettingsConflictError,
)
from app.runtime_config import RuntimeConfig

router = APIRouter(tags=["settings"])


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
    service: Annotated[SettingsService, Depends(get_settings_service)],
) -> SettingsSaved:
    values = body.model_dump(exclude={"reingest_confirmed"})
    values["embedding_model"] = body.embedding_model or service.current.embedding_model
    new = RuntimeSettings(**values)
    try:
        started = await service.update(new, confirmed=body.reingest_confirmed)
    except InvalidSettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except SettingsConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SettingsSaved(**asdict(new), reingest_started=started)
