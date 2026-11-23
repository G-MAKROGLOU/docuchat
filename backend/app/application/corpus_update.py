"""Update check: a stored label whose source SPL XML changed is stored again and set back to
"stored", so the next ingestion pass reads it. Known documents only."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from uuid import UUID

from app.application.corpus import PDF_MAGIC, SNIFF_BYTES, SPL_NAMESPACE
from app.domain.documents import Document, DocumentRepository, LabelSource
from app.domain.storage import DocumentStore, ObjectNotFoundError, document_key, label_key

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UpdateReport:
    checked: int = 0
    updated: int = 0
    failed: int = 0


def _stored_label(store: DocumentStore, document_id: UUID) -> bytes | None:
    try:
        return b"".join(store.get_stream(label_key(document_id)))
    except ObjectNotFoundError:
        return None


async def check_for_updates(
    source: LabelSource,
    store: DocumentStore,
    repository: DocumentRepository,
    *,
    delay_seconds: float,
    concurrency: int,
) -> UpdateReport:
    """concurrency labels are checked at the same time; each pauses between its own requests."""
    report = UpdateReport()
    slots = asyncio.Semaphore(concurrency)

    async def check(document: Document) -> None:
        async with slots:
            report.checked += 1
            try:
                if await _check_one(source, store, repository, document, delay_seconds):
                    report.updated += 1
                    logger.info("label updated", extra={"source_id": document.source_id})
            except Exception:
                report.failed += 1
                logger.exception("update check failed", extra={"source_id": document.source_id})

    await asyncio.gather(*(check(d) for d in await repository.list_all()))
    return report


async def _check_one(
    source: LabelSource,
    store: DocumentStore,
    repository: DocumentRepository,
    document: Document,
    delay_seconds: float,
) -> bool:
    """True when the label changed and was stored again."""
    label = await asyncio.to_thread(source.fetch_label, document.source_id)
    await asyncio.sleep(delay_seconds)  # polite pacing for the public source
    if SPL_NAMESPACE not in label[:SNIFF_BYTES]:
        raise ValueError(f"{document.source_id}: response is not an SPL document")
    if label == await asyncio.to_thread(_stored_label, store, document.id):
        return False

    pdf = await asyncio.to_thread(source.fetch_pdf, document.source_id)
    await asyncio.sleep(delay_seconds)
    if not pdf.startswith(PDF_MAGIC):
        raise ValueError(f"{document.source_id}: response is not a PDF")
    sha256 = hashlib.sha256(pdf).hexdigest()
    key = document_key(document.id, sha256)
    # Objects first, row second: a row never points to a missing object.
    await asyncio.to_thread(store.put, key, pdf, "application/pdf")
    await asyncio.to_thread(store.put, label_key(document.id), label, "application/xml")
    await repository.replace_content(document.id, key, sha256, len(pdf))
    if key != document.storage_key:
        await asyncio.to_thread(store.delete, document.storage_key)
    return True
