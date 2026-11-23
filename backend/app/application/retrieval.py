"""Hybrid retrieval: vector and BM25 searches in parallel, fused and selected."""

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar
from uuid import UUID

from app.application.fusion import FusedChunk, fuse, select
from app.domain.entities import Chunk
from app.domain.ports import ChunkSearch, Embedder

logger = logging.getLogger(__name__)

TOP_K = 20
# Each leg (the query embedding, a vector or a BM25 search) gets this long; then the turn goes on
# without it. ASSUMED value: searches take milliseconds, the embedding call about one second.
LEG_TIMEOUT_SECONDS = 5.0

T = TypeVar("T")


class SearchMode(StrEnum):
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Everything the trace needs: the query, the applied filter, both ranks per chunk."""

    query: str
    labels: tuple[UUID, ...]
    section_hints: tuple[str, ...]
    mode: SearchMode
    candidates: list[FusedChunk] = field(default_factory=list)
    selected: list[FusedChunk] = field(default_factory=list)
    # Legs that failed or timed out ("embedding", "vector", "bm25"); the others answered.
    degraded: tuple[str, ...] = ()


class _Legs:
    """Runs the legs of one retrieval; a failed leg gives no rows and is recorded."""

    def __init__(self) -> None:
        self.failed: dict[str, BaseException] = {}
        self.answered = 0

    async def run(self, name: str, call: Awaitable[T]) -> T | None:
        try:
            result = await asyncio.wait_for(call, LEG_TIMEOUT_SECONDS)
        except Exception as exc:  # any leg fault: the other leg may still answer
            logger.warning("search leg failed", extra={"leg": name, "error": repr(exc)})
            self.failed.setdefault(name, exc)
            return None
        self.answered += 1
        return result


class RetrievalService:
    def __init__(self, search: ChunkSearch, embedder: Embedder, *, top_k: int) -> None:
        self._top_k = top_k
        self._search = search
        self._embedder = embedder

    async def _search_drugs(
        self,
        query: str,
        embedding: Sequence[float] | None,
        labels: Sequence[UUID],
        legs: _Legs,
        *,
        use_bm25: bool,
    ) -> tuple[list[Chunk], list[Chunk]]:
        vector, bm25 = await asyncio.gather(
            legs.run("vector", self._search.vector_search(embedding, labels, self._top_k))
            if embedding is not None
            else _empty(),
            legs.run("bm25", self._search.text_search(query, labels, self._top_k))
            if use_bm25
            else _empty(),
        )
        return vector or [], bm25 or []

    async def retrieve(
        self,
        query: str,
        *,
        labels: Sequence[UUID] = (),
        section_hints: Sequence[str] = (),
        mode: SearchMode = SearchMode.HYBRID,
    ) -> RetrievalResult:
        use_vector = mode in {SearchMode.VECTOR, SearchMode.HYBRID}
        use_bm25 = mode in {SearchMode.BM25, SearchMode.HYBRID}
        legs = _Legs()
        embedding = (
            await legs.run("embedding", self._embedder.embed_query(query)) if use_vector else None
        )
        # A comparison searches each label on its own, so one label cannot fill the candidates.
        groups = [[label] for label in labels] if len(labels) > 1 else [list(labels)]
        runs = await asyncio.gather(
            *(self._search_drugs(query, embedding, g, legs, use_bm25=use_bm25) for g in groups)
        )
        searched = legs.answered - (embedding is not None)
        if legs.failed and searched == 0:
            # No search answered: the turn fails as before, with the first error.
            raise next(iter(legs.failed.values()))
        vector = _interleave([vector for vector, _ in runs])
        bm25 = _interleave([bm25 for _, bm25 in runs])
        fused = fuse(vector=vector, bm25=bm25, section_hints=section_hints)
        return RetrievalResult(
            query=query,
            labels=tuple(labels),
            section_hints=tuple(section_hints),
            mode=mode,
            candidates=fused,
            selected=select(fused, labels=labels),
            degraded=tuple(legs.failed),
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
