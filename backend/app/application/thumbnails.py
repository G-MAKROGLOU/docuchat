"""Page 1 thumbnails of the label PDFs, rendered once and then read from the shared cache."""

import asyncio
from collections.abc import Callable

from app.domain.ports import Cache


async def thumbnail_png(
    cache: Cache,
    key: str,
    render: Callable[[], bytes],
    *,
    slots: asyncio.Semaphore,
    ttl_seconds: int,
) -> bytes:
    """The PNG for the key (file and ETag, so a new PDF gets a new image), rendered once.
    A cold thumbnail reads the whole PDF and renders it: slots limits the renders of this
    process. The key holds the file hash and the width, so a stored PNG never goes stale."""
    if (cached := await cache.get(f"thumbnail:{key}")) is not None:
        return cached
    async with slots:
        png = await asyncio.to_thread(render)
    await cache.set(f"thumbnail:{key}", png, ttl_seconds)
    return png
