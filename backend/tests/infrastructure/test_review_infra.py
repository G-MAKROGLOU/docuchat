"""Tests for the infrastructure review fixes: pool limits and thumbnails."""

import asyncio
import time

from app.api.routers.documents import THUMBNAIL_CONCURRENCY, thumbnail_png
from app.config import load_settings
from app.infrastructure.database import POOL_MAX_WAITING, POOL_TIMEOUT_SECONDS, build_pool
from tests.support.fakes_ports import FakeCache


def test_the_pool_limits_waiting_and_statement_time() -> None:
    pool = build_pool(load_settings())

    assert pool.timeout == POOL_TIMEOUT_SECONDS
    assert pool.max_waiting == POOL_MAX_WAITING
    assert isinstance(pool.kwargs, dict)
    assert "statement_timeout=30000" in pool.kwargs["options"]


def test_a_thumbnail_is_rendered_once_and_then_served_from_the_cache() -> None:
    calls: list[str] = []

    def render() -> bytes:
        calls.append("render")
        return b"png"

    cache = FakeCache()

    async def twice() -> list[bytes]:
        return [
            await thumbnail_png(cache, "key-once", render),
            await thumbnail_png(cache, "key-once", render),
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
        cache = FakeCache()
        await asyncio.gather(*(thumbnail_png(cache, f"key-{i}", render) for i in range(12)))

    asyncio.run(many())

    assert 1 < peak[0] <= THUMBNAIL_CONCURRENCY
