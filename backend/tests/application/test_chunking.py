import uuid
from collections.abc import Sequence

from app.application.chunking import anchor_of, build_chunks, embedding_input
from app.domain.documents import Document
from app.domain.entities import LabelSection
from tests.support.factories import make_document
from tests.support.fakes_ingestion import SentenceSplitter, WordCounter

DOC = uuid.uuid4()


def document(brand: str, generic: str = "generic") -> Document:
    return make_document(
        brand, generic, document_id=DOC, manufacturer="M", source_id="s1", storage_key="key"
    )


def section(number: str, title: str, text: str = "") -> LabelSection:
    return LabelSection(number=number, title=title, text=text)


def pages_of(contents: Sequence[str]) -> list[tuple[int, int]]:
    """Fake page lookup: the chunk with "crush" crosses from page 4 to page 5."""
    return [(4, 5) if "crush" in c else (4, 4) for c in contents]


def test_chunks_carry_section_pages_anchor_and_tokens() -> None:
    sections = [
        section("2.1", "Recommended Dosage", "Take 10 mg once daily. Do not\ncrush the tablet.")
    ]

    chunks = build_chunks(
        document("Lipitor"), sections, SentenceSplitter(), WordCounter(), pages_of
    )

    assert [(c.content, c.page_start, c.page_end) for c in chunks] == [
        ("Take 10 mg once daily.", 4, 4),
        ("Do not\ncrush the tablet.", 4, 5),
    ]
    first = chunks[0]
    assert (first.document_id, first.drug_name) == (DOC, "Lipitor")
    assert (first.section_number, first.section_title) == ("2.1", "Recommended Dosage")
    assert first.token_count == 5
    assert first.anchor == "Take 10 mg once daily."


def test_sections_without_content_give_no_chunks() -> None:
    sections = [section("2", "DOSAGE AND ADMINISTRATION"), section("2.1", "Dose", "One tablet.")]

    chunks = build_chunks(document("X"), sections, SentenceSplitter(), WordCounter(), pages_of)

    assert [c.section_number for c in chunks] == ["2.1"]


def test_chunks_never_cross_sections() -> None:
    sections = [
        section("4", "CONTRAINDICATIONS", "None."),
        section("5", "WARNINGS", "Liver injury."),
    ]

    chunks = build_chunks(document("X"), sections, SentenceSplitter(), WordCounter(), pages_of)

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


def test_a_label_without_a_brand_uses_the_generic_name() -> None:
    sections = [section("1", "USE", "Treats fungus.")]

    chunks = build_chunks(
        document("", "terbinafine"), sections, SentenceSplitter(), WordCounter(), pages_of
    )

    assert chunks[0].drug_name == "terbinafine"


def test_the_first_chunk_of_a_section_is_located_with_its_heading() -> None:
    seen: list[str] = []

    def record(contents: Sequence[str]) -> list[tuple[int, int]]:
        seen.extend(contents)
        return [(1, 1)] * len(contents)

    sections = [section("4", "CONTRAINDICATIONS", "None. Really none.")]
    chunks = build_chunks(document("X"), sections, SentenceSplitter(), WordCounter(), record)

    assert seen == ["4 CONTRAINDICATIONS\nNone.", "Really none."]
    assert chunks[0].content == "None."
