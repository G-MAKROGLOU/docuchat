"""A value built again only after the library version changed."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class VersionedCache[T]:
    """Builds a value once per library version. The version check is one small query; the
    build can read every document, so it runs only after the library changed. A new version
    rebuilds it at most once per min_interval seconds."""

    def __init__(
        self,
        version: Callable[[], Awaitable[object]],
        build: Callable[[], Awaitable[T]],
        *,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._version = version
        self._build = build
        self._min_interval = min_interval
        self._clock = clock
        self._lock = asyncio.Lock()
        self._built: tuple[object, T] | None = None
        self._built_at = 0.0

    def _current(self, built: tuple[object, T], version: object) -> bool:
        # During an ingestion pass the version changes with each document; a value that is a
        # few seconds old is good enough, so it is rebuilt at most once per interval.
        return built[0] == version or self._clock() - self._built_at < self._min_interval

    async def __call__(self) -> T:
        version = await self._version()
        if self._built is not None and self._current(self._built, version):
            return self._built[1]
        async with self._lock:
            # Another call may have built it while this one waited.
            if self._built is None or not self._current(self._built, version):
                self._built = (version, await self._build())
                self._built_at = self._clock()
            return self._built[1]
