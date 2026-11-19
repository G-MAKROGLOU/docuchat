"""Interfaces (ports) that infrastructure adapters implement. No framework imports."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from app.domain.entities import Chunk, Message, ModelRole, ParsedPage, ScoredChunk


class ChatModel(Protocol):
    async def complete(self, messages: Sequence[Message]) -> str: ...

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]: ...


class ChatModelProvider(Protocol):
    def for_role(self, role: ModelRole) -> ChatModel: ...


class Embedder(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class ChunkRepository(Protocol):
    async def upsert(self, chunks: Sequence[Chunk]) -> None: ...

    async def search(
        self, query_text: str, query_embedding: Sequence[float], limit: int
    ) -> list[ScoredChunk]: ...


class DocumentParser(Protocol):
    def parse(self, path: Path) -> list[ParsedPage]: ...


class Span(Protocol):
    def set_attributes(self, attributes: Mapping[str, object]) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> AbstractContextManager[Span]: ...
