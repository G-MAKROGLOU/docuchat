"""Ingest stored labels into chunks. Usage: python -m app.ingest --quick|--all"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from app.application.ingestion import IngestionService, IngestResult
from app.config import Settings, get_settings
from app.domain.documents import Document
from app.infrastructure.chunk_repository import PostgresChunkRepository
from app.infrastructure.database import build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.migrations import apply_migrations
from app.infrastructure.models import ModelFactory
from app.infrastructure.pdf_parser import PyMuPdfParser
from app.infrastructure.storage import build_document_store
from app.infrastructure.text_splitting import SentenceTokenSplitter, TiktokenCounter

DEFAULT_MANIFEST = Path("/corpus/manifest.json")


async def run(
    settings: Settings, quick_ids: set[str] | None, *, force: bool
) -> list[tuple[Document, IngestResult]]:
    async with build_pool(settings.database_url.get_secret_value()) as pool:
        repository = PostgresDocumentRepository(pool)
        documents = await repository.list_all()
        if quick_ids is not None:
            documents = [d for d in documents if d.source_id in quick_ids]
        service = IngestionService(
            store=build_document_store(settings),
            documents=repository,
            chunks=PostgresChunkRepository(pool),
            parser=PyMuPdfParser(),
            splitter=SentenceTokenSplitter(chunk_tokens=500, overlap_tokens=50),
            counter=TiktokenCounter(),
            embedder=ModelFactory(settings).embedder(),
            embedding_model=settings.embedding_model,
            embedding_prefix=settings.embedding_prefix,
        )
        return [(d, await service.ingest(d, force=force)) for d in documents]


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
