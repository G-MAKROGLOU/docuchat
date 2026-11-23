from app.application.page_locator import PageLocator
from tests.support.tuning import INGEST

PAGES = [
    "HIGHLIGHTS. Take 10 mg once daily. FULL PRESCRIBING INFORMATION: CONTENTS* 1 INDICATIONS",
    "FULL PRESCRIBING INFORMATION\n1 INDICATIONS AND USAGE\nTreats high cholesterol.",
    "2 DOSAGE\nTake 10 mg once daily. Do not\n",
    "crush the tablet. Store at room temperature.",
]


def locate(pages: list[str], *contents: str) -> list[tuple[int, int]]:
    return PageLocator(pages, INGEST.locator).locate_all(list(contents))


def test_a_chunk_is_found_after_the_body_start_not_in_the_highlights() -> None:
    assert locate(PAGES, "Take 10 mg once daily.") == [(3, 3)]


def test_a_chunk_across_a_page_break_spans_both_pages() -> None:
    assert locate(PAGES, "Take 10 mg once daily. Do not crush the tablet.") == [(3, 4)]


def test_matching_ignores_case_spaces_and_punctuation() -> None:
    assert locate(PAGES, "treats  HIGH-cholesterol") == [(2, 2)]


def test_search_goes_forward_from_the_page_of_the_last_match() -> None:
    # "Take 10 mg" is on page 3, before the reading position on page 4.
    pages = locate(PAGES, "Store at room temperature.", "Take 10 mg")

    assert pages == [(4, 4), (4, 4)]


def test_without_a_body_start_the_search_starts_at_page_one() -> None:
    assert locate(["Alpha text.", "Beta text."], "Beta text") == [(2, 2)]


TABLE_PAGES = [
    "FULL PRESCRIBING INFORMATION: CONTENTS\nFULL PRESCRIBING INFORMATION\n6 ADVERSE REACTIONS\n"
    "The table shows the reactions.",
    "Adverse Reaction\nUpper respiratory tract infection\nNausea and vomiting\nPlacebo\n12\n3",
    "Drug\n8\n4\n7 DRUG INTERACTIONS\nNo interactions with other drugs are known.",
]


def test_a_table_chunk_in_another_cell_order_is_found_by_its_cells() -> None:
    table = "Adverse Reaction | Placebo | Drug\nUpper respiratory tract infection | 12 | 8"

    pages = locate(
        TABLE_PAGES, "The table shows the reactions.", table, "No interactions with other drugs"
    )

    assert pages == [(1, 1), (2, 2), (3, 3)]


def test_a_chunk_without_any_match_takes_the_pages_between_its_neighbours() -> None:
    locator = PageLocator(TABLE_PAGES, INGEST.locator)

    pages = locator.locate_all(
        ["The table shows the reactions.", "12 | 8 | 3 | 4", "No interactions with other drugs"]
    )

    assert pages == [(1, 1), (1, 3), (3, 3)]
    assert locator.misses == 1


def test_the_end_of_a_chunk_is_not_matched_far_away() -> None:
    filler = " ".join(f"word{i}" for i in range(400))
    pages = [
        "FULL PRESCRIBING INFORMATION: CONTENTS FULL PRESCRIBING INFORMATION Start of the text "
        "that has more than forty letters and then stops.",
        filler,
        "more than forty letters and that ends right here.",
    ]
    chunk = "Start of the text that has more than forty letters and that ends right here."

    assert locate(pages, chunk) == [(1, 1)]


def test_a_repeated_sentence_earlier_on_the_same_page_is_not_matched() -> None:
    pages = [
        "FULL PRESCRIBING INFORMATION: CONTENTS FULL PRESCRIBING INFORMATION",
        "Take one tablet daily for eight weeks.\n1.2 Children\nGive half a tablet.",
        "Take one tablet daily for eight weeks.",
    ]

    found = locate(
        pages, "1.2 Children\nGive half a tablet.", "Take one tablet daily for eight weeks."
    )

    assert found == [(2, 2), (3, 3)]


def test_an_end_not_found_in_order_takes_the_page_of_its_cells() -> None:
    pages = [
        "FULL PRESCRIBING INFORMATION: CONTENTS FULL PRESCRIBING INFORMATION "
        "Table 2 shows doses for adults and children in the trials.",
        "Adults in the trial group Children in the trial group 10 mg 5 mg",
    ]
    chunk = (
        "Table 2 shows doses for adults and children in the trials.\n"
        "Adults in the trial group | 10 mg\nChildren in the trial group | 5 mg"
    )

    assert locate(pages, chunk) == [(1, 2)]
