"""Tracer adapters."""

import logging
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any

from langfuse import Langfuse

from app.config import Settings
from app.domain.ports import Span

logger = logging.getLogger(__name__)


class NoopSpan:
    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        return None


class NoopTracer:
    """Used when Langfuse settings are absent."""

    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> AbstractContextManager[Span]:
        return _noop_span()

    def shutdown(self) -> None:
        return None


@contextmanager
def _noop_span() -> Iterator[Span]:
    yield NoopSpan()


def _log_sdk_error(operation: str, exc: Exception) -> None:
    logger.warning("tracing failed", extra={"operation": operation, "error": type(exc).__name__})


class _LangfuseSpan:
    def __init__(self, observation: Any) -> None:
        self._observation = observation

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        try:
            self._observation.update(metadata=dict(attributes))
        except Exception as exc:
            _log_sdk_error("update", exc)


class _GuardedObservation(AbstractContextManager[Span]):
    """Opens a Langfuse observation. SDK errors are logged; application errors propagate."""

    def __init__(self, client: Langfuse, name: str, attributes: Mapping[str, object]) -> None:
        self._client = client
        self._name = name
        self._attributes = attributes
        self._context: AbstractContextManager[Any] | None = None

    def __enter__(self) -> Span:
        try:
            context = self._client.start_as_current_observation(
                as_type="span", name=self._name, metadata=dict(self._attributes)
            )
            observation = context.__enter__()
        except Exception as exc:
            _log_sdk_error("start", exc)
            return NoopSpan()
        self._context = context
        return _LangfuseSpan(observation)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._context is None:
            return
        try:
            self._context.__exit__(exc_type, exc, tb)
        except Exception as sdk_exc:
            _log_sdk_error("end", sdk_exc)


class LangfuseTracer:
    def __init__(self, client: Langfuse) -> None:
        self._client = client

    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> AbstractContextManager[Span]:
        return _GuardedObservation(self._client, name, attributes or {})

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception as exc:
            _log_sdk_error("shutdown", exc)


def build_tracer(settings: Settings) -> LangfuseTracer | NoopTracer:
    """Returns a Langfuse tracer only when the key pair and the host are all set."""
    public_key, secret_key, host = (
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_host,
    )
    if public_key is None or secret_key is None or host is None:
        return NoopTracer()
    try:
        client = Langfuse(
            public_key=public_key.get_secret_value(),
            secret_key=secret_key.get_secret_value(),
            base_url=host,
        )
    except Exception as exc:
        _log_sdk_error("init", exc)
        return NoopTracer()
    return LangfuseTracer(client)
