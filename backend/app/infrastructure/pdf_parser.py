"""DocumentParser adapter with PyMuPDF (AGPL-3.0 or a commercial license)."""

from dataclasses import dataclass

import pymupdf

# Parts whose vertical centers are this close (points) sit on one row.
_ROW_TOLERANCE = 3.0


@dataclass(frozen=True, slots=True)
class _Part:
    x0: float
    y_center: float
    text: str


class PyMuPdfParser:
    """Page texts in position order: DailyMed PDFs store list items after the other blocks.
    The pages are single-column, so a sort by position and a join per row restore the order."""

    def page_texts(self, data: bytes) -> list[str]:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return ["\n".join(_rows(_parts(page))) for page in doc]


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
                )
            )
    return sorted(parts, key=lambda p: (p.y_center, p.x0))


def _rows(parts: list[_Part]) -> list[str]:
    rows: list[list[_Part]] = []
    for part in parts:
        if rows and abs(part.y_center - rows[-1][0].y_center) <= _ROW_TOLERANCE:
            rows[-1].append(part)
        else:
            rows.append([part])
    return [" ".join(p.text for p in sorted(row, key=lambda p: p.x0)) for row in rows]
