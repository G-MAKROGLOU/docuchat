"""Ingest stored labels into chunks. Usage: python -m app.ingest --quick|--all"""

import argparse
import asyncio
import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from app.application.ingestion import IngestionService, IngestResult, public_reason
from app.application.ingestion_runner import INGEST_CONCURRENCY, ChunkingTracker, ingest_each
from app.config import Settings, get_settings
from app.domain.documents import Document
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.database import build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.migrations import apply_migrations
from app.infrastructure.models import ModelFactory
from app.infrastructure.runtime_settings_repository import PostgresRuntimeSettingsRepository
from app.runtime_config import RuntimeConfig
from app.wiring import default_runtime_settings, ingestion_service, runtime_settings

DEFAULT_MANIFEST = Path("/corpus/manifest.json")
logger = logging.getLogger(__name__)


async def ingest_documents(
    documents: list[Document],
    service: IngestionService,
    tracker: ChunkingTracker,
    *,
    force: bool,
    concurrency: int = INGEST_CONCURRENCY,
) -> list[tuple[Document, IngestResult]]:
    """The same rules as a worker pass: a stale index (chunk settings changed) is embedded
    again, and the marker is cleared only when every document succeeded."""
    force = force or await tracker.stale()
    results = await ingest_all(documents, service, force=force, concurrency=concurrency)
    if force and not any(r.error for _, r in results):
        await tracker.mark_embedded()
    return results


async def ingest_all(
    documents: list[Document],
    service: IngestionService,
    *,
    force: bool,
    concurrency: int = INGEST_CONCURRENCY,
) -> list[tuple[Document, IngestResult]]:
    """Several documents at the same time; a document that raises is reported as failed."""

    async def ingest(document: Document) -> tuple[Document, IngestResult]:
        try:
            return document, await service.ingest(document, force=force)
        except Exception as exc:
            logger.exception("ingestion failed", extra={"document_id": str(document.id)})
            return document, IngestResult(document.id, error=public_reason(exc))

    return await ingest_each(documents, ingest, concurrency=concurrency)


async def run(
    settings: Settings, quick_ids: set[str] | None, *, force: bool
) -> list[tuple[Document, IngestResult]]:
    async with build_pool(settings) as pool:
        documents = await PostgresDocumentRepository(pool).list_all()
        if quick_ids is not None:
            documents = [d for d in documents if d.source_id in quick_ids]
        runtime = await runtime_settings(settings, pool)

        async def keep(new: RuntimeSettings) -> Callable[[], None]:
            return lambda: None

        tracker = RuntimeConfig(
            PostgresRuntimeSettingsRepository(pool), default_runtime_settings(settings), keep
        )
        await tracker.load()
        service = ingestion_service(settings, pool, runtime)
        # A quick run covers only some labels, so it never clears the marker.
        if quick_ids is not None:
            return await ingest_all(documents, service, force=force)
        return await ingest_documents(documents, service, tracker, force=force)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quick", action="store_true", help="only the quick_start labels")
    mode.add_argument("--all", action="store_true", help="every stored label")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--force", action="store_true", help="ingest again even when already ingested"
    )
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    apply_migrations(settings.database_url.get_secret_value())
    started = time.perf_counter()
    quick_ids = (
        {
            d["source_id"]
            for d in json.loads(args.manifest.read_text(encoding="utf-8"))["documents"]
            if d["quick_start"]
        }
        if args.quick
        else None
    )
    results = asyncio.run(run(settings, quick_ids, force=args.force))
    seconds = time.perf_counter() - started

    for document, result in results:
        state = (
            "skipped"
            if result.skipped
            else ("FAILED " + str(result.error) if result.error else "ok")
        )
        name = document.brand_name or document.generic_name
        print(f"  {name:<28} chunks={result.chunks:<5} tokens={result.tokens:<7} {state}")
    tokens = sum(r.tokens for _, r in results)
    price = ModelFactory(settings).embedding_price_per_token()
    cost = f"{tokens * price:.6f} USD" if price is not None else "unknown (price lookup failed)"
    print(
        f"documents: {len(results)}  ingested: {sum(1 for _, r in results if r.chunks)}  "
        f"skipped: {sum(1 for _, r in results if r.skipped)}  "
        f"failed: {sum(1 for _, r in results if r.error)}  "
        f"chunks: {sum(r.chunks for _, r in results)}  tokens: {tokens}  cost: {cost}  "
        f"seconds: {seconds:.1f}"
    )
    return 1 if any(r.error for _, r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
