"""Retrieval adapters for the ablations. They live in the eval, so the running
service keeps one search path.

- ModeRetriever forces a search mode and keeps each RetrievalResult for the retrieval metrics.
- CosineSearch answers vector searches from vectors held in memory. The prefix ablation uses it
  with chunk vectors embedded without the "Drug: ... Section: ..." prefix, so the stored index
  stays as it is. BM25 does not use the prefix and stays on Postgres."""

import asyncio
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from psycopg.rows import dict_row

from app.application.chunking import embedding_input
from app.application.retrieval import RetrievalResult, SearchMode
from app.domain.entities import Chunk
from app.domain.ports import ChunkSearch, Embedder
from app.infrastructure.database import Connections


class ModeSearch(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        drugs: Sequence[str] = (),
        section_hints: Sequence[str] = (),
        mode: SearchMode = SearchMode.HYBRID,
    ) -> RetrievalResult: ...


class ModeRetriever:
    def __init__(self, inner: ModeSearch, mode: SearchMode | str) -> None:
        self._inner = inner
        self._mode = SearchMode(mode)
        self._results: list[RetrievalResult] = []

    async def retrieve(
        self, query: str, *, drugs: Sequence[str] = (), section_hints: Sequence[str] = ()
    ) -> RetrievalResult:
        result = await self._inner.retrieve(
            query, drugs=drugs, section_hints=section_hints, mode=self._mode
        )
        self._results.append(result)
        return result

    def take(self) -> list[RetrievalResult]:
        """The results since the last call: one per search of the turn (a retry adds one)."""
        results, self._results = self._results, []
        return results


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(math.sumprod(vector, vector)) or 1.0
    return tuple(v / norm for v in vector)


class CosineSearch:
    def __init__(self, text: ChunkSearch, vectors: Sequence[tuple[Chunk, Sequence[float]]]) -> None:
        self._text = text
        self._vectors = [(chunk, _unit(vector)) for chunk, vector in vectors]

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]:
        query = _unit(embedding)
        wanted = set(drugs)
        scored = [
            (math.sumprod(query, vector), chunk)
            for chunk, vector in self._vectors
            if not wanted or chunk.drug_name in wanted
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]:
        return await self._text.text_search(query, drugs, limit)


_FIELDS = (
    "id, document_id, drug_name, section_number, section_title, page_start, page_end, "
    "content, anchor, token_count, embedding_model"
)


async def stored_chunks(connections: Connections, embedding_model: str) -> list[Chunk]:
    async with connections.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"SELECT {_FIELDS} FROM chunks WHERE embedding_model = %s ORDER BY id",  # noqa: S608
            (embedding_model,),
        )
        return [Chunk(**row) for row in await cursor.fetchall()]


async def unprefixed_vectors(
    chunks: Sequence[Chunk], embedder: Embedder, cache: Path, batch: int = 256
) -> list[tuple[Chunk, list[float]]]:
    """Vectors of the raw chunk text, cached by chunk ID, so a second run embeds nothing new."""
    saved: dict[str, Any] = await asyncio.to_thread(_read, cache)
    missing = [c for c in chunks if str(c.id) not in saved]
    for start in range(0, len(missing), batch):
        part = missing[start : start + batch]
        texts = [embedding_input("", "", "", c.content, prefix=False) for c in part]
        for chunk, vector in zip(part, await embedder.embed_documents(texts), strict=True):
            saved[str(chunk.id)] = vector
    if missing:
        await asyncio.to_thread(_write, cache, saved)
    return [(c, saved[str(c.id)]) for c in chunks]


def _read(cache: Path) -> dict[str, Any]:
    return json.loads(cache.read_text()) if cache.exists() else {}


def _write(cache: Path, saved: dict[str, Any]) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(saved))
