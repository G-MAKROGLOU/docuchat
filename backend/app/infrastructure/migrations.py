"""Applies the SQL files in app/infrastructure/sql in name order, once each. Usage: python -m ..."""

import logging
from pathlib import Path

import psycopg

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent / "sql"
# Any fixed number; it serializes concurrent runs (several workers or containers).
_LOCK_ID = 7_310_001


class SchemaNotCurrentError(RuntimeError):
    """The database schema does not match this code; the process must not start."""


def apply_migrations(conninfo: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(conninfo, autocommit=False) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(SQL_DIR.glob("*.sql")):
            if path.stem in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))  # trusted file from this package
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
        conn.commit()
    for version in applied:
        logger.info("migration applied", extra={"version": version})
    return applied


def pending_migrations(conninfo: str) -> list[str]:
    """The migration files that schema_migrations does not record, in name order."""
    with psycopg.connect(conninfo) as conn:
        row = conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()
        done = (
            {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            if row and row[0]
            else set()
        )
    return [path.stem for path in sorted(SQL_DIR.glob("*.sql")) if path.stem not in done]


def check_schema(conninfo: str, dimensions: int) -> None:
    """For the processes that do not own the migrations: stop when the schema is not current."""
    if pending := pending_migrations(conninfo):
        raise SchemaNotCurrentError(
            f"The database schema is not current: {', '.join(pending)} not applied. "
            "Start the API first; it applies the migrations."
        )
    check_vector_size(conninfo, dimensions)


def check_vector_size(conninfo: str, dimensions: int) -> None:
    """The vector column has a fixed size; a different EMBEDDING_DIMENSIONS would fail on the
    first ingest or query, so the process stops at start with the fix instead."""
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
    column = int(row[0]) if row else None
    if column != dimensions:
        raise SchemaNotCurrentError(
            f"EMBEDDING_DIMENSIONS={dimensions}, but the chunks.embedding column holds {column} "
            "values. Use an embedding model and size that match, or migrate the column."
        )


if __name__ == "__main__":
    from app.config import get_settings

    print(apply_migrations(get_settings().database_url.get_secret_value()) or "up to date")
