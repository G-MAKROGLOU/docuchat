"""Interfaces (ports) that infrastructure adapters implement. No framework imports."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from app.domain.entities import Chunk, Message, ModelRole, PdfLine, TextSpan


class ChatModel(Protocol):
    async def complete(self, messages: Sequence[Message]) -> str: ...

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]: ...


class ChatModelProvider(Protocol):
    def for_role(self, role: ModelRole) -> ChatModel: ...


class Embedder(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class ChunkRepository(Protocol):
    async def replace_for_document(self, document_id: UUID, chunks: Sequence[Chunk]) -> None:
        """Delete the document's chunks and insert these, in one transaction."""
        ...

    async def embedding_models(self, document_id: UUID) -> set[str]: ...


class ChunkSearch(Protocol):
    """The two retrieval lists. An empty drugs sequence means no drug filter."""

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]: ...

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]: ...

    async def embedding_models(self) -> set[str]: ...


class DocumentParser(Protocol):
    def extract_lines(self, data: bytes) -> tuple[int, list[PdfLine]]:
        """Return the page count and the text lines in reading order."""
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
