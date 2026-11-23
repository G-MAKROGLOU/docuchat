"""Tests for the infrastructure review fixes: pool limits and thumbnails."""

import asyncio
import time

from app.application.thumbnails import thumbnail_png
from app.config import load_settings
from app.infrastructure.database import build_pool
from tests.support.fakes_ports import FakeCache


def test_the_pool_limits_waiting_and_statement_time() -> None:
    settings = load_settings()
    pool = build_pool(settings)

    assert pool.timeout == settings.db_pool_timeout_seconds
    assert pool.max_waiting == settings.db_pool_max_waiting
    assert (pool.min_size, pool.max_size) == (settings.db_pool_min_size, settings.db_pool_max_size)
    assert isinstance(pool.kwargs, dict)
    assert f"statement_timeout={settings.db_statement_timeout_ms}" in pool.kwargs["options"]


def test_a_thumbnail_is_rendered_once_and_then_served_from_the_cache() -> None:
    calls: list[str] = []

    def render() -> bytes:
        calls.append("render")
        return b"png"

    cache = FakeCache()

    SLOTS = asyncio.Semaphore(1)  # noqa: N806  # one name for both calls

    async def twice() -> list[bytes]:
        return [
            await thumbnail_png(cache, "key-once", render, slots=SLOTS, ttl_seconds=60),
            await thumbnail_png(cache, "key-once", render, slots=SLOTS, ttl_seconds=60),
        ]

    assert asyncio.run(twice()) == [b"png", b"png"]
    assert calls == ["render"]
    assert cache.values == {"thumbnail:key-once": b"png"}


def test_at_most_a_few_thumbnails_render_at_the_same_time() -> None:
    running, peak = [0], [0]

    def render() -> bytes:
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        running[0] -= 1
        return b"png"

    async def many() -> None:
        cache, slots = FakeCache(), asyncio.Semaphore(4)
        await asyncio.gather(
            *(
                thumbnail_png(cache, f"key-{i}", render, slots=slots, ttl_seconds=60)
                for i in range(12)
            )
        )

    asyncio.run(many())

    assert 1 < peak[0] <= 4
