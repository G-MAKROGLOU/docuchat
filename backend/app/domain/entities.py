"""Domain entities. No framework imports."""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class ModelRole(StrEnum):
    CHAT = "chat"
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
class LabelNode:
    """One section of a structured label: section code, title, own text and subsections."""

    code: str
    title: str
    text: str
    children: tuple["LabelNode", ...] = ()


@dataclass(frozen=True, slots=True)
class LabelSection:
    """A numbered label section ("2.1"), or "BW" for the boxed warning."""

    number: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class TextSpan:
    start: int
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    id: UUID
    document_id: UUID
    drug_name: str
    section_number: str
    section_title: str
    page_start: int
    page_end: int
    content: str
    anchor: str
    token_count: int
    embedding: tuple[float, ...] | None = field(default=None, repr=False)
    embedding_model: str | None = None
    # Caption and header row of the table that the chunk continues; empty outside a table.
    table_header: str = ""


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float
