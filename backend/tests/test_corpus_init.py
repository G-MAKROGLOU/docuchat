import pytest

from app import corpus_download, corpus_init, ingest


class Calls:
    def __init__(self, download_code: int = 0, ingest_code: int = 0) -> None:
        self.download_code = download_code
        self.ingest_code = ingest_code
        self.made: list[tuple[str, list[str] | None]] = []

    def download(self, argv: list[str] | None = None) -> int:
        self.made.append(("download", argv))
        return self.download_code

    def ingest(self, argv: list[str] | None = None) -> int:
        self.made.append(("ingest", argv))
        return self.ingest_code


def patch(monkeypatch: pytest.MonkeyPatch, missing: int, calls: Calls) -> None:
    monkeypatch.setattr(corpus_init, "missing_labels", lambda: missing)
    monkeypatch.setattr(corpus_download, "main", calls.download)
    monkeypatch.setattr(ingest, "main", calls.ingest)


def test_an_empty_library_downloads_and_ingests_every_manifest_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = Calls()
    patch(monkeypatch, 50, calls)

    assert corpus_init.main() == 0
    assert calls.made == [("download", ["--all"]), ("ingest", ["--all"])]


def test_a_library_with_every_manifest_label_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    patch(monkeypatch, 0, calls)

    assert corpus_init.main() == 0
    assert calls.made == []


def test_failed_downloads_still_ingest_the_others_and_fail_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = Calls(download_code=1)
    patch(monkeypatch, 3, calls)

    assert corpus_init.main() == 1
    assert [name for name, _ in calls.made] == ["download", "ingest"]


def test_a_failed_ingest_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    patch(monkeypatch, 2, Calls(ingest_code=1))

    assert corpus_init.main() == 1
