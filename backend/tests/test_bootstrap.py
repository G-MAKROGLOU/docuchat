import asyncio

import pytest

from app import bootstrap
from app.config import get_settings
from app.infrastructure.migrations import SchemaNotCurrentError


def test_the_worker_side_checks_the_schema_and_applies_no_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def apply(conninfo: str) -> list[str]:
        raise AssertionError("only the API applies the migrations")

    def check(conninfo: str, dimensions: int) -> None:
        raise SchemaNotCurrentError("0012_new is not applied")

    monkeypatch.setattr(bootstrap, "apply_migrations", apply)
    monkeypatch.setattr(bootstrap, "check_schema", check)

    async def open_it() -> None:
        async with bootstrap.open_current_database(get_settings()):
            pass

    with pytest.raises(SchemaNotCurrentError, match="0012_new"):
        asyncio.run(open_it())
