"""Interfaces (ports) that infrastructure adapters implement. No framework imports."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from app.domain.entities import Chunk, LabelNode, Message, ModelRole, TextSpan


class ChatModel(Protocol):
    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str:
        """With `json_schema`, the reply is JSON that follows that schema."""
        ...

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]: ...


class ChatModelProvider(Protocol):
    def for_role(self, role: ModelRole) -> ChatModel: ...


class Embedder(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class Cache(Protocol):
    """A shared cache of byte values. A failure counts as a miss, so a request never fails
    because of the cache."""

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...


class ChunkRepository(Protocol):
    async def replace_for_document(self, document_id: UUID, chunks: Sequence[Chunk]) -> None:
        """Delete the document's chunks and insert these, in one transaction."""
        ...

    async def embedding_models(self, document_id: UUID) -> set[str]: ...


class ChunkSearch(Protocol):
    """The two retrieval lists. An empty drugs sequence means no drug filter. The vector list
    holds only chunks embedded with the query's model, so a half-done re-embed still works."""

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]: ...

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]: ...


class DocumentParser(Protocol):
    def page_texts(self, data: bytes) -> list[str]:
        """Return the text of each page in reading order."""
        ...


class LabelParser(Protocol):
    def sections(self, data: bytes) -> list[LabelNode]:
        """Return the top-level sections of the label body in document order."""
        ...


class TextSplitter(Protocol):
    def split(self, text: str) -> list[TextSpan]: ...


class NameSimilarity(Protocol):
    def ratio(self, a: str, b: str) -> float:
        """Similarity of two names, 0 to 100."""
        ...


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class Span(Protocol):
    def set_attributes(self, attributes: Mapping[str, object]) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> AbstractContextManager[Span]: ...


class TurnTrace(Protocol):
    """One traced chat turn. `run_config` goes to the graph run (callbacks, metadata)."""

    run_config: Mapping[str, object]

    def end(self, output: str | None, metadata: Mapping[str, object], *, failed: bool) -> None: ...


class TurnTracer(Protocol):
    def start_turn(self, conversation_id: UUID, question: str) -> TurnTrace: ...
