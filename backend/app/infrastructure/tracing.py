"""Tracer adapters."""

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from app.config import Settings
from app.domain.ports import TurnTrace

TURN_NAME = "chat-turn"

logger = logging.getLogger(__name__)


class NoopTurn:
    run_config: Mapping[str, object] = {}

    def end(self, output: str | None, metadata: Mapping[str, object], *, failed: bool) -> None:
        return None


class NoopTracer:
    """Used when Langfuse settings are absent."""

    def start_turn(self, conversation_id: UUID, question: str) -> TurnTrace:
        return NoopTurn()

    def shutdown(self) -> None:
        return None


def _log_sdk_error(operation: str, exc: Exception) -> None:
    logger.warning("tracing failed", extra={"operation": operation, "error": type(exc).__name__})


class _LangfuseTurn:
    """A root observation for the turn; the graph run nests under it through the handler."""

    def __init__(self, root: Any, session_id: str) -> None:
        self._root = root
        handler = CallbackHandler(
            trace_context={"trace_id": root.trace_id, "parent_span_id": root.id}
        )
        self.run_config: Mapping[str, object] = {
            "callbacks": [handler],
            "metadata": {"langfuse_session_id": session_id},
        }

    def end(self, output: str | None, metadata: Mapping[str, object], *, failed: bool) -> None:
        try:
            if failed:
                self._root.update(output=output, metadata=dict(metadata), level="ERROR")
            else:
                self._root.update(output=output, metadata=dict(metadata))
            self._root.end()
        except Exception as exc:
            _log_sdk_error("end", exc)


class LangfuseTracer:
    def __init__(self, client: Langfuse) -> None:
        self._client = client

    def start_turn(self, conversation_id: UUID, question: str) -> TurnTrace:
        """One trace per turn, grouped into a session per conversation."""
        session_id = str(conversation_id)
        try:
            with propagate_attributes(session_id=session_id, trace_name=TURN_NAME):
                root = self._client.start_observation(
                    name=TURN_NAME, as_type="agent", input=question
                )
            return _LangfuseTurn(root, session_id)
        except Exception as exc:
            _log_sdk_error("start", exc)
            return NoopTurn()

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
