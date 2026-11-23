import logging

import pytest

from app.application.label_sections import LabelFormatError, split_sections
from app.domain.entities import LabelNode, LabelSection

UNCLASSIFIED = "42229-5"


def node(title: str, text: str = "", *children: LabelNode, code: str = UNCLASSIFIED) -> LabelNode:
    return LabelNode(code=code, title=title, text=text, children=children)


def numbers(sections: list[LabelSection]) -> list[str]:
    return [s.number for s in sections]


def test_numbered_sections_and_subsections_in_document_order() -> None:
    sections = split_sections(
        [
            node("1 INDICATIONS AND USAGE", "Treats pain.", code="34067-9"),
            node(
                "2 DOSAGE AND ADMINISTRATION",
                "",
                node("2.1 Adults", "10 mg daily."),
                node("2.2 Children", "5 mg daily."),
                code="34068-7",
            ),
        ]
    )

    assert sections == [
        LabelSection("1", "INDICATIONS AND USAGE", "Treats pain."),
        LabelSection("2", "DOSAGE AND ADMINISTRATION", ""),
        LabelSection("2.1", "Adults", "10 mg daily."),
        LabelSection("2.2", "Children", "5 mg daily."),
    ]


@pytest.mark.parametrize(
    ("title", "number", "rest"),
    [
        ("2. DOSAGE AND ADMINISTRATION", "2", "DOSAGE AND ADMINISTRATION"),
        ("5. 2 Angina", "5.2", "Angina"),
        ("5.1 0 Impaired Renal Function", "5.10", "Impaired Renal Function"),
        ("14 .1 Hypertension", "14.1", "Hypertension"),
        ("2. 1 3 Dosage Modifications", "2.13", "Dosage Modifications"),
        ("7.7 mTOR Inhibitor s", "7.7", "mTOR Inhibitor s"),
        ("2.1 5 mg Tablets", "2.1", "5 mg Tablets"),
    ],
)
def test_numbers_with_broken_spacing_are_normalized(title: str, number: str, rest: str) -> None:
    sections = split_sections([node("5 WARNINGS", "", node(title, "Text."))])

    assert (sections[1].number, sections[1].title) == (number, rest)


def test_unnumbered_children_join_the_text_of_their_numbered_parent() -> None:
    sections = split_sections(
        [
            node(
                "8 USE IN SPECIFIC POPULATIONS",
                "",
                node(
                    "8.1 Pregnancy",
                    "",
                    node("Risk Summary", "No data."),
                    node("Data", "Animal studies."),
                ),
            )
        ]
    )

    assert sections[1] == LabelSection(
        "8.1", "Pregnancy", "Risk Summary\nNo data.\nData\nAnimal studies."
    )


def test_boxed_warning_comes_from_its_code() -> None:
    sections = split_sections(
        [
            node("WARNING: BLEEDING RISK", "May cause bleeding.", code="34066-1"),
            node("1 INDICATIONS AND USAGE", "Treats pain."),
        ]
    )

    assert sections[0] == LabelSection("BW", "WARNING: BLEEDING RISK", "May cause bleeding.")


def test_highlights_guides_and_package_labels_are_not_sections() -> None:
    sections = split_sections(
        [
            node("These highlights do not include all the information", "H.", code="48780-1"),
            node("", "Recent changes.", code="43683-2"),
            node("1 INDICATIONS AND USAGE", "Treats pain."),
            node(
                "17 PATIENT COUNSELING INFORMATION",
                "Tell patients.",
                node("MEDICATION GUIDE", "Read this.", code="42231-1"),
            ),
            node("PATIENT INFORMATION", "Read this.", code="42230-3"),
            node("PACKAGE LABEL.PRINCIPAL DISPLAY PANEL", "NDC 1.", code="51945-4"),
        ]
    )

    assert numbers(sections) == ["1", "17"]
    assert sections[1].text == "Tell patients."


def test_an_unknown_unnumbered_top_level_section_is_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.application.label_sections"):
        sections = split_sections(
            [node("1 INDICATIONS AND USAGE", "Treats pain."), node("SPL UNCLASSIFIED", "Text.")]
        )

    assert numbers(sections) == ["1"]
    assert "section skipped" in caplog.text


def test_a_top_level_number_outside_the_standard_sections_is_skipped() -> None:
    sections = split_sections([node("1 INDICATIONS AND USAGE", "A."), node("30 TABLETS", "B.")])

    assert numbers(sections) == ["1"]


def test_a_subsection_at_the_top_level_is_a_section() -> None:
    sections = split_sections([node("1 INDICATIONS AND USAGE", "A."), node("1.2 Adults", "B.")])

    assert numbers(sections) == ["1", "1.2"]


def test_a_label_without_numbered_sections_raises() -> None:
    with pytest.raises(LabelFormatError):
        split_sections([node("These highlights do not include", "H.", code="48780-1")])
