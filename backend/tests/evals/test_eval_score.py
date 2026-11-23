import json
from pathlib import Path
from typing import Any

from evals.run import Result, load_questions, result_of, score

ANSWER = Result("final", "Take 10 mg to 20 mg once daily [S1].", ["S1"], None)


def test_an_answer_passes_when_every_fact_group_matches() -> None:
    question = {"expect": "answer", "facts": [["10 mg"], ["20 mg|40 mg"]]}

    assert score(question, ANSWER) == (True, [])


def test_an_answer_fails_with_the_missing_groups() -> None:
    question = {"expect": "answer", "facts": [["10 mg"], ["twice daily"]]}

    assert score(question, ANSWER) == (False, ["twice daily"])


def test_an_answer_needs_citations() -> None:
    question = {"expect": "answer", "facts": [["10 mg"]]}

    assert score(question, Result("final", "Take 10 mg.", [], None)) == (False, ["citations"])


def test_a_refusal_fails_an_answer_question() -> None:
    question = {"expect": "answer", "facts": []}

    assert score(question, Result("refusal", "", [], "no_valid_citation")) == (
        False,
        ["outcome refusal"],
    )


def test_no_answer_accepts_a_refusal_or_a_reply_but_not_a_cited_answer() -> None:
    question = {"expect": "no_answer"}

    assert score(question, Result("refusal", "", [], "out_of_scope"))[0]
    assert score(question, Result("final", "I only answer label questions.", [], None))[0]
    assert not score(question, ANSWER)[0]


def test_a_reply_must_have_no_citations() -> None:
    question = {"expect": "reply"}

    assert score(question, Result("final", "Hi!", [], None))[0]
    assert not score(question, ANSWER)[0]


def test_a_clarify_question_passes_only_with_a_clarify_outcome() -> None:
    question = {"expect": "clarify"}

    assert score(question, Result("clarify", "", [], None)) == (True, [])
    assert score(question, ANSWER) == (False, ["clarify"])


def test_a_refusal_with_an_expected_reason_needs_that_reason() -> None:
    question = {"expect": "refusal", "refusal": "drug_not_in_corpus"}

    assert score(question, Result("refusal", "", [], "drug_not_in_corpus")) == (True, [])
    assert score(question, Result("refusal", "", [], "out_of_scope")) == (
        False,
        ["refusal drug_not_in_corpus"],
    )


def test_the_golden_set_maps_to_the_runner_fields(tmp_path: Path) -> None:
    line = {
        "id": "g1", "question": "And for children?", "type": "follow_up",
        "expected_outcome": "answer", "expected_drugs": ["Lipitor"],
        "expected_sections": {"Lipitor": ["2.3"]}, "reference_answer": "10 mg once daily.",
        "reviewed": False, "history": [["user", "Lipitor dose for adults?"]],
    }  # fmt: skip
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    (question,) = load_questions(path)

    assert question["text"] == "And for children?"
    assert question["expect"] == "answer"
    assert question["sections"] == {"Lipitor": ["2.3"]}
    assert question["reference"] == "10 mg once daily."
    assert question["history"] == ["Lipitor dose for adults?"]


def test_a_clarify_turn_stays_clarify_when_its_final_event_follows() -> None:
    events: list[dict[str, Any]] = [
        {"type": "clarify", "candidates": ["Celexa", "Lexapro"]},
        {"type": "token", "text": "Which medicine do you mean?"},
        {"type": "final", "answer": "Which medicine do you mean?", "citations": []},
    ]

    assert result_of(events).outcome == "clarify"
    assert result_of(events[2:]).outcome == "final"
