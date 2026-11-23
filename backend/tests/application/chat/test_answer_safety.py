import json

import pytest

from app.application.chat import SourceRef, parse_intake, validate_answer
from tests.support.factories import make_chunk, sources_of


def reply(text: str) -> str:
    return json.dumps({"action": "reply", "reply": text})


@pytest.mark.parametrize(
    "text",
    [
        "Hi! Ask me about a medicine in the library.",
        "I have the labels of 50 medicines, for example Lipitor and Zoloft.",
        "I only answer questions about drug labels.",
    ],
)
def test_a_plain_intake_reply_is_kept(text: str) -> None:
    assert parse_intake(reply(text)) == ("reply", text)


@pytest.mark.parametrize(
    "text",
    [
        "The usual dose of Lipitor is 10 mg once daily.",
        "Take 2.5 mcg/kg each day.",
        "Most adults take 0.5 mL.",
        "See https://example.com/lipitor for the dose.",
        "More at www.example.com.",
        "Read [the label](https://example.com).",
    ],
)
def test_an_intake_reply_with_a_dose_or_a_link_goes_to_the_search(text: str) -> None:
    assert parse_intake(reply(text)) == ("search", "")


def test_an_intake_reply_that_is_too_long_goes_to_the_search() -> None:
    assert parse_intake(reply("Hello. " * 120)) == ("search", "")


def test_a_dose_that_no_cited_excerpt_has_refuses_the_answer() -> None:
    result = validate_answer("The dose is 10 mg or 80 mg [S1].", sources_of("10 mg daily"))

    assert result.refusal == "no_valid_citation"


def test_a_dose_from_the_cited_excerpt_passes() -> None:
    result = validate_answer("Start with 10 mg to 20 mg [S1].", sources_of("10 to 20 mg once"))

    assert result.refusal is None


def test_a_dose_found_only_in_an_excerpt_that_is_not_cited_refuses() -> None:
    answer = "The dose is 80 mg [S1]."

    result = validate_answer(answer, sources_of("10 mg daily", "80 mg for adults"))

    assert result.refusal == "no_valid_citation"


def test_a_number_without_a_unit_and_without_a_source_stays_a_warning() -> None:
    result = validate_answer("Take it 2 times a day [S1].", sources_of("twice daily"))

    assert result.refusal is None
    assert result.ungrounded == ("2",)


def test_a_link_that_no_cited_excerpt_has_refuses_the_answer() -> None:
    answer = "Report side effects at https://example.com/report [S1]."

    result = validate_answer(answer, sources_of("Report side effects to the FDA."))

    assert result.refusal == "no_valid_citation"


def test_a_link_from_the_cited_excerpt_passes() -> None:
    answer = "Report side effects at www.fda.gov/medwatch [S1]."

    result = validate_answer(
        answer, sources_of("contact FDA at 1-800-FDA-1088 or www.fda.gov/medwatch.")
    )

    assert result.refusal is None


QUESTION = "When should the Eliquis dose be reduced to 2.5 mg?"
CITED = "5 mg twice daily; 2.5 mg twice daily in patients with two of: age 80 years or older"


def test_a_lead_in_that_repeats_the_question_figure_is_removed_not_refused() -> None:
    answer = (
        "Here is what the label says about when the dose is 2.5 mg.\n\n"
        "- The usual dose is 5 mg twice daily [S1].\n"
        "- It is 2.5 mg twice daily in patients aged 80 years or older [S1]."
    )

    result = validate_answer(answer, sources_of(CITED), question=QUESTION)

    assert result.refusal is None
    assert result.answer.startswith("- The usual dose is 5 mg")


def test_an_uncited_sentence_with_a_new_figure_still_refuses() -> None:
    answer = "The dose is 2.5 mg or 10 mg.\n\n- The usual dose is 5 mg twice daily [S1]."

    result = validate_answer(answer, sources_of(CITED), question=QUESTION)

    assert result.refusal == "no_valid_citation"


def test_without_the_question_an_uncited_figure_refuses_as_before() -> None:
    answer = "Here is what the label says about 2.5 mg.\n\n- The usual dose is 5 mg [S1]."

    assert validate_answer(answer, sources_of(CITED)).refusal == "no_valid_citation"


@pytest.mark.parametrize(
    "lead",
    [
        "The relevant sections are 2.1, 2.3, 2.6, 5.4 and 8.6.",
        "See Sections 2.1 and 5.4 of the label.",
        "Tables 1 to 3 list the doses.",
    ],
)
def test_lists_of_section_and_table_numbers_need_no_marker(lead: str) -> None:
    answer = f"{lead}\n\n- Take 20 mg once daily [S1]."

    assert validate_answer(answer, sources_of("20 mg once daily")).refusal is None


# A dose needs the same number with the same or an equivalent unit in an excerpt it cites.


def refusal(answer: str, *excerpts: str, question: str = "") -> str | None:
    return validate_answer(answer, sources_of(*excerpts), question=question).refusal


def test_a_table_number_is_not_a_source_for_a_dose() -> None:
    assert refusal("Take 10 mg once daily [S1].", "See Table 10. Take 5 mg once daily.") == (
        "no_valid_citation"
    )


@pytest.mark.parametrize(
    ("answer", "excerpt"),
    [
        ("Take 10 mcg once daily [S1].", "10 mg once daily"),
        ("Take 10 mg once daily [S1].", "10 mcg once daily"),
        ("Give 10 mg [S1].", "10 mg/kg once daily"),
        ("Give 10 mg/kg [S1].", "10 mg once daily"),
        ("Give 2 mg/kg/day [S1].", "2 mg/kg/hour"),
        ("Give 5 mL [S1].", "5 mg"),
        ("The dose is 20 mg [S1].", "a 20% solution"),
    ],
)
def test_a_dose_with_another_unit_in_the_excerpt_refuses(answer: str, excerpt: str) -> None:
    assert refusal(answer, excerpt) == "no_valid_citation"


@pytest.mark.parametrize(
    ("answer", "excerpt"),
    [
        ("Take 1 g once daily [S1].", "1000 mg once daily"),
        ("Take 0.5 mg [S1].", "500 mcg"),
        ("Take 500 mcg [S1].", "500 \u00b5g"),
        ("Take 500 micrograms [S1].", "500 mcg"),
        ("Take 1,000 mg [S1].", "1000 mg"),
        ("Give 2.5 mg/kg [S1].", "2.5 mg/kg every 12 hours"),
        ("Give 10 mg per kg [S1].", "10 mg/kg"),
        ("Give 75 mg/m2 [S1].", "75 mg/m\u00b2 on day 1"),
        ("Use the 10-mg tablet [S1].", "10 mg tablets"),
        ("Take it every 12 hours [S1].", "every 12 hours"),
    ],
)
def test_a_dose_with_the_same_or_an_equivalent_unit_passes(answer: str, excerpt: str) -> None:
    assert refusal(answer, excerpt) is None


def test_a_dose_cited_to_the_wrong_source_refuses() -> None:
    excerpts = ("5 mg for children", "10 mg for adults")

    assert refusal("Adults take 10 mg [S1]. Children take 5 mg [S2].", *excerpts) == (
        "no_valid_citation"
    )
    assert refusal("Adults take 10 mg [S2]. Children take 5 mg [S1].", *excerpts) is None
    assert refusal("Adults take 10 mg and children 5 mg [S1][S2].", *excerpts) is None


def test_a_sentence_takes_the_source_of_the_next_marker_in_its_line() -> None:
    assert refusal("Adults take 10 mg. Children take 5 mg [S2].", "10 mg", "5 mg") == (
        "no_valid_citation"
    )
    assert refusal("Adults take 10 mg. Children take 5 mg [S1].", "10 mg and 5 mg", "x") is None


def test_a_nested_item_takes_the_source_of_the_line_above_it() -> None:
    answer = "- Doses [S2]:\n  - adults: 10 mg"

    assert refusal(answer, "10 mg", "20 mg") == "no_valid_citation"
    assert refusal(answer, "20 mg", "10 mg") is None


@pytest.mark.parametrize(
    ("answer", "excerpt", "expected"),
    [
        ("Take 10 to 20 mg [S1].", "10 mg to 20 mg once daily", None),
        ("Take 10-20 mg [S1].", "10 to 20 mg once daily", None),
        ("Take 10 to 20 mg [S1].", "10\u201320 mg once daily", None),
        ("Take 10 to 20 mg [S1].", "10 mg once daily", "no_valid_citation"),
        ("Take 10 to 20 mg [S1].", "Table 20 lists 10 mg", "no_valid_citation"),
        ("Take 10, 20, or 40 mg [S1].", "10 mg, 20 mg and 80 mg", "no_valid_citation"),
        ("Take 10, 20, or 40 mg [S1].", "10, 20, or 40 mg tablets", None),
        ("Take 10 to 20 mcg [S1].", "10 to 20 mg once daily", "no_valid_citation"),
    ],
)
def test_each_number_of_a_dose_range_needs_its_source(
    answer: str, excerpt: str, expected: str | None
) -> None:
    assert refusal(answer, excerpt) == expected


def test_a_statement_of_absence_may_repeat_a_figure_of_the_question() -> None:
    answer = "- Adults take 10 mg [S1].\nThe excerpts do not give a dose for 6 years."

    assert refusal(answer, "10 mg", question="Dose at 6 years?") is None
    assert refusal(answer, "10 mg", question="Dose for a child?") == "no_valid_citation"


def test_a_statement_of_absence_never_takes_an_amount_from_the_question() -> None:
    answer = "- Adults take 5 mg [S1].\nThe labels do not limit this, so take 80 mg."

    assert refusal(answer, "5 mg", question="Can I take 80 mg?") == "no_valid_citation"


@pytest.mark.parametrize(
    "answer",
    [
        "For patients aged 65, 10 mg daily [S1].",
        "On days 1 and 2, 10 mg daily [S1].",
    ],
)
def test_a_figure_before_a_comma_does_not_join_the_next_dose(answer: str) -> None:
    assert refusal(answer, "Patients aged 65 or older on days 1 and 2: 10 mg daily") is None


def test_a_nested_item_takes_the_source_of_its_nearest_marked_parent() -> None:
    answer = "- Adults [S1]:\n  - Tablets [S2]: 5 mg\n    - Max 10 mg daily"

    assert refusal(answer, "adults", "tablets 5 mg; max 10 mg daily") is None


@pytest.mark.parametrize(
    ("answer", "excerpt", "expected"),
    [
        ("Take at most 40 mg/day [S1].", "maximum 40 mg daily", None),
        ("Take at most 40 mg per day [S1].", "40 mg once a day", None),
        ("Give 10 mg/kg/day [S1].", "10 mg/kg once daily", None),
        ("Take 40 mg daily [S1].", "40 mg/day", "no_valid_citation"),
        ("Take at most 40 mg/day [S1].", "40 mg twice daily", "no_valid_citation"),
    ],
)
def test_daily_in_the_excerpt_counts_as_per_day(
    answer: str, excerpt: str, expected: str | None
) -> None:
    assert refusal(answer, excerpt) == expected


@pytest.mark.parametrize("excerpt", ["10 \u0130U", "5 mg/m\u0130n", "take 5 hour\u017f"])
def test_an_unusual_unit_spelling_in_an_excerpt_does_not_break_the_check(excerpt: str) -> None:
    assert refusal("Take 2 mg [S1].", excerpt) == "no_valid_citation"


def test_a_dose_from_the_table_header_of_a_cited_excerpt_is_supported() -> None:
    # The model sees the caption and header row of a split table, so the check reads them too.
    row = make_chunk(
        "Adults | 18 | 12", table_header="Table 2. Patients\nGroup | Sitagliptin 100 mg"
    )
    answer = "The group took Sitagliptin 100 mg [S1]."

    result = validate_answer(answer, [SourceRef("S1", row)])

    assert result.refusal is None
