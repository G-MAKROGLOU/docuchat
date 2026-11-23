"""The live runtime settings of one process. A change rebuilds the services that read them, also
when another process saved it. Also tracks which chunk settings the index was built with, so a
half-finished re-embedding is finished later."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import fields

from app.application.runtime_settings import INDEX_FIELDS, merge_runtime_settings
from app.domain.runtime_settings import RuntimeSettings, RuntimeSettingsRepository

logger = logging.getLogger(__name__)

# Saved next to the settings: the chunk settings and embedding model that the index was built with.
EMBEDDED_KEY = "embedded_index"
_INDEX = INDEX_FIELDS
# How often a process looks for a save by another process.
REFRESH_SECONDS = 1.0

# Builds the services for the settings and returns the step that puts them in use.
Rebuild = Callable[[RuntimeSettings], Awaitable[Callable[[], None]]]


def _index(settings: RuntimeSettings) -> dict[str, object]:
    return {name: getattr(settings, name) for name in _INDEX}


class RuntimeConfig:
    def __init__(
        self,
        repository: RuntimeSettingsRepository,
        defaults: RuntimeSettings,
        rebuild: Rebuild,
        *,
        request_pass: Callable[[], Awaitable[bool]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._defaults = defaults
        self._rebuild = rebuild
        self._request_pass = request_pass
        self._clock = clock
        self._saved: dict[str, object] = {}
        self._checked_at = clock()
        # One change at a time: a refresh, a save and the embedded marker read and write _saved.
        self._lock = asyncio.Lock()
        self.current = defaults

    async def load(self) -> None:
        """Read the saved settings and build the services for them."""
        self._saved = await self._repository.load()
        self._checked_at = self._clock()
        await self._use(merge_runtime_settings(self._defaults, self._saved))

    async def _use(self, settings: RuntimeSettings) -> None:
        # Build first: a failure here leaves the running settings as they were.
        commit = await self._rebuild(settings)
        self.current = settings
        commit()

    async def refresh(self) -> bool:
        """Use the settings that another process saved. True when they changed. A failed
        rebuild keeps the running settings and is tried again at the next check."""
        if self._clock() - self._checked_at < REFRESH_SECONDS:
            return False
        self._checked_at = self._clock()
        async with self._lock:
            saved = await self._repository.load()
            if saved == self._saved:
                return False
            settings = merge_runtime_settings(self._defaults, saved)
            changed = settings != self.current
            if changed:
                try:
                    await self._use(settings)
                except Exception:
                    # _saved stays old, so the next check builds again.
                    logger.warning("settings refresh failed; keeping the old ones", exc_info=True)
                    return False
            self._saved = saved
            return changed

    async def apply(self, new: RuntimeSettings, *, reingest: bool) -> bool:
        """Save and use the settings. True when a pass that embeds every document was accepted."""
        async with self._lock:
            commit = await self._rebuild(new)
            embedded = (await self._repository.load()).get(EMBEDDED_KEY)
            if reingest and embedded is None:
                embedded = _index(self.current)
            await self._save(self._stored(new, embedded))
            self.current = new
            # A running turn keeps the old service; the next one uses the new one.
            commit()
        # When a pass runs already, the next pass finds the stale marker and embeds again.
        if reingest and self._request_pass is not None:
            return await self._request_pass()
        return False

    async def _save(self, values: dict[str, object]) -> None:
        await self._repository.save(values)
        self._saved = values

    def _stored(self, settings: RuntimeSettings, embedded: object) -> dict[str, object]:
        """Only the fields that differ from the defaults, so a changed default still applies."""
        stored = {
            f.name: getattr(settings, f.name)
            for f in fields(settings)
            if getattr(settings, f.name) != getattr(self._defaults, f.name)
        }
        if embedded is not None:
            stored[EMBEDDED_KEY] = embedded
        return stored

    async def stale(self) -> bool:
        """True when the index was built with other chunk settings than the current ones."""
        embedded = (await self._repository.load()).get(EMBEDDED_KEY)
        return embedded is not None and embedded != _index(self.current)

    async def mark_embedded(self) -> None:
        """Record that every document was embedded with the current chunk settings."""
        async with self._lock:
            await self._save(self._stored(self.current, _index(self.current)))
