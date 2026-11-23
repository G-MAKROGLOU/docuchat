"""The label queue: add a label after the catalogue confirms it, and take the next labels
into the corpus on each ingestion pass."""

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.application.corpus import SPL_NAMESPACE, CorpusEntry, download_corpus
from app.application.ingestion import public_reason
from app.domain.documents import DocumentRepository, LabelSource
from app.domain.label_queue import (
    CatalogLabel,
    LabelCatalog,
    LabelMetadataReader,
    LabelQueueRepository,
    QueueEntry,
    QueueStatus,
)
from app.domain.storage import DocumentStore

logger = logging.getLogger(__name__)

LABELS_PER_PASS = 50
SET_ID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


class LabelNotFoundError(Exception):
    """The catalogue does not know the label."""


class LabelKnownError(Exception):
    """The label is in the corpus or in the queue."""


async def add_label(
    catalog: LabelCatalog,
    queue: LabelQueueRepository,
    documents: DocumentRepository,
    set_id: str,
) -> CatalogLabel:
    set_id = set_id.strip().lower()
    if not SET_ID.match(set_id):
        raise LabelNotFoundError(set_id)
    label = await asyncio.to_thread(catalog.lookup, set_id)
    if label is None:
        raise LabelNotFoundError(set_id)
    if await documents.find_by_source_id(set_id) is not None:
        raise LabelKnownError(set_id)
    if not await queue.add(set_id, label.title):
        raise LabelKnownError(set_id)
    return label


class PassRequests(Protocol):
    async def request(self, *, force: bool) -> None: ...


async def queue_manifest(
    entries: Sequence[CorpusEntry],
    queue: LabelQueueRepository,
    documents: DocumentRepository,
    passes: PassRequests,
) -> int:
    """Queue the manifest labels that are not in the library, then ask the worker for a pass.
    A failed entry is queued again. Returns the number queued."""
    stored = await documents.known_source_ids([e.source_id for e in entries])
    queued = 0
    for entry in entries:
        if entry.source_id not in stored:
            title = entry.brand_name or entry.generic_name
            queued += await queue.add(entry.source_id, title)
    if queued:
        await passes.request(force=False)
    return queued


@dataclass(slots=True)
class QueueReport:
    added: int = 0
    failed: int = 0


class _Prefetched:
    """A LabelSource that serves a label that is already fetched, so it is not fetched twice."""

    def __init__(self, source: LabelSource, set_id: str, label: bytes) -> None:
        self._source = source
        self._set_id = set_id
        self._label = label

    def fetch_pdf(self, source_id: str) -> bytes:
        return self._source.fetch_pdf(source_id)

    def fetch_label(self, source_id: str) -> bytes:
        return self._label if source_id == self._set_id else self._source.fetch_label(source_id)


@dataclass(frozen=True, slots=True)
class QueueContext:
    source: LabelSource
    reader: LabelMetadataReader
    store: DocumentStore
    documents: DocumentRepository


async def process_queue(
    queue: LabelQueueRepository,
    context: QueueContext,
    *,
    limit: int = LABELS_PER_PASS,
    delay_seconds: float = 0.3,
) -> QueueReport:
    report = QueueReport()
    for entry in await queue.next_queued(limit):
        reason = await _take(entry, context, delay_seconds)
        status = QueueStatus.FAILED if reason else QueueStatus.ADDED
        await queue.mark(entry.set_id, status, reason)
        if reason:
            report.failed += 1
        else:
            report.added += 1
    return report


async def _take(entry: QueueEntry, context: QueueContext, delay_seconds: float) -> str | None:
    """Download one queued label. The failure reason, or None when the label is in the corpus."""
    try:
        label = await asyncio.to_thread(context.source.fetch_label, entry.set_id)
        await asyncio.sleep(delay_seconds)  # polite pacing for the public source
        if SPL_NAMESPACE not in label[:4096]:
            return "The response is not an SPL document."
        names = context.reader.metadata(label)
        if not (names.brand_name or names.generic_name):
            return "The label has no product name."
        corpus_entry = CorpusEntry(
            brand_name=names.brand_name,
            generic_name=names.generic_name,
            manufacturer=names.manufacturer,
            source_id=entry.set_id,
        )
        download = await download_corpus(
            [corpus_entry],
            _Prefetched(context.source, entry.set_id, label),
            context.store,
            context.documents,
            delay_seconds=delay_seconds,
        )
        if await context.documents.find_by_source_id(entry.set_id) is None:
            if download.skipped:
                return "A label with the same PDF is already in the corpus."
            return "The download failed. See the API log."
    except Exception as exc:
        logger.exception("label queue entry failed", extra={"source_id": entry.set_id})
        return public_reason(exc)
    return None
