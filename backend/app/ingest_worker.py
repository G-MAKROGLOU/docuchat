"""The ingest worker: runs the daily schedule and the passes that the API asks for.
Run exactly one. Usage: python -m app.ingest_worker"""

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime, timedelta

from app.application.corpus_update import UpdateReport, check_for_updates
from app.application.ingestion import IngestionService
from app.application.ingestion_control import IngestWorker
from app.application.ingestion_runner import IngestionRunner
from app.application.label_queue import QueueContext, QueueReport, process_queue
from app.bootstrap import load_runtime_config, open_database
from app.config import Settings, get_settings
from app.domain.ingestion_state import IngestionPhase, IngestionState, IngestionStateRepository
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.dailymed import DEFAULT_LABEL_TEMPLATE, DEFAULT_PDF_TEMPLATE, DailyMedClient
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.ingestion_state_repository import PostgresIngestionStateRepository
from app.infrastructure.label_queue_repository import PostgresLabelQueueRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.metrics import observe_ingest, observe_phase, serve
from app.infrastructure.models import close_model_clients
from app.infrastructure.spl_parser import SplXmlParser
from app.infrastructure.storage import build_document_store
from app.wiring import ingestion_service

logger = logging.getLogger(__name__)
# Prometheus reads the worker here; the API serves its metrics on its own port.
METRICS_PORT = 9100


class MeteredState:
    """The shared state, plus the phase and report time as metrics."""

    def __init__(self, inner: IngestionStateRepository) -> None:
        self._inner = inner

    async def load(self) -> IngestionState:
        return await self._inner.load()

    async def request(self, *, force: bool) -> None:
        await self._inner.request(force=force)

    async def take(self) -> bool | None:
        return await self._inner.take()

    async def report(self, phase: IngestionPhase, next_run_at: datetime | None) -> None:
        await self._inner.report(phase, next_run_at)
        observe_phase(phase)


async def run(settings: Settings) -> None:
    async with open_database(settings) as pool:
        documents = PostgresDocumentRepository(pool)
        store = await asyncio.to_thread(build_document_store, settings)
        queue = PostgresLabelQueueRepository(pool)
        source = DailyMedClient(
            DEFAULT_PDF_TEMPLATE,
            DEFAULT_LABEL_TEMPLATE,
            timeout_seconds=settings.source_timeout_seconds,
            max_bytes=settings.source_max_bytes,
            attempts=settings.source_attempts,
            first_backoff_seconds=settings.source_first_backoff_seconds,
        )
        delay = settings.source_delay_seconds
        state = MeteredState(PostgresIngestionStateRepository(pool))

        async def check_updates() -> UpdateReport:
            return await check_for_updates(
                source,
                store,
                documents,
                delay_seconds=delay,
                concurrency=settings.update_check_concurrency,
            )

        async def take_queue() -> QueueReport:
            context = QueueContext(
                source, SplXmlParser(), store, documents, settings.failure_reason_max_chars
            )
            return await process_queue(
                queue, context, limit=settings.label_queue_batch, delay_seconds=delay
            )

        runner: IngestionRunner | None = None
        services: list[IngestionService] = []

        async def rebuild(new: RuntimeSettings) -> Callable[[], None]:
            # The service builds the S3 client, which can reach the network: keep it off the loop.
            service = await asyncio.to_thread(ingestion_service, settings, pool, new)

            def commit() -> None:
                services[:] = [service]
                if runner is not None:
                    runner.use_service(service)

            return commit

        config = await load_runtime_config(settings, pool, rebuild)
        runner = IngestionRunner(
            services[-1],
            documents,
            check_updates,
            take_queue,
            config,
            concurrency=settings.ingest_concurrency,
        )
        runner.observe = observe_ingest

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        if interrupted := await documents.reset_interrupted():
            # A crash left these half done; a pass now ingests them again.
            logger.info("documents reset after an interrupted pass", extra={"count": interrupted})
            await state.request(force=False)
        runner.start_schedule(timedelta(hours=settings.ingest_schedule_hours))
        serve(METRICS_PORT)
        logger.info("ingest worker started")
        try:
            await IngestWorker(
                runner, state, config.refresh, timedelta(seconds=settings.worker_tick_seconds)
            ).run(stop)
        finally:
            await runner.stop()
            await state.report("idle", None)
            await close_model_clients()
            logger.info("ingest worker stopped")


def main() -> None:
    configure_logging()
    asyncio.run(run(get_settings()))


if __name__ == "__main__":
    main()
