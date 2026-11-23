from evals.run import Result, score

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
