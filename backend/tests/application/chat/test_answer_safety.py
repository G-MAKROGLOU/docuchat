import json

import pytest

from app.application.chat import parse_intake, validate_answer
from tests.support.factories import sources_of


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
