import pytest

from app.application.topics import section_hints


@pytest.mark.parametrize(
    ("question", "hints"),
    [
        ("What is the dosage of Valium, and what are its side effects?", ("2", "6")),
        ("What is the starting dose of Lipitor?", ("2",)),
        ("How should I take Synthroid?", ("2",)),
        ("How should Synthroid be taken relative to food?", ("2",)),
        ("What are the adverse reactions of Ibrance?", ("6",)),
        ("Who should not take Eliquis? Any contraindications?", ("4",)),
        ("What is the boxed warning for Seroquel?", ("BW", "5")),
        ("Which drugs interact with Plavix?", ("7",)),
        ("Is Zoloft safe during pregnancy?", ("8.1",)),
        ("Is Zoloft safe to use during pregnancy?", ("8.1",)),
        ("Can I breastfeed while taking Lexapro?", ("8.2",)),
        ("Can Tamiflu be given to children?", ("8.4",)),
        ("Is Xanax safe for elderly patients?", ("8.5",)),
        ("What happens in an overdose of Ambien?", ("10",)),
        ("What is Jardiance used for?", ("1",)),
        ("What strengths does Crestor come in?", ("3",)),
        ("How should Vfend be stored?", ("16",)),
    ],
)
def test_question_topics_map_to_label_sections(question: str, hints: tuple[str, ...]) -> None:
    assert section_hints(question) == hints


def test_a_question_without_a_known_topic_has_no_hints() -> None:
    assert section_hints("Tell me about Valium") == ()
    assert section_hints("Valium?") == ()


def test_a_comparison_without_a_topic_gets_the_standard_sections() -> None:
    assert section_hints("Compare Jardiance and Farxiga", comparing=True) == (
        "1",
        "2",
        "4",
        "5",
        "6",
    )
    # A named topic wins, and one drug has no default.
    assert section_hints("Compare the side effects of A and B", comparing=True) == ("6",)
    assert section_hints("Tell me about Lipitor", comparing=False) == ()


def test_words_match_whole_words_only() -> None:
    # "dosage" in "underdosage" and "use" in "because" must not count.
    assert section_hints("Is underdosage a problem because of Valium?") == ()
