"""Postgres adapter for RuntimeSettingsRepository."""

from psycopg.types.json import Jsonb

from app.infrastructure.database import Connections


class PostgresRuntimeSettingsRepository:
    def __init__(self, connections: Connections) -> None:
        self._connections = connections

    async def load(self) -> dict[str, object]:
        async with self._connections.connection() as conn:
            cursor = await conn.execute("SELECT key, value FROM runtime_settings")
            return {row[0]: row[1] for row in await cursor.fetchall()}

    async def save(self, values: dict[str, object]) -> None:
        """Replace the saved values: keys that are not in values are removed."""
        async with (
            self._connections.connection() as conn,
            conn.transaction(),
            conn.cursor() as cursor,
        ):
            await cursor.execute(
                "DELETE FROM runtime_settings WHERE key <> ALL(%s)", (list(values),)
            )
            await cursor.executemany(
                "INSERT INTO runtime_settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                [(key, Jsonb(value)) for key, value in values.items()],
            )
