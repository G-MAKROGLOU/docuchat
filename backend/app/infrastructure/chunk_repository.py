"""Postgres adapter for ChunkRepository (pgvector column, ParadeDB BM25 index)."""

from collections.abc import Sequence
from uuid import UUID

from app.domain.entities import Chunk
from app.infrastructure.database import Connections


def vector_literal(values: Sequence[float]) -> str:
    """pgvector text input, so no extra driver package is needed."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class PostgresChunkRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def replace_for_document(self, document_id: UUID, chunks: Sequence[Chunk]) -> None:
        if any(c.document_id != document_id or c.embedding is None for c in chunks):
            raise ValueError("Every chunk must belong to the document and have an embedding")
        async with (
            self._connections.connection() as conn,
            conn.transaction(),
            conn.cursor() as cursor,
        ):
            await cursor.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            await cursor.executemany(
                "INSERT INTO chunks (id, document_id, drug_name, section_number, "
                "section_title, page_start, page_end, content, anchor, embedding, "
                "embedding_model, token_count, table_header) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)",
                [
                    (
                        c.id,
                        c.document_id,
                        c.drug_name,
                        c.section_number,
                        c.section_title,
                        c.page_start,
                        c.page_end,
                        c.content,
                        c.anchor,
                        vector_literal(c.embedding or ()),
                        c.embedding_model,
                        c.token_count,
                        c.table_header,
                    )
                    for c in chunks
                ],
            )

    async def embedding_models(self, document_id: UUID) -> set[str]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute(
                "SELECT DISTINCT embedding_model FROM chunks WHERE document_id = %s", (document_id,)
            )
            return {str(row[0]) for row in await cursor.fetchall()}
