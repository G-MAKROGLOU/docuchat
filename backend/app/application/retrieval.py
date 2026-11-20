"""Hybrid retrieval: vector and BM25 searches in parallel, fused and selected."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.application.fusion import FusedChunk, fuse, select
from app.domain.entities import Chunk
from app.domain.ports import ChunkSearch, Embedder

TOP_K = 20


class SearchMode(StrEnum):
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"


class EmbeddingModelMismatchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Everything the trace needs: the query, the applied filter, both ranks per chunk."""

    query: str
    drugs: tuple[str, ...]
    section_hints: tuple[str, ...]
    mode: SearchMode
    candidates: list[FusedChunk] = field(default_factory=list)
    selected: list[FusedChunk] = field(default_factory=list)


class RetrievalService:
    def __init__(self, search: ChunkSearch, embedder: Embedder, embedding_model: str) -> None:
        self._search = search
        self._embedder = embedder
        self._model = embedding_model
        self._model_checked = False

    async def _check_embedding_model(self) -> None:
        if self._model_checked:
            return
        indexed = await self._search.embedding_models()
        if indexed - {self._model}:
            raise EmbeddingModelMismatchError(
                f"The index holds embeddings from {sorted(indexed)}, but queries use "
                f"{self._model!r}. Ingest again with: python -m app.ingest --all --force"
            )
        # An empty index proves nothing; a later ingest can still use another model.
        self._model_checked = bool(indexed)

    async def _vector(self, query: str, drugs: Sequence[str]) -> list[Chunk]:
        return await self._search.vector_search(
            await self._embedder.embed_query(query), drugs, TOP_K
        )

    async def retrieve(
        self,
        query: str,
        *,
        drugs: Sequence[str] = (),
        section_hints: Sequence[str] = (),
        mode: SearchMode = SearchMode.HYBRID,
    ) -> RetrievalResult:
        await self._check_embedding_model()
        use_vector = mode in {SearchMode.VECTOR, SearchMode.HYBRID}
        use_bm25 = mode in {SearchMode.BM25, SearchMode.HYBRID}
        vector, bm25 = await asyncio.gather(
            self._vector(query, drugs) if use_vector else _empty(),
            self._search.text_search(query, drugs, TOP_K) if use_bm25 else _empty(),
        )
        fused = fuse(vector=vector, bm25=bm25, section_hints=section_hints)
        return RetrievalResult(
            query=query,
            drugs=tuple(drugs),
            section_hints=tuple(section_hints),
            mode=mode,
            candidates=fused,
            selected=select(fused, drugs=drugs),
        )


async def _empty() -> list[Chunk]:
    return []
