import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest

from app.application.corpus import (
    CorpusEntry,
    download_corpus,
    parse_manifest,
    parse_sources,
)
from app.domain.documents import Document, DocumentStatus
from app.domain.storage import label_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.test_document_file import FakeRepository

MANIFEST = """
{"source": "DailyMed", "pdf_url_template": "https://example.test/{source_id}",
 "label_url_template": "https://example.test/{source_id}.xml",
 "documents": [
  {"brand_name": "Alpha", "generic_name": "alphamab", "manufacturer": "M1", "source_id": "s1",
   "quick_start": true, "tags": {"class": "x"}},
  {"brand_name": "", "generic_name": "betanol", "manufacturer": "M2", "source_id": "s2",
   "quick_start": false, "tags": {}},
  {"brand_name": "Gamma", "generic_name": "gammazine", "manufacturer": "M3", "source_id": "s3",
   "quick_start": true, "tags": {}}
 ]}
"""


SPL = b'<?xml version="1.0"?><document xmlns="urn:hl7-org:v3"/>'


class FakeSource:
    def __init__(
        self, payloads: dict[str, bytes] | None = None, labels: dict[str, bytes] | None = None
    ) -> None:
        self.calls: list[str] = []
        self._payloads = payloads or {}
        self._labels = labels or {}

    def fetch_pdf(self, source_id: str) -> bytes:
        self.calls.append(source_id)
        if source_id == "broken":
            raise OSError("network down")
        return self._payloads.get(source_id, b"%PDF-1.7 " + source_id.encode())

    def fetch_label(self, source_id: str) -> bytes:
        self.calls.append(f"{source_id}.xml")
        return self._labels.get(source_id, SPL)


def run(
    entries: list[CorpusEntry], source: FakeSource, repo: FakeRepository, tmp_path: Path
) -> dict[str, int]:
    store = FileSystemDocumentStore(tmp_path)
    report = asyncio.run(download_corpus(entries, source, store, repo, delay_seconds=0))
    return {"downloaded": report.downloaded, "skipped": report.skipped, "failed": report.failed}


def test_parse_manifest_and_quick_mode_selects_quick_start_entries() -> None:
    entries = parse_manifest(MANIFEST, quick=True)

    assert [e.source_id for e in entries] == ["s1", "s3"]
    assert len(parse_manifest(MANIFEST, quick=False)) == 3


def test_download_stores_documents_and_a_second_run_downloads_nothing(tmp_path: Path) -> None:
    entries = parse_manifest(MANIFEST, quick=False)
    source, repo = FakeSource(), FakeRepository()

    assert run(entries, source, repo, tmp_path) == {"downloaded": 3, "skipped": 0, "failed": 0}
    stored = asyncio.run(repo.find_by_source_id("s2"))
    assert stored is not None
    assert stored.status is DocumentStatus.STORED
    assert stored.brand_name == ""
    assert stored.sha256 == hashlib.sha256(b"%PDF-1.7 s2").hexdigest()
    assert stored.storage_key == f"documents/{stored.id}/{stored.sha256}.pdf"
    assert FileSystemDocumentStore(tmp_path).exists(stored.storage_key)
    assert FileSystemDocumentStore(tmp_path).exists(label_key(stored.id))

    source.calls.clear()
    assert run(entries, source, repo, tmp_path) == {"downloaded": 0, "skipped": 3, "failed": 0}
    assert source.calls == []


def test_same_content_under_another_source_id_is_not_stored_twice(tmp_path: Path) -> None:
    entries = parse_manifest(MANIFEST, quick=False)
    same = b"%PDF-1.7 same"
    source = FakeSource({"s1": same, "s2": same, "s3": same})

    assert run(entries, source, FakeRepository(), tmp_path) == {
        "downloaded": 1,
        "skipped": 2,
        "failed": 0,
    }


def test_a_failed_download_is_counted_and_the_rest_continue(tmp_path: Path) -> None:
    entries = [
        CorpusEntry("Broken", "x", "M", "broken", quick_start=False),
        CorpusEntry("Ok", "y", "M", "ok", quick_start=False),
    ]

    assert run(entries, FakeSource(), FakeRepository(), tmp_path) == {
        "downloaded": 1,
        "skipped": 0,
        "failed": 1,
    }


def test_non_pdf_content_is_a_failure(tmp_path: Path) -> None:
    entries = [CorpusEntry("Html", "x", "M", "html", quick_start=False)]
    source = FakeSource({"html": b"<html>error page</html>"})

    assert run(entries, source, FakeRepository(), tmp_path)["failed"] == 1


def test_non_spl_label_content_is_a_failure_and_nothing_is_stored(tmp_path: Path) -> None:
    entries = [CorpusEntry("Html", "x", "M", "html", quick_start=False)]
    source = FakeSource(labels={"html": b"<html>error page</html>"})
    repo = FakeRepository()

    assert run(entries, source, repo, tmp_path)["failed"] == 1
    assert asyncio.run(repo.find_by_source_id("html")) is None


def known_document() -> Document:
    data = b"%PDF-1.7 s1"
    doc_id = uuid.uuid4()
    sha = hashlib.sha256(data).hexdigest()
    return Document(
        id=doc_id,
        brand_name="Alpha",
        generic_name="alphamab",
        manufacturer="M1",
        source_id="s1",
        storage_key=f"documents/{doc_id}/{sha}.pdf",
        sha256=sha,
        size_bytes=len(data),
        status=DocumentStatus.STORED,
    )


ENTRY = [CorpusEntry("Alpha", "alphamab", "M1", "s1", quick_start=True)]


def test_missing_object_for_a_known_document_is_stored_again(tmp_path: Path) -> None:
    known = known_document()

    assert run(ENTRY, FakeSource(), FakeRepository(known), tmp_path)["downloaded"] == 1
    assert FileSystemDocumentStore(tmp_path).exists(known.storage_key)
    assert FileSystemDocumentStore(tmp_path).exists(label_key(known.id))


def test_a_known_document_without_its_label_gets_only_the_label(tmp_path: Path) -> None:
    known = known_document()
    FileSystemDocumentStore(tmp_path).put(known.storage_key, b"%PDF-1.7 s1", "application/pdf")
    source = FakeSource()

    assert run(ENTRY, source, FakeRepository(known), tmp_path)["downloaded"] == 1
    assert source.calls == ["s1.xml"]
    assert FileSystemDocumentStore(tmp_path).exists(label_key(known.id))


@pytest.mark.parametrize("bad", ['{"documents": [{"source_id": "x"}]}', "[]"])
def test_invalid_manifest_raises(bad: str) -> None:
    with pytest.raises(ValueError, match="manifest"):
        parse_manifest(bad, quick=False)


def test_parse_sources_reads_both_url_templates() -> None:
    assert parse_sources(MANIFEST) == (
        "https://example.test/{source_id}",
        "https://example.test/{source_id}.xml",
    )


def test_a_manifest_without_the_label_template_raises() -> None:
    with pytest.raises(ValueError, match="manifest"):
        parse_sources('{"pdf_url_template": "https://example.test/{source_id}"}')
