"""LabelSource adapter for DailyMed: GET the label PDF and the SPL XML by set ID."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from app.domain.label_queue import CatalogLabel
from app.infrastructure.http_retry import RETRY_STATUSES

DEFAULT_PDF_TEMPLATE = "https://dailymed.nlm.nih.gov/dailymed/downloadpdffile.cfm?setId={source_id}"
DEFAULT_LABEL_TEMPLATE = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{source_id}.xml"
DEFAULT_CATALOG_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
USER_AGENT = "label-corpus-downloader/1.0"


def _retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRY_STATUSES
    return isinstance(error, urllib.error.URLError | TimeoutError | ConnectionError)


class DailyMedClient:
    def __init__(  # noqa: PLR0913  # two templates, four request limits, two test seams
        self,
        pdf_url_template: str,
        label_url_template: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
        attempts: int,
        first_backoff_seconds: float,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        for template in (pdf_url_template, label_url_template):
            if urlparse(template).scheme != "https":
                raise ValueError("The DailyMed URL templates must use https")
        self._pdf_template = pdf_url_template
        self._label_template = label_url_template
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        # Tries per request, and the wait before each retry (doubled each time).
        self._attempts = attempts
        self._first_backoff = first_backoff_seconds
        self._open = opener
        self._sleep = sleep

    def fetch_pdf(self, source_id: str) -> bytes:
        return self._get(self._pdf_template, source_id)

    def fetch_label(self, source_id: str) -> bytes:
        return self._get(self._label_template, source_id)

    def _get(self, template: str, source_id: str) -> bytes:
        url = template.format(source_id=quote(source_id, safe=""))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310  # https only, checked above
        # Runs in a worker thread, so the blocking sleep between tries does not stop the loop.
        wait = self._first_backoff
        for attempt in range(1, self._attempts + 1):
            try:
                with self._open(request, timeout=self._timeout) as response:
                    data: bytes = response.read(self._max_bytes + 1)
                break
            except Exception as exc:
                if attempt == self._attempts or not _retryable(exc):
                    raise
                self._sleep(wait)
                wait *= 2
        if len(data) > self._max_bytes:
            raise ValueError(f"{source_id}: response is larger than {self._max_bytes} bytes")
        return data


class DailyMedCatalog:
    """LabelCatalog adapter: the DailyMed SPL list, by set ID or drug name."""

    def __init__(
        self, *, timeout_seconds: float, max_bytes: int, url: str = DEFAULT_CATALOG_URL
    ) -> None:
        if urlparse(url).scheme != "https":
            raise ValueError("The DailyMed catalog URL must use https")
        self._url = url
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    def lookup(self, set_id: str) -> CatalogLabel | None:
        found = self._list({"setid": set_id, "pagesize": 1})
        return found[0] if found else None

    def search(self, drug_name: str, limit: int) -> list[CatalogLabel]:
        return self._list({"drug_name": drug_name, "pagesize": limit})

    def _list(self, query: dict[str, str | int]) -> list[CatalogLabel]:
        request = urllib.request.Request(  # noqa: S310  # https only, checked above
            f"{self._url}?{urlencode(query)}", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310  # nosec B310
            body = json.loads(response.read(self._max_bytes))
        return [
            CatalogLabel(
                set_id=item["setid"],
                title=item["title"],
                version=int(item["spl_version"]),
                published=item["published_date"],
            )
            for item in body["data"]
        ]
