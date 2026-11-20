import re
import uuid

from app.application.chunking import anchor_of, build_chunks, embedding_input
from app.domain.entities import LabelSection, PdfLine, TextSpan

DOC = uuid.uuid4()


class SentenceSplitter:
    """Fake splitter: one span per sentence, with its start offset."""

    def split(self, text: str) -> list[TextSpan]:
        return [
            TextSpan(start=m.start() + len(m[0]) - len(m[0].lstrip()), text=m[0].strip())
            for m in re.finditer(r"[^.]+\.?", text)
            if m[0].strip()
        ]


class WordCounter:
    def count(self, text: str) -> int:
        return len(text.split())


def section(number: str, title: str, *lines: tuple[int, str]) -> LabelSection:
    return LabelSection(
        number=number,
        title=title,
        lines=tuple(PdfLine(page=p, text=t, bold=False) for p, t in lines),
    )


def test_chunks_carry_section_pages_anchor_and_tokens() -> None:
    sections = [
        section(
            "2.1",
            "Recommended Dosage",
            (4, "Take 10 mg once daily. Do not"),
            (5, "crush the tablet."),
        ),
    ]

    chunks = build_chunks(DOC, "Lipitor", sections, SentenceSplitter(), WordCounter())

    assert [(c.content, c.page_start, c.page_end) for c in chunks] == [
        ("Take 10 mg once daily.", 4, 4),
        ("Do not crush the tablet.", 4, 5),
    ]
    first = chunks[0]
    assert (first.document_id, first.drug_name) == (DOC, "Lipitor")
    assert (first.section_number, first.section_title) == ("2.1", "Recommended Dosage")
    assert first.token_count == 5
    assert first.anchor == "Take 10 mg once daily."


def test_sections_without_content_give_no_chunks() -> None:
    sections = [
        section("2", "DOSAGE AND ADMINISTRATION"),
        section("2.1", "Dose", (4, "One tablet.")),
    ]

    chunks = build_chunks(DOC, "X", sections, SentenceSplitter(), WordCounter())

    assert [c.section_number for c in chunks] == ["2.1"]


def test_chunks_never_cross_sections() -> None:
    sections = [
        section("4", "CONTRAINDICATIONS", (5, "None.")),
        section("5", "WARNINGS", (5, "Liver injury.")),
    ]

    chunks = build_chunks(DOC, "X", sections, SentenceSplitter(), WordCounter())

    assert [(c.section_number, c.content) for c in chunks] == [
        ("4", "None."),
        ("5", "Liver injury."),
    ]


def test_anchor_is_the_first_eight_words() -> None:
    assert anchor_of("one two three four five six seven eight nine ten") == (
        "one two three four five six seven eight"
    )
    assert anchor_of("  short   text ") == "short text"


def test_embedding_input_prefix_is_switchable() -> None:
    with_prefix = embedding_input(
        "Lipitor", "atorvastatin", "2.1 Dosage", "Take 10 mg.", prefix=True
    )
    without = embedding_input("Lipitor", "atorvastatin", "2.1 Dosage", "Take 10 mg.", prefix=False)

    assert with_prefix == "Drug: Lipitor (atorvastatin). Section: 2.1 Dosage.\nTake 10 mg."
    assert without == "Take 10 mg."
    assert embedding_input("", "hydralazine", "1 USE", "Text.", prefix=True).startswith(
        "Drug: hydralazine. Section: 1 USE."
    )
