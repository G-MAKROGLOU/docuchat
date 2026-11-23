"""Runs one ingestion pass over all documents in the background. One pass at a time."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.application.corpus_update import UpdateReport
from app.application.ingestion import IngestionService, IngestResult
from app.application.label_queue import QueueReport
from app.domain.documents import Document, DocumentRepository
from app.domain.ingestion_state import IngestionPhase

logger = logging.getLogger(__name__)


async def ingest_each[T](
    documents: Sequence[Document],
    ingest: Callable[[Document], Awaitable[T]],
    *,
    concurrency: int,
) -> list[T]:
    """Runs ingest for each document, at most concurrency at the same time. The results keep the
    document order. ingest must catch its own errors: on a raise, gather stops waiting."""
    slots = asyncio.Semaphore(concurrency)

    async def one(document: Document) -> T:
        async with slots:
            return await ingest(document)

    return list(await asyncio.gather(*(one(d) for d in documents)))


class ChunkingTracker(Protocol):
    """Knows whether the index was built with the current chunk settings."""

    async def stale(self) -> bool: ...

    async def mark_embedded(self) -> None: ...


class IngestionRunner:
    def __init__(  # noqa: PLR0913  # five ports plus the document limit
        self,
        service: IngestionService,
        documents: DocumentRepository,
        check_updates: Callable[[], Awaitable[UpdateReport]],
        take_queue: Callable[[], Awaitable[QueueReport]],
        chunking: ChunkingTracker,
        *,
        concurrency: int,
    ) -> None:
        """concurrency: documents ingested at the same time. Each holds 2 pooled connections at
        most (lock, writes), so the pool size must stay above 2 times this value."""
        self._service = service
        self._concurrency = concurrency
        self._documents = documents
        self._check_updates = check_updates
        self._take_queue = take_queue
        self._chunking = chunking
        self._task: asyncio.Task[None] | None = None
        self._schedule_task: asyncio.Task[None] | None = None
        self._next_run_at: datetime | None = None
        self._phase: IngestionPhase = "idle"
        # Called with each document's result and seconds, for the metrics.
        self.observe: Callable[[IngestResult, float], None] | None = None

    @property
    def phase(self) -> IngestionPhase:
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

    def start_schedule(self, interval: timedelta) -> None:
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
            # One take is limited, so take again until the queue is empty.
            while (queued := await self._take_queue()).added or queued.failed:
                logger.info("label queue: %d added, %d failed", queued.added, queued.failed)
            self._phase = "ingesting"
            # A pass that was cut short earlier left documents with the old chunk settings.
            force = force or await self._chunking.stale()
            raised = False

            async def ingest(document: Document) -> None:
                nonlocal raised
                started = time.perf_counter()
                try:
                    # The service is read per document, so a settings change applies from the next.
                    result = await self._service.ingest(document, force=force)
                except Exception:
                    raised = True
                    logger.exception("ingestion failed", extra={"document_id": str(document.id)})
                    return
                if self.observe is not None:
                    self.observe(result, time.perf_counter() - started)

            await ingest_each(
                await self._documents.list_all(), ingest, concurrency=self._concurrency
            )
            # A document that raised kept its status, and maybe chunks of the old index.
            if force and not raised:
                await self._chunking.mark_embedded()
        except Exception:
            logger.exception("ingestion pass failed")
        finally:
            self._phase = "idle"
