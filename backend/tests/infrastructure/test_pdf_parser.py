"""PyMuPdfParser on generated PDFs whose content order differs from the reading order."""

from app.infrastructure.pdf_parser import PyMuPdfParser
from tests.support.factories import make_pdf
from tests.support.tuning import SETTINGS


def test_text_follows_the_page_position_not_the_content_order() -> None:
    # Written in the order DailyMed uses: heading, bullets, then the item texts at the end.
    data = make_pdf(
        (41, 100, "4 CONTRAINDICATIONS", "hebo"),
        (51, 120, "-", "helv"),
        (51, 140, "-", "helv"),
        (70, 140, "Hypersensitivity to the drug.", "helv"),
        (70, 120, "Acute liver failure.", "helv"),
        (41, 170, "5 WARNINGS AND PRECAUTIONS", "hebo"),
    )

    assert PyMuPdfParser(SETTINGS.pdf_row_tolerance).page_texts(data) == [
        "4 CONTRAINDICATIONS\n- Acute liver failure.\n- Hypersensitivity to the drug.\n"
        "5 WARNINGS AND PRECAUTIONS"
    ]


def test_parts_on_one_row_become_one_line() -> None:
    data = make_pdf(
        (51, 100, "-", "helv"), (70, 100, "Bold item", "hebo"), (200, 100, "tail", "hebo")
    )

    assert PyMuPdfParser(SETTINGS.pdf_row_tolerance).page_texts(data) == ["- Bold item tail"]


def test_every_page_has_a_text_even_when_empty() -> None:
    assert PyMuPdfParser(SETTINGS.pdf_row_tolerance).page_texts(
        make_pdf((41, 100, "Text", "helv"), pages=2)
    ) == ["Text", ""]
