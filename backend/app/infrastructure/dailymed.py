"""LabelSource adapter for DailyMed: GET the label PDF and the SPL XML by set ID."""

import urllib.request
from urllib.parse import quote, urlparse

USER_AGENT = "label-corpus-downloader/1.0"
MAX_BYTES = 50 * 1024 * 1024


class DailyMedClient:
    def __init__(
        self, pdf_url_template: str, label_url_template: str, timeout_seconds: float = 60
    ) -> None:
        for template in (pdf_url_template, label_url_template):
            if urlparse(template).scheme != "https":
                raise ValueError("The DailyMed URL templates must use https")
        self._pdf_template = pdf_url_template
        self._label_template = label_url_template
        self._timeout = timeout_seconds

    def fetch_pdf(self, source_id: str) -> bytes:
        return self._get(self._pdf_template, source_id)

    def fetch_label(self, source_id: str) -> bytes:
        return self._get(self._label_template, source_id)

    def _get(self, template: str, source_id: str) -> bytes:
        url = template.format(source_id=quote(source_id, safe=""))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310  # https only, checked above
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310  # nosec B310
            data: bytes = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"{source_id}: response is larger than {MAX_BYTES} bytes")
        return data
