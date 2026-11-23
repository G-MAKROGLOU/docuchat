from evals.retrieval_set import (
    Label,
    build_questions,
    gold_hits,
    reciprocal_rank,
    section_matches,
)

LABELS = [
    Label("set-lipitor", "Lipitor", "atorvastatin calcium", frozenset({"2.1", "6.1", "8.1"})),
    Label("set-eliquis", "Eliquis", "apixaban", frozenset({"2", "6", "8.2"})),
]


def test_questions_are_deterministic_and_only_ask_about_sections_the_label_has() -> None:
    questions = build_questions(LABELS)

    assert questions == build_questions(LABELS)
    assert len({q.id for q in questions}) == len(questions)
    for q in questions:
        for gold in q.gold:
            label = next(lb for lb in LABELS if lb.source_id == gold.source_id)
            assert any(section_matches(s, gold.section) for s in label.sections), q
    topics = {(q.gold[0].source_id, q.topic) for q in questions if q.kind != "comparison"}
    assert ("set-lipitor", "lactation") not in topics  # Lipitor has no 8.2 here
    assert ("set-eliquis", "lactation") in topics


def test_the_name_rotates_over_brand_generic_typo_and_lower_case() -> None:
    kinds = {q.name_kind for q in build_questions(LABELS) if q.kind == "single"}

    assert kinds == {"brand", "generic", "typo", "lower"}


def test_comparisons_name_two_labels_with_a_shared_topic() -> None:
    comparisons = [q for q in build_questions(LABELS) if q.kind == "comparison"]

    assert comparisons
    assert all(len(q.gold) == 2 for q in comparisons)
    assert {g.source_id for g in comparisons[0].gold} == {"set-lipitor", "set-eliquis"}


def test_a_section_matches_itself_and_its_subsections_only() -> None:
    assert section_matches("2.1", "2")
    assert section_matches("2", "2")
    assert not section_matches("12.3", "2")
    assert not section_matches("2", "2.1")


def test_hits_and_reciprocal_rank_use_label_and_section() -> None:
    gold = build_questions(LABELS)[0].gold
    first = gold[0]
    ranked = [
        ("set-other", first.section),
        (first.source_id, "17"),
        (first.source_id, first.section),
    ]

    assert gold_hits(ranked[:2], gold) == 0
    assert gold_hits(ranked, gold) == 1
    assert reciprocal_rank(ranked, gold) == 1 / 3
    assert reciprocal_rank(ranked[:2], gold) == 0.0
