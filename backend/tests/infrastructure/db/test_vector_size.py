import os

import pytest

from app.infrastructure.migrations import apply_migrations, check_vector_size

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def test_the_configured_size_matches_the_vector_column() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)

    check_vector_size(conninfo, 1536)


def test_another_size_stops_the_start_with_a_clear_message() -> None:
    conninfo = os.environ["TEST_DATABASE_URL"]
    apply_migrations(conninfo)

    with pytest.raises(RuntimeError, match=r"EMBEDDING_DIMENSIONS=3072.*1536"):
        check_vector_size(conninfo, 3072)
