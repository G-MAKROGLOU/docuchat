"""DocumentParser adapter with PyMuPDF (AGPL-3.0 or a commercial license)."""

from dataclasses import dataclass

import pymupdf

from app.domain.entities import PdfLine

_BOLD_FLAG = 1 << 4
# Parts whose vertical centers are this close (points) sit on one row.
_ROW_TOLERANCE = 3.0


@dataclass(frozen=True, slots=True)
class _Part:
    x0: float
    y_center: float
    text: str
    bold: bool


class PyMuPdfParser:
    """Lines in page position order: DailyMed PDFs store list items after the other blocks.
    The pages are single-column, so a sort by position and a join per row restore the order."""

    def extract_lines(self, data: bytes) -> tuple[int, list[PdfLine]]:
        lines: list[PdfLine] = []
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for index, page in enumerate(doc):
                lines.extend(_rows(index + 1, _parts(page)))
            return doc.page_count, lines


def _parts(page: pymupdf.Page) -> list[_Part]:
    parts: list[_Part] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0, y0, _, y1 = line["bbox"]
            parts.append(
                _Part(
                    x0=x0,
                    y_center=(y0 + y1) / 2,
                    text=" ".join("".join(s["text"] for s in line["spans"]).split()),
                    bold=all(s["flags"] & _BOLD_FLAG or "Bold" in s["font"] for s in spans),
                )
            )
    return sorted(parts, key=lambda p: (p.y_center, p.x0))


def _rows(page: int, parts: list[_Part]) -> list[PdfLine]:
    rows: list[list[_Part]] = []
    for part in parts:
        if rows and abs(part.y_center - rows[-1][0].y_center) <= _ROW_TOLERANCE:
            rows[-1].append(part)
        else:
            rows.append([part])
    lines = []
    for row in rows:
        ordered = sorted(row, key=lambda p: p.x0)
        # Bullets and other symbol-only parts do not decide whether the row is bold.
        wordy = [p for p in ordered if any(c.isalnum() for c in p.text)]
        bold = bool(wordy) and all(p.bold for p in wordy)
        lines.append(PdfLine(page, " ".join(p.text for p in ordered), bold))
    return lines
