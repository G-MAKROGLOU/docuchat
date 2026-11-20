import pytest

from app.application.label_sections import LabelFormatError, split_sections
from app.domain.entities import PdfLine


def L(page: int, text: str, bold: bool = False) -> PdfLine:  # noqa: N802
    return PdfLine(page=page, text=text, bold=bold)


HIGHLIGHTS_AND_CONTENTS = [
    L(1, "HIGHLIGHTS OF PRESCRIBING INFORMATION", bold=True),
    L(1, "These highlights do not include all the information."),
    L(2, "FULL PRESCRIBING INFORMATION: CONTENTS*", bold=True),
    L(2, "1 INDICATIONS AND USAGE", bold=True),
    L(2, "2 DOSAGE AND ADMINISTRATION", bold=True),
]


def body(*lines: PdfLine) -> list[PdfLine]:
    return [*HIGHLIGHTS_AND_CONTENTS, L(3, "FULL PRESCRIBING INFORMATION", bold=True), *lines]


def test_skips_highlights_and_contents_and_splits_numbered_sections() -> None:
    sections = split_sections(
        body(
            L(3, "1 INDICATIONS AND USAGE", bold=True),
            L(3, "Drug X is indicated for hypertension."),
            L(3, "2 DOSAGE AND ADMINISTRATION", bold=True),
            L(3, "2.1 Recommended Dosage", bold=True),
            L(4, "Take 10 mg once daily."),
        )
    )

    assert [(s.number, s.title) for s in sections] == [
        ("1", "INDICATIONS AND USAGE"),
        ("2", "DOSAGE AND ADMINISTRATION"),
        ("2.1", "Recommended Dosage"),
    ]
    assert [line.text for line in sections[0].lines] == ["Drug X is indicated for hypertension."]
    assert sections[1].lines == ()
    assert [(line.page, line.text) for line in sections[2].lines] == [(4, "Take 10 mg once daily.")]


def test_non_bold_numbered_lines_are_content_not_headings() -> None:
    sections = split_sections(
        body(
            L(3, "2.1 Recommended Dosage", bold=True),
            L(3, "5 mg twice daily"),
            L(3, "11 mg once daily"),
        )
    )

    assert len(sections) == 1
    assert [line.text for line in sections[0].lines] == ["5 mg twice daily", "11 mg once daily"]


def test_boxed_warning_becomes_its_own_section() -> None:
    sections = split_sections(
        body(
            L(3, "WARNING: SERIOUS INFECTIONS, MORTALITY, MALIGNANCY,", bold=True),
            L(3, "ADVERSE CARDIOVASCULAR EVENTS, and THROMBOSIS", bold=True),
            L(3, "Patients are at increased risk for serious infections.", bold=True),
            L(4, "1 INDICATIONS AND USAGE", bold=True),
            L(4, "Indicated for arthritis."),
        )
    )

    assert sections[0].number == "BW"
    assert sections[0].title == (
        "WARNING: SERIOUS INFECTIONS, MORTALITY, MALIGNANCY, "
        "ADVERSE CARDIOVASCULAR EVENTS, and THROMBOSIS"
    )
    assert [line.text for line in sections[0].lines] == [
        "Patients are at increased risk for serious infections."
    ]
    assert sections[1].number == "1"


def test_wrapped_heading_title_is_joined() -> None:
    sections = split_sections(
        body(
            L(3, "2.3 Recommended Dosage in Adults with Rheumatoid Arthritis,", bold=True),
            L(3, "Psoriatic Arthritis, and Ankylosing Spondylitis", bold=True),
            L(3, "Take one tablet."),
        )
    )

    assert sections[0].title == (
        "Recommended Dosage in Adults with Rheumatoid Arthritis, "
        "Psoriatic Arthritis, and Ankylosing Spondylitis"
    )
    assert [line.text for line in sections[0].lines] == ["Take one tablet."]


def test_stops_at_the_medication_guide_and_label_end_matter() -> None:
    sections = split_sections(
        body(
            L(3, "17 PATIENT COUNSELING INFORMATION", bold=True),
            L(3, "Advise patients to read the Medication Guide."),
            L(4, "MEDICATION GUIDE", bold=True),
            L(4, "What is the most important information?"),
            L(5, "Revised: 3/2026"),
        )
    )

    assert [s.number for s in sections] == ["17"]
    assert [line.text for line in sections[0].lines] == [
        "Advise patients to read the Medication Guide."
    ]


def test_out_of_range_top_level_numbers_are_not_headings() -> None:
    sections = split_sections(
        body(L(3, "1 INDICATIONS AND USAGE", bold=True), L(3, "400 MG TABLETS", bold=True))
    )

    assert [line.text for line in sections[0].lines] == ["400 MG TABLETS"]


def test_label_without_full_prescribing_information_is_rejected() -> None:
    with pytest.raises(LabelFormatError):
        split_sections(HIGHLIGHTS_AND_CONTENTS)


def test_bold_table_cells_with_a_number_are_not_headings() -> None:
    sections = split_sections(
        body(
            L(3, "14 CLINICAL STUDIES", bold=True),
            L(3, "Results by dose:"),
            L(4, "10 mg", bold=True),
            L(4, "40% reduction"),
        )
    )

    assert [s.number for s in sections] == ["14"]
    assert [line.text for line in sections[0].lines] == [
        "Results by dose:",
        "10 mg",
        "40% reduction",
    ]


def test_top_level_numbers_never_go_back() -> None:
    sections = split_sections(
        body(
            L(3, "12 CLINICAL PHARMACOLOGY", bold=True),
            L(3, "Text."),
            L(4, "2 Table Of Doses", bold=True),
            L(4, "13 NONCLINICAL TOXICOLOGY", bold=True),
        )
    )

    assert [s.number for s in sections] == ["12", "13"]
    assert [line.text for line in sections[0].lines] == ["Text.", "2 Table Of Doses"]


def test_guide_titles_end_the_body_only_as_a_whole_line() -> None:
    sections = split_sections(
        body(
            L(3, "17 PATIENT COUNSELING INFORMATION", bold=True),
            L(3, "Patient Information about sun exposure", bold=True),
            L(3, "Advise patients to avoid the sun."),
            L(4, "Patient Information", bold=True),
            L(4, "What is Drug X?"),
        )
    )

    assert [line.text for line in sections[-1].lines] == [
        "Patient Information about sun exposure",
        "Advise patients to avoid the sun.",
    ]


def test_display_panel_ends_the_body_as_a_prefix() -> None:
    sections = split_sections(
        body(
            L(3, "17 PATIENT COUNSELING INFORMATION", bold=True),
            L(3, "Advise patients."),
            L(4, "PRINCIPAL DISPLAY PANEL - 5 mg Tablet Bottle Label", bold=True),
            L(4, "NDC 0000-0000"),
        )
    )

    assert [line.text for line in sections[-1].lines] == ["Advise patients."]


def test_guide_title_variants_end_the_body() -> None:
    for title in ("Patient Information Leaflet", "MEDICATION GUIDE:", "Instructions for Use*"):
        sections = split_sections(
            body(
                L(3, "17 PATIENT COUNSELING INFORMATION", bold=True),
                L(3, "Advise patients."),
                L(4, title, bold=True),
                L(4, "What is Drug X?"),
            )
        )

        assert [line.text for line in sections[-1].lines] == ["Advise patients."], title


def test_guide_title_with_a_lower_case_note_in_brackets_is_section_text() -> None:
    sections = split_sections(
        body(
            L(3, "17 PATIENT COUNSELING INFORMATION", bold=True),
            L(3, "Medication Guide (see FDA-approved patient labeling)", bold=True),
            L(3, "Advise patients."),
        )
    )

    assert [line.text for line in sections[-1].lines] == [
        "Medication Guide (see FDA-approved patient labeling)",
        "Advise patients.",
    ]
