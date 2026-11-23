"""Postgres adapter for CorpusStatsRepository, and a cache over its chunk totals."""

from collections.abc import Awaitable, Callable

from app.domain.corpus_stats import CorpusStats, CorpusStatsRepository
from app.infrastructure.database import Connections


class PostgresCorpusStatsRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def stats(self) -> CorpusStats:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT count(*), COALESCE(sum(token_count), 0), "
                "COALESCE(array_agg(DISTINCT embedding_model), '{}') FROM chunks"
            )
            row = await cursor.fetchone()
        if row is None:
            return CorpusStats(chunk_count=0, token_count=0, embedding_models=[])
        return CorpusStats(
            chunk_count=int(row[0]), token_count=int(row[1]), embedding_models=sorted(row[2])
        )

    async def document_counts(self) -> dict[str, int]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute("SELECT status, count(*) FROM documents GROUP BY status")
            return {str(status): int(count) for status, count in await cursor.fetchall()}


class CachedCorpusStats:
    """The chunk totals scan the whole chunks table, so they come from a cache that reads them
    again only after the library changed. Document counts are cheap and always current."""

    def __init__(
        self, inner: CorpusStatsRepository, stats: Callable[[], Awaitable[CorpusStats]]
    ) -> None:
        self._inner = inner
        self._stats = stats

    async def stats(self) -> CorpusStats:
        return await self._stats()

    async def document_counts(self) -> dict[str, int]:
        return await self._inner.document_counts()
