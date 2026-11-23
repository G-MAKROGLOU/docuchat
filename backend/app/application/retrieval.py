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
    def __init__(self, search: ChunkSearch, embedder: Embedder, *, top_k: int) -> None:
        self._top_k = top_k
        self._search = search
        self._embedder = embedder

    async def _search_drugs(
        self,
        query: str,
        embedding: Sequence[float] | None,
        drugs: Sequence[str],
        *,
        use_bm25: bool,
    ) -> tuple[list[Chunk], list[Chunk]]:
        vector, bm25 = await asyncio.gather(
            self._search.vector_search(embedding, drugs, self._top_k)
            if embedding is not None
            else _empty(),
            self._search.text_search(query, drugs, self._top_k) if use_bm25 else _empty(),
        )
        return vector, bm25

    async def retrieve(
        self,
        query: str,
        *,
        drugs: Sequence[str] = (),
        section_hints: Sequence[str] = (),
        mode: SearchMode = SearchMode.HYBRID,
    ) -> RetrievalResult:
        use_vector = mode in {SearchMode.VECTOR, SearchMode.HYBRID}
        use_bm25 = mode in {SearchMode.BM25, SearchMode.HYBRID}
        embedding = await self._embedder.embed_query(query) if use_vector else None
        # A comparison searches each drug on its own, so one drug cannot fill the candidates.
        groups = [[drug] for drug in drugs] if len(drugs) > 1 else [list(drugs)]
        runs = await asyncio.gather(
            *(self._search_drugs(query, embedding, g, use_bm25=use_bm25) for g in groups)
        )
        vector = _interleave([vector for vector, _ in runs])
        bm25 = _interleave([bm25 for _, bm25 in runs])
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


def _interleave(lists: Sequence[Sequence[Chunk]]) -> list[Chunk]:
    """The first of each list, then the second of each, and so on; a chunk once."""
    merged: list[Chunk] = []
    seen: set[object] = set()
    for rank in range(max((len(items) for items in lists), default=0)):
        for items in lists:
            if rank < len(items) and items[rank].id not in seen:
                seen.add(items[rank].id)
                merged.append(items[rank])
    return merged
