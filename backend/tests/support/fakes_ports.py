"""Fakes for the chat ports: detector, retriever, conversations and tracer."""

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from app.application.chat import ChatService, GraderMode
from app.application.drug_detection import DrugDetection
from app.application.fusion import FusedChunk
from app.application.retrieval import RetrievalResult, SearchMode
from app.domain.conversations import Turn
from app.domain.entities import Chunk, MessageRole
from tests.support.factories import label_of
from tests.support.fakes_models import FakeModels

LIPITOR = DrugDetection(drugs=("Lipitor",), labels=(label_of("Lipitor"),))


class FakeDetector:
    def __init__(self, detection: DrugDetection) -> None:
        self._detection = detection

    def detect(self, question: str) -> DrugDetection:
        return self._detection

    def catalog(self) -> list[str]:
        return ["Lipitor (atorvastatin)", "Valium (diazepam)"]

    async def source(self) -> "FakeDetector":
        return self


class FakeRetriever:
    def __init__(self, *chunks: Chunk) -> None:
        self._chunks = chunks
        self.queries: list[tuple[str, tuple[uuid.UUID, ...]]] = []
        self.hints: list[tuple[str, ...]] = []

    async def retrieve(
        self, query: str, *, labels: Sequence[uuid.UUID] = (), section_hints: Sequence[str] = ()
    ) -> RetrievalResult:
        self.queries.append((query, tuple(labels)))
        self.hints.append(tuple(section_hints))
        selected = [FusedChunk(c, 0.1, 1, 1) for c in self._chunks]
        return RetrievalResult(
            query, tuple(labels), tuple(section_hints), SearchMode.HYBRID, selected, selected
        )


class FakeConversations:
    def __init__(self) -> None:
        self.turns_by_id: dict[uuid.UUID, list[Turn]] = {}

    async def create(self) -> uuid.UUID:
        conversation_id = uuid.uuid4()
        self.turns_by_id[conversation_id] = []
        return conversation_id

    async def exists(self, conversation_id: uuid.UUID) -> bool:
        return conversation_id in self.turns_by_id

    async def delete(self, conversation_id: uuid.UUID) -> bool:
        return self.turns_by_id.pop(conversation_id, None) is not None

    async def add_turn(
        self,
        conversation_id: uuid.UUID,
        role: MessageRole,
        text: str,
        citations: Sequence[str] = (),
    ) -> Turn:
        turn = Turn(uuid.uuid4(), conversation_id, role, text, datetime.now(UTC), tuple(citations))
        self.turns_by_id[conversation_id].append(turn)
        return turn

    async def turns(self, conversation_id: uuid.UUID, limit: int | None = None) -> list[Turn]:
        turns = self.turns_by_id[conversation_id]
        return turns[-limit:] if limit else list(turns)


class NodeRecorder(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.names: list[str] = []

    async def on_chain_start(self, serialized: Any, inputs: Any, **kwargs: Any) -> None:
        self.names.append(kwargs.get("name") or "")


class FakeTurn:
    def __init__(self) -> None:
        self.recorder = NodeRecorder()
        self.run_config: Mapping[str, object] = {"callbacks": [self.recorder]}
        self.ends: list[tuple[str | None, dict[str, object], bool]] = []

    def end(self, output: str | None, metadata: Mapping[str, object], *, failed: bool) -> None:
        self.ends.append((output, dict(metadata), failed))


class FakeTracer:
    def __init__(self) -> None:
        self.started: list[tuple[uuid.UUID, str]] = []
        self.turn = FakeTurn()

    def start_turn(self, conversation_id: uuid.UUID, question: str) -> FakeTurn:
        self.started.append((conversation_id, question))
        return self.turn


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def run_turn(
    models: FakeModels,
    detector: FakeDetector,
    retriever: FakeRetriever,
    question: str = "What is the dose of Lipitor?",
    *,
    conversations: FakeConversations | None = None,
    tracer: FakeTracer | None = None,
    grader_mode: GraderMode = "llm",
) -> tuple[list[dict[str, Any]], FakeConversations, uuid.UUID]:
    store = conversations or FakeConversations()
    service = ChatService(
        store,
        models,
        detector.source,
        retriever,
        tracer or FakeTracer(),
        grader_mode=grader_mode,
    )

    async def scenario() -> tuple[list[dict[str, Any]], uuid.UUID]:
        conversation_id = next(iter(store.turns_by_id), None) or await service.start()
        return [e async for e in await service.ask(conversation_id, question)], conversation_id

    events, conversation_id = asyncio.run(scenario())
    return events, store, conversation_id


class FakeCache:
    """The Cache port in memory; records the time to live of each write."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        self.values[key] = value
        self.ttls[key] = ttl_seconds
