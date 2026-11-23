import asyncio
import hashlib
from pathlib import Path

import pytest

from app.application.corpus import (
    CorpusEntry,
    download_corpus,
    parse_manifest,
)
from app.domain.documents import Document, DocumentStatus
from app.domain.storage import label_key
from app.infrastructure.storage import FileSystemDocumentStore
from tests.support.factories import make_document
from tests.support.fakes_ingestion import FakeDocumentRepository, FakeSource

MANIFEST = """
{"source": "DailyMed", "pdf_url_template": "https://example.test/{source_id}",
 "label_url_template": "https://example.test/{source_id}.xml",
 "documents": [
  {"brand_name": "Alpha", "generic_name": "alphamab", "manufacturer": "M1", "source_id": "s1",
   "tags": {"class": "x"}},
  {"brand_name": "", "generic_name": "betanol", "manufacturer": "M2", "source_id": "s2",
   "tags": {}},
  {"brand_name": "Gamma", "generic_name": "gammazine", "manufacturer": "M3", "source_id": "s3",
   "tags": {}}
 ]}
"""


def run(
    entries: list[CorpusEntry], source: FakeSource, repo: FakeDocumentRepository, tmp_path: Path
) -> dict[str, int]:
    store = FileSystemDocumentStore(tmp_path)
    report = asyncio.run(download_corpus(entries, source, store, repo, delay_seconds=0))
    return {"downloaded": report.downloaded, "skipped": report.skipped, "failed": report.failed}


def test_parse_manifest_reads_every_entry() -> None:
    assert [e.source_id for e in parse_manifest(MANIFEST)] == ["s1", "s2", "s3"]


def test_download_stores_documents_and_a_second_run_downloads_nothing(tmp_path: Path) -> None:
    entries = parse_manifest(MANIFEST)
    source, repo = FakeSource(), FakeDocumentRepository()

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
    entries = parse_manifest(MANIFEST)
    same = b"%PDF-1.7 same"
    source = FakeSource({"s1": same, "s2": same, "s3": same})

    assert run(entries, source, FakeDocumentRepository(), tmp_path) == {
        "downloaded": 1,
        "skipped": 2,
        "failed": 0,
    }


def test_a_failed_download_is_counted_and_the_rest_continue(tmp_path: Path) -> None:
    entries = [
        CorpusEntry("Broken", "x", "M", "broken"),
        CorpusEntry("Ok", "y", "M", "ok"),
    ]

    assert run(entries, FakeSource(), FakeDocumentRepository(), tmp_path) == {
        "downloaded": 1,
        "skipped": 0,
        "failed": 1,
    }


def test_non_pdf_content_is_a_failure(tmp_path: Path) -> None:
    entries = [CorpusEntry("Html", "x", "M", "html")]
    source = FakeSource({"html": b"<html>error page</html>"})

    assert run(entries, source, FakeDocumentRepository(), tmp_path)["failed"] == 1


def test_non_spl_label_content_is_a_failure_and_nothing_is_stored(tmp_path: Path) -> None:
    entries = [CorpusEntry("Html", "x", "M", "html")]
    source = FakeSource(labels={"html": b"<html>error page</html>"})
    repo = FakeDocumentRepository()

    assert run(entries, source, repo, tmp_path)["failed"] == 1
    assert asyncio.run(repo.find_by_source_id("html")) is None


def known_document() -> Document:
    data = b"%PDF-1.7 s1"
    sha = hashlib.sha256(data).hexdigest()
    return make_document(
        "Alpha", "alphamab", manufacturer="M1", source_id="s1", sha=sha, size_bytes=len(data)
    )


ENTRY = [CorpusEntry("Alpha", "alphamab", "M1", "s1")]


def test_missing_object_for_a_known_document_is_stored_again(tmp_path: Path) -> None:
    known = known_document()

    assert run(ENTRY, FakeSource(), FakeDocumentRepository(known), tmp_path)["downloaded"] == 1
    assert FileSystemDocumentStore(tmp_path).exists(known.storage_key)
    assert FileSystemDocumentStore(tmp_path).exists(label_key(known.id))


def test_a_known_document_without_its_label_gets_only_the_label(tmp_path: Path) -> None:
    known = known_document()
    FileSystemDocumentStore(tmp_path).put(known.storage_key, b"%PDF-1.7 s1", "application/pdf")
    source = FakeSource()

    assert run(ENTRY, source, FakeDocumentRepository(known), tmp_path)["downloaded"] == 1
    assert source.calls == ["s1.xml"]
    assert FileSystemDocumentStore(tmp_path).exists(label_key(known.id))


@pytest.mark.parametrize("bad", ['{"documents": [{"source_id": "x"}]}', "[]"])
def test_invalid_manifest_raises(bad: str) -> None:
    with pytest.raises(ValueError, match="manifest"):
        parse_manifest(bad)
