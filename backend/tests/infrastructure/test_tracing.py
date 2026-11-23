import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from langfuse import Langfuse

from app import main
from app.config import load_settings
from app.infrastructure import tracing
from app.infrastructure.tracing import LangfuseTracer, NoopTracer, NoopTurn, build_tracer

LANGFUSE_ENV = {
    "LANGFUSE_PUBLIC_KEY": "pk-test",
    "LANGFUSE_SECRET_KEY": "sk-test",
    "LANGFUSE_HOST": "http://langfuse.test",
}


class FakeObservation:
    def __init__(self, fail_on_update: bool) -> None:
        self.fail_on_update = fail_on_update
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> "FakeObservation":
        if self.fail_on_update:
            raise RuntimeError("sdk update failed")
        self.updates.append(kwargs)
        return self


class FakeRoot:
    trace_id = "t1"
    id = "r1"

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.ended = 0

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.ended += 1


class FakeHandler:
    def __init__(self, trace_context: dict[str, str]) -> None:
        self.trace_context = trace_context


class FakeLangfuse:
    def __init__(
        self,
        fail_on_start: bool = False,
        fail_on_exit: bool = False,
        fail_on_update: bool = False,
        fail_on_shutdown: bool = False,
    ) -> None:
        self.fail_on_start = fail_on_start
        self.fail_on_exit = fail_on_exit
        self.fail_on_shutdown = fail_on_shutdown
        self.observation = FakeObservation(fail_on_update)
        self.root = FakeRoot()
        self.started: list[dict[str, Any]] = []
        self.exits = 0
        self.shutdowns = 0

    @contextmanager
    def _observation(self) -> Iterator[FakeObservation]:
        try:
            yield self.observation
        finally:
            self.exits += 1
            if self.fail_on_exit:
                raise RuntimeError("sdk exit failed")

    def start_observation(self, **kwargs: Any) -> "FakeRoot":
        if self.fail_on_start:
            raise RuntimeError("sdk start failed")
        self.started.append(kwargs)
        return self.root

    def start_as_current_observation(self, **kwargs: Any) -> Any:
        if self.fail_on_start:
            raise RuntimeError("sdk start failed")
        self.started.append(kwargs)
        return self._observation()

    def shutdown(self) -> None:
        self.shutdowns += 1
        if self.fail_on_shutdown:
            raise RuntimeError("sdk shutdown failed")


def tracer_with(fake: FakeLangfuse) -> LangfuseTracer:
    return LangfuseTracer(cast(Langfuse, fake))


def test_no_keys_gives_noop_tracer() -> None:
    assert isinstance(build_tracer(load_settings()), NoopTracer)


def test_partial_keys_give_noop_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    assert isinstance(build_tracer(load_settings()), NoopTracer)


def test_keys_give_langfuse_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in LANGFUSE_ENV.items():
        monkeypatch.setenv(key, value)
    calls: list[dict[str, Any]] = []

    def fake_client(**kwargs: Any) -> FakeLangfuse:
        calls.append(kwargs)
        return FakeLangfuse()

    monkeypatch.setattr(tracing, "Langfuse", fake_client)

    assert isinstance(build_tracer(load_settings()), LangfuseTracer)
    assert calls == [
        {"public_key": "pk-test", "secret_key": "sk-test", "base_url": "http://langfuse.test"}
    ]


def test_client_construction_error_gives_noop_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in LANGFUSE_ENV.items():
        monkeypatch.setenv(key, value)

    def failing_client(**kwargs: Any) -> FakeLangfuse:
        raise RuntimeError("sdk init failed")

    monkeypatch.setattr(tracing, "Langfuse", failing_client)

    assert isinstance(build_tracer(load_settings()), NoopTracer)


def test_attributes_reach_the_sdk() -> None:
    fake = FakeLangfuse()

    with tracer_with(fake).span("retrieve-context", {"top_k": 5}) as span:
        span.set_attributes({"hits": 3})

    assert fake.started == [
        {"as_type": "span", "name": "retrieve-context", "metadata": {"top_k": 5}}
    ]
    assert fake.observation.updates == [{"metadata": {"hits": 3}}]
    assert fake.exits == 1


def test_sdk_error_on_start_does_not_raise() -> None:
    ran = False

    with tracer_with(FakeLangfuse(fail_on_start=True)).span("retrieve-context") as span:
        span.set_attributes({"hits": 3})
        ran = True

    assert ran


def test_sdk_errors_on_update_and_exit_do_not_raise() -> None:
    fake = FakeLangfuse(fail_on_exit=True, fail_on_update=True)

    with tracer_with(fake).span("retrieve-context") as span:
        span.set_attributes({"hits": 3})

    assert fake.exits == 1


def test_application_error_propagates_and_closes_the_span() -> None:
    fake = FakeLangfuse()

    with (
        pytest.raises(ValueError, match="app failed"),
        tracer_with(fake).span("retrieve-context"),
    ):
        raise ValueError("app failed")

    assert fake.exits == 1


class NoSavedSettings:
    def __init__(self, connections: object) -> None:
        pass

    async def load(self) -> dict[str, object]:
        return {}


def test_app_shutdown_flushes_the_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLangfuse()
    monkeypatch.setattr(main, "build_tracer", lambda settings: tracer_with(fake))
    # Only the tracer is under test: skip the database and storage startup steps.
    monkeypatch.setattr(main, "apply_migrations", lambda conninfo: [])
    monkeypatch.setattr(main, "check_vector_size", lambda conninfo, size: None)
    monkeypatch.setattr(main, "build_document_store", lambda settings: None)
    monkeypatch.setattr(main, "PostgresRuntimeSettingsRepository", NoSavedSettings)

    with TestClient(main.create_app(load_settings())):
        assert fake.shutdowns == 0

    assert fake.shutdowns == 1


def test_shutdown_error_does_not_raise() -> None:
    fake = FakeLangfuse(fail_on_shutdown=True)

    tracer_with(fake).shutdown()

    assert fake.shutdowns == 1


def test_the_app_starts_again_after_a_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "apply_migrations", lambda conninfo: [])
    monkeypatch.setattr(main, "check_vector_size", lambda conninfo, size: None)
    monkeypatch.setattr(main, "build_document_store", lambda settings: None)
    monkeypatch.setattr(main, "PostgresRuntimeSettingsRepository", NoSavedSettings)
    app = main.create_app(load_settings())

    for _ in range(2):
        with TestClient(app):
            pass


def test_a_failed_start_keeps_no_pool_from_an_earlier_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "apply_migrations", lambda conninfo: [])
    monkeypatch.setattr(main, "check_vector_size", lambda conninfo, size: None)
    monkeypatch.setattr(main, "build_document_store", lambda settings: None)
    monkeypatch.setattr(main, "PostgresRuntimeSettingsRepository", NoSavedSettings)
    app = main.create_app(load_settings())
    with TestClient(app):
        pass

    def fail(conninfo: str) -> list[str]:
        raise RuntimeError("database down")

    monkeypatch.setattr(main, "apply_migrations", fail)
    with pytest.raises(RuntimeError, match="database down"), TestClient(app):
        pass

    assert app.state.pool is None
    assert app.state.document_repository is None


def test_a_turn_is_a_root_observation_with_the_graph_run_under_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tracing, "CallbackHandler", FakeHandler)
    fake = FakeLangfuse()
    conversation_id = uuid.uuid4()

    turn = tracer_with(fake).start_turn(conversation_id, "What is the dose?")
    turn.end("10 mg [S1].", {"outcome": "answer"}, failed=False)

    assert fake.started == [{"name": "chat-turn", "as_type": "agent", "input": "What is the dose?"}]
    [handler] = cast(list[FakeHandler], turn.run_config["callbacks"])
    assert handler.trace_context == {"trace_id": "t1", "parent_span_id": "r1"}
    assert turn.run_config["metadata"] == {"langfuse_session_id": str(conversation_id)}
    assert fake.root.updates == [{"output": "10 mg [S1].", "metadata": {"outcome": "answer"}}]
    assert fake.root.ended == 1


def test_a_failed_turn_is_marked_as_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "CallbackHandler", FakeHandler)
    fake = FakeLangfuse()

    tracer_with(fake).start_turn(uuid.uuid4(), "q").end(None, {"outcome": "error"}, failed=True)

    assert fake.root.updates == [
        {"output": None, "metadata": {"outcome": "error"}, "level": "ERROR"}
    ]


def test_an_sdk_error_at_turn_start_gives_an_untraced_turn() -> None:
    turn = tracer_with(FakeLangfuse(fail_on_start=True)).start_turn(uuid.uuid4(), "q")

    assert isinstance(turn, NoopTurn)
    assert turn.run_config == {}
