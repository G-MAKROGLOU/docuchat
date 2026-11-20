"""Corpus download: manifest entries to stored PDFs and document rows. Idempotent by source ID."""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.documents import Document, DocumentRepository, DocumentStatus, LabelSource
from app.domain.storage import DocumentStore, document_key

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    brand_name: str
    generic_name: str
    manufacturer: str
    source_id: str
    quick_start: bool


@dataclass(slots=True)
class DownloadReport:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_downloaded: int = 0


def parse_manifest(text: str, *, quick: bool) -> list[CorpusEntry]:
    try:
        raw = json.loads(text)["documents"]
        entries = [
            CorpusEntry(
                brand_name=item["brand_name"],
                generic_name=item["generic_name"],
                manufacturer=item["manufacturer"],
                source_id=item["source_id"],
                quick_start=bool(item["quick_start"]),
            )
            for item in raw
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid corpus manifest: {exc!r}") from exc
    return [e for e in entries if e.quick_start] if quick else entries


async def download_corpus(
    entries: Sequence[CorpusEntry],
    source: LabelSource,
    store: DocumentStore,
    repository: DocumentRepository,
    *,
    delay_seconds: float = 0.3,
) -> DownloadReport:
    return await _Downloader(source, store, repository, delay_seconds).run(entries)


@dataclass(frozen=True, slots=True)
class _Downloader:
    source: LabelSource
    store: DocumentStore
    repository: DocumentRepository
    delay_seconds: float

    async def run(self, entries: Sequence[CorpusEntry]) -> DownloadReport:
        report = DownloadReport()
        for entry in entries:
            try:
                await self._one(entry, report)
            except Exception:
                report.failed += 1
                logger.exception("corpus download failed", extra={"source_id": entry.source_id})
        return report

    async def _one(self, entry: CorpusEntry, report: DownloadReport) -> None:
        known = await self.repository.find_by_source_id(entry.source_id)
        if known is not None:
            stored: bool = await asyncio.to_thread(self.store.exists, known.storage_key)
            if stored:
                report.skipped += 1
                return

        data = await asyncio.to_thread(self.source.fetch_pdf, entry.source_id)
        await asyncio.sleep(self.delay_seconds)  # polite pacing for the public source
        if not data.startswith(PDF_MAGIC):
            raise ValueError(f"{entry.source_id}: response is not a PDF")
        sha256 = hashlib.sha256(data).hexdigest()

        if known:
            # The row exists but the object is missing: store it again under the known key.
            if known.sha256 != sha256:
                raise ValueError(f"{entry.source_id}: label changed since it was stored")
            await asyncio.to_thread(self.store.put, known.storage_key, data, "application/pdf")
        elif await self.repository.find_by_sha256(sha256):
            logger.info("same PDF already stored", extra={"source_id": entry.source_id})
            report.skipped += 1
            return
        else:
            document_id = uuid.uuid4()
            document = Document(
                id=document_id,
                brand_name=entry.brand_name,
                generic_name=entry.generic_name,
                manufacturer=entry.manufacturer,
                source_id=entry.source_id,
                storage_key=document_key(document_id, sha256),
                sha256=sha256,
                size_bytes=len(data),
                status=DocumentStatus.STORED,
            )
            # Object first, row second: a row never points to a missing object.
            await asyncio.to_thread(self.store.put, document.storage_key, data, "application/pdf")
            await self.repository.add(document)
        report.downloaded += 1
        report.bytes_downloaded += len(data)
