"""LabelSource adapter for DailyMed: GET the label PDF by set ID."""

import urllib.request
from urllib.parse import quote, urlparse

USER_AGENT = "label-corpus-downloader/1.0"
MAX_BYTES = 50 * 1024 * 1024


class DailyMedClient:
    def __init__(self, url_template: str, timeout_seconds: float = 60) -> None:
        if urlparse(url_template).scheme != "https":
            raise ValueError("The DailyMed URL template must use https")
        self._template = url_template
        self._timeout = timeout_seconds

    def fetch_pdf(self, source_id: str) -> bytes:
        url = self._template.format(source_id=quote(source_id, safe=""))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310  # https only, checked above
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310  # nosec B310
            data: bytes = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"{source_id}: PDF is larger than {MAX_BYTES} bytes")
        return data
