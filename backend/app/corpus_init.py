"""Fill the library from the manifest: download, then ingest. Usage: python -m app.corpus_init

Runs once per stack start as a one-shot job. It does nothing when every manifest label is
already in the library, so a later start retries only labels that failed before."""

import asyncio
import sys

from app import corpus_download, ingest
from app.application.corpus import parse_manifest
from app.config import get_settings
from app.infrastructure.database import build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.logging import configure_logging
from app.infrastructure.migrations import apply_migrations


def missing_labels() -> int:
    """How many manifest labels the library does not have yet."""
    settings = get_settings()
    apply_migrations(settings.database_url.get_secret_value())
    manifest = corpus_download.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    wanted = {e.source_id for e in parse_manifest(manifest, quick=False)}

    async def stored() -> set[str]:
        async with build_pool(settings) as pool:
            return {d.source_id for d in await PostgresDocumentRepository(pool).list_all()}

    return len(wanted - asyncio.run(stored()))


def main() -> int:
    configure_logging()
    missing = missing_labels()
    if not missing:
        print("every manifest label is in the library; nothing to do")
        return 0
    print(f"{missing} manifest labels are missing; downloading and ingesting them")
    # A failed download must not stop the ingest of the labels that did arrive.
    downloaded = corpus_download.main(["--all"])
    ingested = ingest.main(["--all"])
    return 1 if downloaded or ingested else 0


if __name__ == "__main__":
    sys.exit(main())
