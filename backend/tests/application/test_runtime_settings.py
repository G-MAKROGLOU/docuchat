import asyncio
import os
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_embedding_choices,
    get_ingestion_control,
    get_known_models,
    get_runtime_config,
)
from app.application.corpus_update import UpdateReport
from app.application.ingestion_runner import IngestionRunner
from app.application.label_queue import QueueReport
from app.application.runtime_settings import index_changed, load_runtime_settings
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.migrations import apply_migrations
from app.infrastructure.runtime_settings_repository import PostgresRuntimeSettingsRepository
from app.main import app
from app.runtime_config import EMBEDDED_KEY, RuntimeConfig
from tests.support.db import DirectConnections
from tests.support.factories import RUNTIME_DEFAULTS
from tests.support.fakes_ingestion import (
    FakeRuntimeSettingsRepository,
    FakeTracker,
    ListedDocuments,
    StubIngestionControl,
)
from tests.support.fakes_ports import Clock
from tests.support.tuning import SETTINGS


def returning(value: object) -> Callable[..., Awaitable[Any]]:
    """An async lookup that gives a fixed value (the model list and choice overrides)."""

    async def lookup(*_: object) -> Any:
        return value

    return lookup


def test_saved_values_replace_the_defaults_and_unknown_keys_are_ignored() -> None:
    repository = FakeRuntimeSettingsRepository({"top_k": 30, "grader_mode": "rule", "old_key": 1})

    loaded = asyncio.run(load_runtime_settings(RUNTIME_DEFAULTS, repository))

    assert loaded == replace(RUNTIME_DEFAULTS, top_k=30, grader_mode="rule")


def test_nothing_saved_gives_the_defaults() -> None:
    assert (
        asyncio.run(load_runtime_settings(RUNTIME_DEFAULTS, FakeRuntimeSettingsRepository()))
        == RUNTIME_DEFAULTS
    )


def test_only_the_index_fields_count_as_a_re_embedding_change() -> None:
    assert not index_changed(
        RUNTIME_DEFAULTS, replace(RUNTIME_DEFAULTS, top_k=30, chat_model="b/chat")
    )
    assert index_changed(RUNTIME_DEFAULTS, replace(RUNTIME_DEFAULTS, chunk_tokens=400))
    assert index_changed(RUNTIME_DEFAULTS, replace(RUNTIME_DEFAULTS, overlap_tokens=0))
    assert index_changed(RUNTIME_DEFAULTS, replace(RUNTIME_DEFAULTS, embedding_model="x/other"))


class FakeConfig:
    def __init__(self) -> None:
        self.current = RUNTIME_DEFAULTS
        self.applied: list[tuple[RuntimeSettings, bool]] = []

    async def apply(self, new: RuntimeSettings, *, reingest: bool) -> bool:
        self.applied.append((new, reingest))
        self.current = new
        return reingest


@pytest.fixture
def config() -> FakeConfig:
    return FakeConfig()


def make_client(config: FakeConfig, control: StubIngestionControl) -> Iterator[TestClient]:
    app.dependency_overrides[get_runtime_config] = lambda: config
    app.dependency_overrides[get_ingestion_control] = lambda: control
    app.dependency_overrides[get_embedding_choices] = lambda: returning(["m/embed", "x/other"])
    app.state.settings = SimpleNamespace(embedding_model="m/embed")
    yield TestClient(app)


@pytest.fixture
def client(config: FakeConfig) -> Iterator[TestClient]:
    yield from make_client(config, StubIngestionControl())


def test_get_returns_the_settings_and_the_embedding_model(client: TestClient) -> None:
    body = client.get("/api/v1/settings").json()

    assert body == asdict(RUNTIME_DEFAULTS)


def test_a_change_without_chunk_fields_is_saved_and_starts_no_pass(
    client: TestClient, config: FakeConfig
) -> None:
    response = client.put("/api/v1/settings", json={**asdict(RUNTIME_DEFAULTS), "top_k": 30})

    assert response.status_code == 200
    assert response.json()["reingest_started"] is False
    assert config.applied == [(replace(RUNTIME_DEFAULTS, top_k=30), False)]


def test_a_chunk_change_needs_confirmation(client: TestClient, config: FakeConfig) -> None:
    body = {**asdict(RUNTIME_DEFAULTS), "chunk_tokens": 400}

    refused = client.put("/api/v1/settings", json=body)
    confirmed = client.put("/api/v1/settings", json={**body, "reingest_confirmed": True})

    assert refused.status_code == 409
    assert confirmed.status_code == 200
    assert confirmed.json()["reingest_started"] is True
    assert config.applied == [(replace(RUNTIME_DEFAULTS, chunk_tokens=400), True)]


def test_a_chunk_change_is_refused_while_a_pass_runs(config: FakeConfig) -> None:
    client = next(make_client(config, StubIngestionControl(running=True)))
    body = {**asdict(RUNTIME_DEFAULTS), "chunk_tokens": 400, "reingest_confirmed": True}

    assert client.put("/api/v1/settings", json=body).status_code == 409
    assert config.applied == []


@pytest.mark.parametrize(
    "change",
    [
        {"overlap_tokens": 500, "chunk_tokens": 400},
        {"top_k": 0},
        {"chat_model": "bad model name"},
        {"grader_mode": "always"},
    ],
)
def test_invalid_values_are_refused(client: TestClient, change: dict[str, Any]) -> None:
    assert (
        client.put("/api/v1/settings", json={**asdict(RUNTIME_DEFAULTS), **change}).status_code
        == 422
    )


class RecordingService:
    def __init__(self) -> None:
        self.forced: list[bool] = []

    async def ingest(self, document: Any, *, force: bool = False) -> None:
        self.forced.append(force)


def test_a_forced_pass_embeds_each_document_again_with_the_new_service() -> None:
    async def no_queue() -> QueueReport:
        return QueueReport()

    async def no_updates() -> UpdateReport:
        return UpdateReport()

    tracker = FakeTracker(stale=False)

    async def scenario() -> tuple[list[bool], list[bool]]:
        old, new = RecordingService(), RecordingService()
        runner = IngestionRunner(
            cast(Any, old),
            cast(Any, ListedDocuments("a")),
            no_updates,
            no_queue,
            tracker,
            concurrency=SETTINGS.ingest_concurrency,
        )
        runner.use_service(cast(Any, new))
        runner.start(force=True)
        await runner._task  # type: ignore[misc]
        return old.forced, new.forced

    old_forced, new_forced = asyncio.run(scenario())

    assert old_forced == []
    assert new_forced == [True]


@pytest.mark.db
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
def test_the_repository_saves_and_replaces_values() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    repository = PostgresRuntimeSettingsRepository(DirectConnections(conninfo))

    async def scenario() -> None:
        try:
            await repository.save({"test_a": 1, "test_b": "x"})
            await repository.save({"test_a": 2})
            saved = await repository.load()
            assert saved["test_a"] == 2
            assert "test_b" not in saved
        finally:
            async with DirectConnections(conninfo).connection() as conn:
                await conn.execute(r"DELETE FROM runtime_settings WHERE key LIKE 'test\_%'")

    asyncio.run(scenario())


def test_an_unknown_model_id_is_refused(client: TestClient) -> None:
    app.dependency_overrides[get_known_models] = lambda: returning({"a/chat", "a/rewrite"})
    body = {**asdict(RUNTIME_DEFAULTS), "grade_model": "a/typo"}

    response = client.put("/api/v1/settings", json=body)

    assert response.status_code == 422
    assert "a/typo" in response.json()["detail"]


def test_a_model_list_that_is_not_available_does_not_block_the_save(
    client: TestClient, config: FakeConfig
) -> None:
    app.dependency_overrides[get_known_models] = lambda: returning(None)

    response = client.put(
        "/api/v1/settings", json={**asdict(RUNTIME_DEFAULTS), "grade_model": "a/new"}
    )

    assert response.status_code == 200
    assert config.applied[0][0].grade_model == "a/new"


class Services:
    """Records what the config built and when the build went live."""

    def __init__(self, *, fail: bool = False) -> None:
        self.live: RuntimeSettings | None = None
        self.builds = 0
        self._fail = fail

    async def rebuild(self, settings: RuntimeSettings) -> Callable[[], None]:
        self.builds += 1
        if self._fail:
            raise RuntimeError("build failed")

        def commit() -> None:
            self.live = settings

        return commit


class Requests:
    def __init__(self, *, accepted: bool = True) -> None:
        self.count = 0
        self._accepted = accepted

    async def __call__(self) -> bool:
        self.count += 1
        return self._accepted


def make_config(
    repository: FakeRuntimeSettingsRepository,
    services: Services,
    requests: Requests | None = None,
    clock: Clock | None = None,
) -> RuntimeConfig:
    config = RuntimeConfig(
        repository,
        RUNTIME_DEFAULTS,
        services.rebuild,
        request_pass=requests,
        clock=clock or Clock(),
        refresh_seconds=SETTINGS.runtime_refresh_seconds,
    )
    asyncio.run(config.load())
    return config


def test_load_uses_the_saved_values_and_builds_the_services() -> None:
    services = Services()
    config = make_config(FakeRuntimeSettingsRepository({"top_k": 30}), services)

    assert config.current == replace(RUNTIME_DEFAULTS, top_k=30)
    assert services.live == replace(RUNTIME_DEFAULTS, top_k=30)


def test_apply_saves_only_changed_fields_and_swaps_the_services() -> None:
    repository, services, requests = FakeRuntimeSettingsRepository(), Services(), Requests()
    config = make_config(repository, services, requests)
    new = replace(RUNTIME_DEFAULTS, top_k=30)

    started = asyncio.run(config.apply(new, reingest=False))

    assert started is False
    assert repository.saved == {"top_k": 30}
    assert config.current == new
    assert services.live == new
    assert requests.count == 0


def test_a_failed_build_keeps_the_saved_and_the_running_settings() -> None:
    repository = FakeRuntimeSettingsRepository()
    config = make_config(repository, Services())
    config._rebuild = Services(fail=True).rebuild

    with pytest.raises(RuntimeError):
        asyncio.run(config.apply(replace(RUNTIME_DEFAULTS, top_k=30), reingest=False))

    assert repository.saved == {}
    assert config.current == RUNTIME_DEFAULTS


def test_apply_with_a_chunk_change_records_the_old_chunking_and_asks_for_a_pass() -> None:
    repository, requests = FakeRuntimeSettingsRepository(), Requests()
    config = make_config(repository, Services(), requests)

    started = asyncio.run(config.apply(replace(RUNTIME_DEFAULTS, chunk_tokens=250), reingest=True))

    assert started is True
    assert requests.count == 1
    assert repository.saved == {
        "chunk_tokens": 250,
        EMBEDDED_KEY: {"chunk_tokens": 500, "overlap_tokens": 50, "embedding_model": "m/embed"},
    }
    assert asyncio.run(config.stale()) is True


def test_a_finished_embedding_clears_the_stale_marker() -> None:
    repository = FakeRuntimeSettingsRepository()
    config = make_config(repository, Services(), Requests(accepted=False))
    asyncio.run(config.apply(replace(RUNTIME_DEFAULTS, chunk_tokens=250), reingest=True))

    asyncio.run(config.mark_embedded())

    assert asyncio.run(config.stale()) is False
    assert repository.saved[EMBEDDED_KEY] == {
        "chunk_tokens": 250,
        "overlap_tokens": 50,
        "embedding_model": "m/embed",
    }


def test_nothing_embedded_yet_is_not_stale() -> None:
    config = make_config(FakeRuntimeSettingsRepository(), Services())

    assert asyncio.run(config.stale()) is False


def test_refresh_picks_up_a_save_from_another_process() -> None:
    repository, services, clock = FakeRuntimeSettingsRepository(), Services(), Clock()
    config = make_config(repository, services, clock=clock)
    repository.saved = {"top_k": 30}
    clock.now = 5.0

    assert asyncio.run(config.refresh()) is True
    assert config.current == replace(RUNTIME_DEFAULTS, top_k=30)
    assert services.live == replace(RUNTIME_DEFAULTS, top_k=30)


def test_refresh_checks_at_most_once_per_interval() -> None:
    repository, clock = FakeRuntimeSettingsRepository(), Clock()
    config = make_config(repository, Services(), clock=clock)
    repository.saved = {"top_k": 30}
    clock.now = 0.5

    assert asyncio.run(config.refresh()) is False
    assert config.current == RUNTIME_DEFAULTS


def test_refresh_does_not_rebuild_for_a_marker_change_only() -> None:
    repository, services, clock = FakeRuntimeSettingsRepository(), Services(), Clock()
    config = make_config(repository, services, clock=clock)
    repository.saved = {EMBEDDED_KEY: {"chunk_tokens": 500}}
    clock.now = 5.0

    assert asyncio.run(config.refresh()) is False
    assert services.builds == 1


def test_a_pass_that_finds_stale_chunks_embeds_everything_and_marks_it_done() -> None:
    async def no_queue() -> QueueReport:
        return QueueReport()

    async def no_updates() -> UpdateReport:
        return UpdateReport()

    async def scenario() -> tuple[list[bool], int]:
        service, tracker = RecordingService(), FakeTracker(stale=True)
        runner = IngestionRunner(
            cast(Any, service),
            cast(Any, ListedDocuments("a")),
            no_updates,
            no_queue,
            tracker,
            concurrency=SETTINGS.ingest_concurrency,
        )
        runner.start()
        await runner._task  # type: ignore[misc]
        return service.forced, tracker.marked

    forced, marked = asyncio.run(scenario())

    assert forced == [True]
    assert marked == 1


def test_the_options_list_the_chat_models_and_the_embedding_choices(client: TestClient) -> None:
    app.dependency_overrides[get_known_models] = lambda: returning({"b/two", "a/one"})

    body = client.get("/api/v1/settings/options").json()

    assert body == {"chat_models": ["a/one", "b/two"], "embedding_models": ["m/embed", "x/other"]}


def test_an_embedding_change_needs_confirmation_and_a_known_choice(
    client: TestClient, config: FakeConfig
) -> None:
    body = {**asdict(RUNTIME_DEFAULTS), "embedding_model": "x/other"}

    refused = client.put("/api/v1/settings", json=body)
    unknown = client.put(
        "/api/v1/settings", json={**body, "embedding_model": "y/none", "reingest_confirmed": True}
    )
    confirmed = client.put("/api/v1/settings", json={**body, "reingest_confirmed": True})

    assert refused.status_code == 409
    assert unknown.status_code == 422
    assert confirmed.status_code == 200
    assert confirmed.json()["reingest_started"] is True
    assert config.applied == [(replace(RUNTIME_DEFAULTS, embedding_model="x/other"), True)]


def test_a_save_without_an_embedding_model_keeps_the_current_one(
    client: TestClient, config: FakeConfig
) -> None:
    body = {k: v for k, v in asdict(RUNTIME_DEFAULTS).items() if k != "embedding_model"}

    response = client.put("/api/v1/settings", json={**body, "top_k": 25})

    assert response.status_code == 200
    assert config.applied[0][0].embedding_model == "m/embed"
