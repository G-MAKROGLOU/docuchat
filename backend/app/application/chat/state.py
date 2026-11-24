"""The chat graph state, its limits, and the ports that the nodes read."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from app.application.drug_detection import DrugDetection
from app.application.retrieval import RetrievalResult
from app.domain.entities import Chunk, Message


@dataclass(frozen=True, slots=True)
class ChatLimits:
    history_turns: int  # messages, not exchanges
    # A longer intake query is not one search question; the rewrite node makes the query then.
    max_query_chars: int
    # Rewrites and searches again after a weak grade.
    grade_retries: int
    # Seconds for a whole chat turn, all model calls included.
    turn_deadline_seconds: float
    # Greetings and library lists are short; a long reply is more than the front desk should say.
    max_reply_chars: int
    # Up to this many names, the intake prompt and a refusal list the library.
    intake_list_max: int
    max_suggestions: int
    max_suggestion_chars: int


Verdict = Literal["sufficient", "partial", "insufficient"]


class Detector(Protocol):
    def detect(self, question: str) -> DrugDetection: ...

    def catalog(self) -> list[str]: ...


# Read per turn, so labels ingested after startup are known.
DetectorSource = Callable[[], Awaitable[Detector]]

# Sends one stream event (the shape of app/api/schemas/stream.py) to the client.
Emit = Callable[[dict[str, object]], None]


class Retriever(Protocol):
    async def retrieve(
        self, query: str, *, labels: Sequence[UUID] = (), section_hints: Sequence[str] = ()
    ) -> RetrievalResult: ...


@dataclass(frozen=True, slots=True)
class SourceRef:
    id: str  # "S1"
    chunk: Chunk


class ChatState(TypedDict, total=False):
    question: str
    history: list[Message]
    action: str
    reply: str
    # Medicines the intake model found in the question; code checks them against the library.
    named: tuple[str, ...]
    query: str
    labels: tuple[UUID, ...]  # the searched labels (document IDs)
    candidates: list[str]
    sources: list[SourceRef]
    # Relevant excerpts of the first search, kept for the second one.
    kept: list[SourceRef]
    attempt: int
    verdict: str
    feedback: str
    retry: bool
    answer: str
    citations: list[str]
    ungrounded_numbers: list[str]
    refusal: str
