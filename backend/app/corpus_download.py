"""Download the corpus labels. Usage: python -m app.corpus_download --quick|--all"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from app.application.corpus import CorpusEntry, DownloadReport, download_corpus, parse_manifest
from app.config import Settings, get_settings
from app.infrastructure.dailymed import DailyMedClient
from app.infrastructure.database import build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.migrations import apply_migrations
from app.infrastructure.storage import build_document_store

DEFAULT_MANIFEST = Path("/corpus/manifest.json")


async def run(
    settings: Settings, entries: list[CorpusEntry], source: DailyMedClient
) -> DownloadReport:
    async with build_pool(settings) as pool:
        return await download_corpus(
            entries, source, build_document_store(settings), PostgresDocumentRepository(pool)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quick", action="store_true", help="only the quick_start labels")
    mode.add_argument("--all", action="store_true", help="every label in the manifest")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    apply_migrations(settings.database_url.get_secret_value())
    text = args.manifest.read_text(encoding="utf-8")
    entries = parse_manifest(text, quick=args.quick)
    source = DailyMedClient(json.loads(text)["pdf_url_template"])

    started = time.perf_counter()
    report = asyncio.run(run(settings, entries, source))
    print(
        f"labels: {len(entries)}  downloaded: {report.downloaded}  skipped: {report.skipped}  "
        f"failed: {report.failed}  bytes: {report.bytes_downloaded}  "
        f"seconds: {time.perf_counter() - started:.1f}"
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
