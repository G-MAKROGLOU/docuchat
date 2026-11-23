"""The chat use case: conversations, and one graph run per question with a deadline."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from app.application import chat_prompts
from app.application.chat.graph import build_chat_graph
from app.application.chat.state import ChatLimits, ChatState, DetectorSource, Retriever
from app.domain.conversations import ConversationRepository, Turn
from app.domain.entities import Message, MessageRole
from app.domain.ports import ChatModelProvider, TurnTracer
from app.domain.runtime_settings import GraderMode

logger = logging.getLogger(__name__)


class ConversationNotFoundError(LookupError):
    pass


class ChatService:
    def __init__(  # noqa: PLR0913  # five ports plus the grader switch from the settings
        self,
        conversations: ConversationRepository,
        models: ChatModelProvider,
        detectors: DetectorSource,
        retriever: Retriever,
        tracer: TurnTracer,
        *,
        limits: ChatLimits,
        grader_mode: GraderMode = "llm",
    ) -> None:
        self._conversations = conversations
        self._limits = limits
        self._deadline = limits.turn_deadline_seconds
        self._tracer = tracer
        self._graph = build_chat_graph(models, detectors, retriever, limits, grader_mode)
        # Every trace records the prompt versions and the grader mode of its turn.
        self._run_metadata: dict[str, object] = {
            "prompts": dict(chat_prompts.PROMPT_VERSIONS),
            "grader": grader_mode,
        }

    async def start(self) -> UUID:
        return await self._conversations.create()

    async def end(self, conversation_id: UUID) -> None:
        """Delete the conversation. An unknown ID is not an error."""
        await self._conversations.delete(conversation_id)

    async def history(self, conversation_id: UUID) -> list[Turn]:
        if not await self._conversations.exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        return await self._conversations.turns(conversation_id)

    async def ask(self, conversation_id: UUID, question: str) -> AsyncGenerator[dict[str, Any]]:
        """Stream events; store the question, and the answer when its final event arrives."""
        if not await self._conversations.exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        history = [
            Message(t.role, t.text)
            for t in await self._conversations.turns(
                conversation_id, limit=self._limits.history_turns
            )
        ]
        await self._conversations.add_turn(conversation_id, MessageRole.USER, question)
        return self._run(conversation_id, {"question": question, "history": history})

    async def _run(self, conversation_id: UUID, state: ChatState) -> AsyncGenerator[dict[str, Any]]:
        trace = self._tracer.start_turn(conversation_id, state["question"])
        stored: tuple[str, dict[str, object]] | None = None
        ended = False
        try:
            # A stuck provider must not hold the stream and its connection open forever.
            async with asyncio.timeout(self._deadline):
                async for part in self._graph.astream(
                    state, config=dict(trace.run_config), stream_mode="custom", version="v2"
                ):
                    event: dict[str, Any] = part["data"]
                    if event["type"] in {"final", "refusal"}:
                        # Stored now: the suggestions that follow must not decide if it is kept.
                        stored = await self._store_answer(conversation_id, event)
                    yield event
        except TimeoutError:
            logger.warning(
                "chat turn past its deadline", extra={"conversation_id": str(conversation_id)}
            )
            trace.end(None, {"outcome": "timeout", **self._run_metadata}, failed=True)
            ended = True
            yield {"type": "error", "message": "The answer took too long. Please try again."}
            return
        except Exception:
            logger.exception("chat turn failed", extra={"conversation_id": str(conversation_id)})
            trace.end(None, {"outcome": "error", **self._run_metadata}, failed=True)
            ended = True
            yield {"type": "error", "message": "The answer failed. Please try again."}
            return
        finally:
            # The client can close the stream early; the trace still ends.
            if not ended:
                text, metadata = stored or (None, {"outcome": "incomplete"})
                trace.end(text, {**metadata, **self._run_metadata}, failed=False)

    async def _store_answer(
        self, conversation_id: UUID, event: dict[str, Any]
    ) -> tuple[str, dict[str, object]]:
        if event["type"] == "final":
            text, citations = event["answer"], event["citations"]
            metadata: dict[str, object] = {"outcome": "answer", "citations": citations}
        else:
            text, citations = chat_prompts.REFUSALS[event["reason"]], []
            metadata = {"outcome": "refusal", "reason": event["reason"]}
        await self._conversations.add_turn(conversation_id, MessageRole.ASSISTANT, text, citations)
        return text, metadata
