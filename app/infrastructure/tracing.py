"""Tracer adapters."""

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager

from app.domain.ports import Span


class NoopSpan:
    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        return None


class NoopTracer:
    """Used when Langfuse settings are absent."""

    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> AbstractContextManager[Span]:
        return _noop_span()


@contextmanager
def _noop_span() -> Iterator[Span]:
    yield NoopSpan()
