"""Fill the library from the manifest. Usage: python -m app.worker.corpus_init

Runs once per stack start as a one-shot job. It puts the manifest labels that the library
does not have into the label queue and asks the ingest worker for a pass; the worker
downloads and ingests them. A label that failed before is queued again."""

import asyncio
from pathlib import Path

from app.application.corpus import CorpusEntry, parse_manifest
from app.application.label_queue import queue_manifest
from app.bootstrap import open_database
from app.config import get_settings
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.ingestion_state_repository import PostgresIngestionStateRepository
from app.infrastructure.label_queue_repository import PostgresLabelQueueRepository
from app.infrastructure.logging import configure_logging

MANIFEST = Path("/corpus/manifest.json")


async def fill(entries: list[CorpusEntry]) -> int:
    async with open_database(get_settings()) as pool:
        return await queue_manifest(
            entries,
            PostgresLabelQueueRepository(pool),
            PostgresDocumentRepository(pool),
            PostgresIngestionStateRepository(pool),
        )


def main() -> None:
    configure_logging()
    entries = parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    queued = asyncio.run(fill(entries))
    if queued:
        print(f"{queued} manifest labels queued; the ingest worker downloads and ingests them")
    else:
        print("every manifest label is in the library or in the queue; nothing to do")


if __name__ == "__main__":
    main()
