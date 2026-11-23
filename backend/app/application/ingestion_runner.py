"""Runs one ingestion pass over all documents in the background. One pass at a time."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.application.corpus_update import UpdateReport
from app.application.ingestion import IngestionService, IngestResult
from app.application.label_queue import QueueReport
from app.domain.documents import DocumentRepository

logger = logging.getLogger(__name__)

# DailyMed publishes label updates daily.
SCHEDULE_INTERVAL = timedelta(days=1)


class ChunkingTracker(Protocol):
    """Knows whether the index was built with the current chunk settings."""

    async def stale(self) -> bool: ...

    async def mark_embedded(self) -> None: ...


class IngestionRunner:
    def __init__(
        self,
        service: IngestionService,
        documents: DocumentRepository,
        check_updates: Callable[[], Awaitable[UpdateReport]],
        take_queue: Callable[[], Awaitable[QueueReport]],
        chunking: ChunkingTracker,
    ) -> None:
        self._service = service
        self._documents = documents
        self._check_updates = check_updates
        self._take_queue = take_queue
        self._chunking = chunking
        self._task: asyncio.Task[None] | None = None
        self._schedule_task: asyncio.Task[None] | None = None
        self._next_run_at: datetime | None = None
        self._phase: Literal["idle", "checking", "downloading", "ingesting"] = "idle"
        # Called with each document's result and seconds, for the metrics.
        self.observe: Callable[[IngestResult, float], None] | None = None

    @property
    def phase(self) -> Literal["idle", "checking", "downloading", "ingesting"]:
        """What the running pass does now: check labels for updates, then ingest."""
        return self._phase

    @property
    def next_run_at(self) -> datetime | None:
        """When the scheduled pass starts. None when no schedule runs."""
        return self._next_run_at

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def use_service(self, service: IngestionService) -> None:
        """Use another ingestion service from the next document on."""
        self._service = service

    def start(self, *, force: bool = False) -> bool:
        """Start a pass. False when one is already running. force: embed every document again."""
        if self.running:
            return False
        self._task = asyncio.create_task(self._run(force))
        return True

    def start_schedule(self, interval: timedelta = SCHEDULE_INTERVAL) -> None:
        """Start a pass every interval, counted from now. A manual pass does not move it."""
        self._schedule_task = asyncio.create_task(self._schedule(interval))

    async def stop(self) -> None:
        tasks = [t for t in (self._schedule_task, self._task) if t is not None and not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._next_run_at = None

    async def _schedule(self, interval: timedelta) -> None:
        while True:
            self._next_run_at = datetime.now(UTC) + interval
            await asyncio.sleep(interval.total_seconds())
            self.start()

    async def _run(self, force: bool = False) -> None:
        try:
            # Changed labels go back to stored; ingested documents are skipped by the service.
            self._phase = "checking"
            report = await self._check_updates()
            logger.info(
                "update check: %d checked, %d updated, %d failed",
                report.checked,
                report.updated,
                report.failed,
            )
            self._phase = "downloading"
            queued = await self._take_queue()
            logger.info("label queue: %d added, %d failed", queued.added, queued.failed)
            self._phase = "ingesting"
            # A pass that was cut short earlier left documents with the old chunk settings.
            force = force or await self._chunking.stale()
            for document in await self._documents.list_all():
                started = time.perf_counter()
                result = await self._service.ingest(document, force=force)
                if self.observe is not None:
                    self.observe(result, time.perf_counter() - started)
            if force:
                await self._chunking.mark_embedded()
        except Exception:
            logger.exception("ingestion pass failed")
        finally:
            self._phase = "idle"
