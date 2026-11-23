import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, cast

import pytest

from app.application.settings_service import SettingsService
from app.domain.runtime_settings import (
    InvalidSettingsError,
    RuntimeSettings,
    SettingsConflictError,
)
from tests.support.factories import RUNTIME_DEFAULTS
from tests.support.fakes_ingestion import StubIngestionControl


class FakeConfig:
    def __init__(self) -> None:
        self.current = RUNTIME_DEFAULTS
        self.applied: list[tuple[RuntimeSettings, bool]] = []

    async def apply(self, new: RuntimeSettings, *, reingest: bool) -> bool:
        self.applied.append((new, reingest))
        self.current = new
        return reingest


def returning(value: object) -> Callable[..., Awaitable[Any]]:
    async def lookup(*_: object) -> Any:
        return value

    return lookup


def service(
    config: FakeConfig, *, running: bool = False, known: set[str] | None = None
) -> SettingsService:
    return SettingsService(
        config,
        cast(Any, StubIngestionControl(running=running)),
        returning(known),
        returning([RUNTIME_DEFAULTS.embedding_model, "x/other"]),
    )


def test_a_plain_change_is_saved_without_a_pass() -> None:
    config = FakeConfig()
    new = replace(RUNTIME_DEFAULTS, top_k=30)

    started = asyncio.run(service(config).update(new, confirmed=False))

    assert not started
    assert config.applied == [(new, False)]


def test_a_chunk_change_needs_confirmation_and_no_running_pass() -> None:
    config = FakeConfig()
    new = replace(RUNTIME_DEFAULTS, chunk_tokens=400)

    with pytest.raises(SettingsConflictError, match="confirm"):
        asyncio.run(service(config).update(new, confirmed=False))
    with pytest.raises(SettingsConflictError, match="running"):
        asyncio.run(service(config, running=True).update(new, confirmed=True))
    assert asyncio.run(service(config).update(new, confirmed=True))
    assert config.applied == [(new, True)]


def test_an_unlisted_model_or_embedding_is_invalid() -> None:
    config = FakeConfig()
    typo = replace(RUNTIME_DEFAULTS, grade_model="a/typo")
    unknown_embedding = replace(RUNTIME_DEFAULTS, embedding_model="y/none")

    with pytest.raises(InvalidSettingsError, match="a/typo"):
        asyncio.run(service(config, known={"a/chat"}).update(typo, confirmed=False))
    with pytest.raises(InvalidSettingsError, match="y/none"):
        asyncio.run(service(config).update(unknown_embedding, confirmed=True))
    assert config.applied == []
