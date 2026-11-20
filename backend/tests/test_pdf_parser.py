"""PyMuPdfParser on generated PDFs whose content order differs from the reading order."""

import pymupdf

from app.domain.entities import PdfLine
from app.infrastructure.pdf_parser import PyMuPdfParser


def pdf(*items: tuple[float, float, str, str], pages: int = 1) -> bytes:
    """items: (x, y, text, font) on page 1; font "helv" is regular, "hebo" is bold."""
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    for x, y, text, font in items:
        doc[0].insert_text((x, y), text, fontname=font, fontsize=11)
    data: bytes = doc.tobytes()
    return data


def test_lines_follow_the_page_position_not_the_content_order() -> None:
    # Written in the order DailyMed uses: heading, bullets, then the item texts at the end.
    data = pdf(
        (41, 100, "4 CONTRAINDICATIONS", "hebo"),
        (51, 120, "-", "helv"),
        (51, 140, "-", "helv"),
        (70, 140, "Hypersensitivity to the drug.", "helv"),
        (70, 120, "Acute liver failure.", "helv"),
        (41, 170, "5 WARNINGS AND PRECAUTIONS", "hebo"),
    )

    page_count, lines = PyMuPdfParser().extract_lines(data)

    assert page_count == 1
    assert lines == [
        PdfLine(1, "4 CONTRAINDICATIONS", bold=True),
        PdfLine(1, "- Acute liver failure.", bold=False),
        PdfLine(1, "- Hypersensitivity to the drug.", bold=False),
        PdfLine(1, "5 WARNINGS AND PRECAUTIONS", bold=True),
    ]


def test_parts_on_one_row_become_one_line_and_bold_ignores_the_bullet() -> None:
    data = pdf((51, 100, "-", "helv"), (70, 100, "Bold item", "hebo"), (200, 100, "tail", "hebo"))

    _, lines = PyMuPdfParser().extract_lines(data)

    assert lines == [PdfLine(1, "- Bold item tail", bold=True)]


def test_page_numbers_start_at_one() -> None:
    _, lines = PyMuPdfParser().extract_lines(pdf((41, 100, "Text", "helv"), pages=2))

    assert [line.page for line in lines] == [1]
