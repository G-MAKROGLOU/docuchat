"""Domain entities. No framework imports."""

from dataclasses import dataclass, field
from enum import StrEnum


class ModelRole(StrEnum):
    REWRITE = "rewrite"
    GRADE = "grade"
    GENERATE = "generate"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ParsedPage:
    document: str
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    document: str
    drug: str
    section: str
    page: int
    text: str
    embedding: tuple[float, ...] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float
