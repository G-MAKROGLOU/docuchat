from app.application.drug_detection import DrugDetection, DrugEntry
from app.infrastructure.name_similarity import RapidFuzzSimilarity
from evals.detector_calibration import (
    CLARIFY_COST,
    WRONG_COST,
    Case,
    Thresholds,
    best,
    build_cases,
    classify,
    cost,
    evaluate,
    typo_variants,
)

ENTRIES = [
    DrugEntry("Celexa", "Celexa", "citalopram"),
    DrugEntry("Celebrex", "Celebrex", "celecoxib"),
    DrugEntry("Lipitor", "Lipitor", "atorvastatin"),
]


def test_typo_variants_are_deterministic_distinct_and_one_edit_away() -> None:
    variants = typo_variants("lipitor")

    assert variants == typo_variants("lipitor")
    assert len(variants) == len(set(variants)) >= 4
    assert "lipitor" not in variants
    assert all(abs(len(v) - len("lipitor")) <= 1 for v in variants)


def test_build_cases_has_typos_of_each_key_and_labelled_negatives() -> None:
    cases = build_cases(ENTRIES, outside=["tylenol"], words=["dosage"])

    typos = [c for c in cases if c.kind == "typo"]
    assert {c.expected for c in typos} == {"Celexa", "Celebrex", "Lipitor"}
    # A typo that is itself a key of the catalog is not a typo case.
    assert all(c.word not in {"celexa", "celebrex", "lipitor"} for c in typos)
    assert Case("tylenol", None, "outside") in cases
    assert Case("dosage", None, "word") in cases


def test_classify_names_each_result() -> None:
    assert classify(DrugDetection(drugs=("Lipitor",)), "Lipitor") == "correct"
    assert classify(DrugDetection(ambiguous=("Celexa", "Celebrex")), "Celexa") == "clarify"
    assert classify(DrugDetection(), "Lipitor") == "missed"
    assert classify(DrugDetection(drugs=("Celexa",)), "Celebrex") == "wrong"
    assert classify(DrugDetection(), None) == "clean"
    assert classify(DrugDetection(not_in_corpus=("tylenol",)), None) == "clean"
    assert classify(DrugDetection(ambiguous=("Celexa", "Celebrex")), None) == "clarify"
    assert classify(DrugDetection(drugs=("Lipitor",)), None) == "wrong"
    # Two labels of one brand can differ in case ("OZEMPIC" and "Ozempic").
    assert classify(DrugDetection(drugs=("Ozempic",)), "OZEMPIC") == "correct"


def test_evaluate_counts_results_per_kind() -> None:
    cases = [Case("lipitr", "Lipitor", "typo"), Case("dosage", None, "word")]

    counts = evaluate(ENTRIES, RapidFuzzSimilarity(), Thresholds(85, 75, 12), cases)

    assert counts == {"typo": {"correct": 1}, "word": {"clean": 1}}


def test_cost_weighs_a_wrong_drug_far_above_a_miss_and_a_clarify() -> None:
    assert cost({"wrong": 1, "missed": 0, "clarify": 0}) == WRONG_COST
    assert cost({"wrong": 0, "missed": 2, "clarify": 2}) == 2 + 2 * CLARIFY_COST


def test_best_has_the_lowest_cost_then_the_fewest_wrong() -> None:
    rows = [
        {"thresholds": Thresholds(80, 70, 10), "wrong": 2, "missed": 0, "clarify": 0},
        {"thresholds": Thresholds(85, 75, 12), "wrong": 0, "missed": 30, "clarify": 0},
        {"thresholds": Thresholds(90, 75, 12), "wrong": 1, "missed": 5, "clarify": 2},
        {"thresholds": Thresholds(95, 75, 12), "wrong": 0, "missed": 400, "clarify": 0},
    ]

    assert best(rows)["thresholds"] == Thresholds(90, 75, 12)
