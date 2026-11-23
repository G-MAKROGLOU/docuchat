"""The settings use case: check a change of the runtime settings, then save and use it."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.application.ingestion_control import IngestionStatus
from app.application.runtime_settings import index_changed
from app.domain.runtime_settings import (
    InvalidSettingsError,
    RuntimeSettings,
    SettingsConflictError,
)

KnownModels = Callable[[], Awaitable[set[str] | None]]
EmbeddingChoices = Callable[[str], Awaitable[list[str]]]


class LiveSettings(Protocol):
    @property
    def current(self) -> RuntimeSettings: ...

    async def apply(self, new: RuntimeSettings, *, reingest: bool) -> bool: ...


class PassStatus(Protocol):
    async def status(self) -> IngestionStatus: ...


class SettingsService:
    def __init__(
        self,
        config: LiveSettings,
        control: PassStatus,
        known_models: KnownModels,
        embedding_choices: EmbeddingChoices,
    ) -> None:
        self._config = config
        self._control = control
        self._known_models = known_models
        self._embedding_choices = embedding_choices

    @property
    def current(self) -> RuntimeSettings:
        return self._config.current

    async def update(self, new: RuntimeSettings, *, confirmed: bool) -> bool:
        """Saves the settings; True when a pass to embed every document again started."""
        await self._check_models(self._config.current, new)
        reindex = index_changed(self._config.current, new)
        if reindex and not confirmed:
            raise SettingsConflictError(
                "A chunk or embedding change embeds every document again: confirm it."
            )
        if reindex and (await self._control.status()).running:
            raise SettingsConflictError("An ingestion pass is running.")
        return await self._config.apply(new, reingest=reindex)

    async def _check_models(self, old: RuntimeSettings, new: RuntimeSettings) -> None:
        """Refuse a chat model ID that OpenRouter does not list, and an embedding model that the
        page does not offer. A chat list that is not available does not block the save."""
        if new.embedding_model != old.embedding_model:
            offered = await self._embedding_choices(old.embedding_model)
            if new.embedding_model not in offered:
                raise InvalidSettingsError(
                    f"The embedding model {new.embedding_model} is not offered."
                )
        names = {new.chat_model, new.rewrite_model, new.grade_model, new.generate_model}
        changed = names - {old.chat_model, old.rewrite_model, old.grade_model, old.generate_model}
        if not changed:
            return
        known = await self._known_models()
        unknown = sorted(changed - known) if known is not None else []
        if unknown:
            raise InvalidSettingsError(f"OpenRouter does not list: {', '.join(unknown)}")
