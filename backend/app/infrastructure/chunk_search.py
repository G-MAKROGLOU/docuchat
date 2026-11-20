"""ChunkSearch adapter: pgvector HNSW (cosine) and ParadeDB BM25, with the same drug filter."""

from collections.abc import Sequence
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row

from app.domain.entities import Chunk
from app.infrastructure.chunk_repository import vector_literal
from app.infrastructure.database import Connections

_FIELDS = (
    "id",
    "document_id",
    "drug_name",
    "section_number",
    "section_title",
    "page_start",
    "page_end",
    "content",
    "anchor",
    "token_count",
    "embedding_model",
)
_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, _FIELDS))


def _filter(drugs: Sequence[str]) -> tuple[sql.Composable, tuple[Any, ...]]:
    if not drugs:
        return sql.SQL(""), ()
    return sql.SQL(" AND drug_name = ANY(%s)"), (list(drugs),)


class PostgresChunkSearch:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def vector_search(
        self, embedding: Sequence[float], drugs: Sequence[str], limit: int
    ) -> list[Chunk]:
        where, params = _filter(drugs)
        query = sql.SQL(
            "SELECT {} FROM chunks WHERE TRUE{} ORDER BY embedding <=> %s::vector LIMIT %s"
        ).format(_COLUMNS, where)
        async with (
            self._connections.connection() as conn,
            conn.transaction(),
        ):
            # With a drug filter, keep scanning the HNSW graph until enough rows match.
            await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(query, (*params, vector_literal(embedding), limit))
            rows = await cursor.fetchall()
        return [Chunk(**row) for row in rows]

    async def text_search(self, query: str, drugs: Sequence[str], limit: int) -> list[Chunk]:
        where, params = _filter(drugs)
        # ||| matches any token; ### boosts tokens in order, so "2.5 mg twice daily" ranks above
        # "5 mg ... twice daily". Both tokenize the text and do not parse query syntax.
        statement = sql.SQL(
            "SELECT {} FROM chunks "
            "WHERE (content ||| %s OR content ### %s::pdb.boost(2)){} "
            "ORDER BY pdb.score(id) DESC LIMIT %s"
        ).format(_COLUMNS, where)
        async with self._connections.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(statement, (query, query, *params, limit))
            rows = await cursor.fetchall()
        return [Chunk(**row) for row in rows]

    async def embedding_models(self) -> set[str]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute("SELECT DISTINCT embedding_model FROM chunks")
            return {str(row[0]) for row in await cursor.fetchall()}
