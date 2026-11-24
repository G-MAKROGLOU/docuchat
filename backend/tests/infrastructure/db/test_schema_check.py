import os
from pathlib import Path

import pytest

from app.infrastructure import migrations
from app.infrastructure.migrations import SchemaNotCurrentError, apply_migrations, check_schema

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def test_a_migrated_schema_passes_the_check() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)

    check_schema(conninfo, 1536)


def test_a_migration_that_is_not_applied_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)
    for path in migrations.SQL_DIR.glob("*.sql"):
        (tmp_path / path.name).write_text("", encoding="utf-8")
    (tmp_path / "9999_future.sql").write_text("", encoding="utf-8")
    monkeypatch.setattr(migrations, "SQL_DIR", tmp_path)

    with pytest.raises(SchemaNotCurrentError, match=r"9999_future.*Start the API"):
        check_schema(conninfo, 1536)


def test_a_wrong_vector_size_stops_the_start() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)

    with pytest.raises(SchemaNotCurrentError, match=r"EMBEDDING_DIMENSIONS=3072"):
        check_schema(conninfo, 3072)
