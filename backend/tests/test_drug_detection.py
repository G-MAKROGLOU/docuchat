import pytest

from app.application.drug_detection import DrugDetector, DrugEntry

CATALOG = [
    DrugEntry(name="Lipitor", brand="Lipitor", generic="atorvastatin"),
    DrugEntry(name="Crestor", brand="Crestor", generic="rosuvastatin"),
    DrugEntry(name="Eliquis", brand="Eliquis", generic="apixaban"),
    DrugEntry(name="Xarelto", brand="Xarelto", generic="rivaroxaban"),
    DrugEntry(name="Celebrex", brand="Celebrex", generic="celecoxib"),
    DrugEntry(name="Celexa", brand="Celexa", generic="citalopram"),
    DrugEntry(name="Toprol XL", brand="Toprol XL", generic="metoprolol succinate"),
    DrugEntry(name="hydralazine hydrochloride", brand="", generic="hydralazine hydrochloride"),
    DrugEntry(name="hydroxyzine hydrochloride", brand="", generic="hydroxyzine hydrochloride"),
]


@pytest.fixture
def detector() -> DrugDetector:
    return DrugDetector(CATALOG)


def test_exact_brand_name_any_case(detector: DrugDetector) -> None:
    result = detector.detect("What is the starting dose of LIPITOR?")

    assert result.drugs == ("Lipitor",)
    assert result.fuzzy == ()
    assert result.ambiguous == ()


def test_exact_generic_name_maps_to_the_label(detector: DrugDetector) -> None:
    assert detector.detect("Can atorvastatin cause muscle pain?").drugs == ("Lipitor",)


def test_generic_name_without_the_salt(detector: DrugDetector) -> None:
    assert detector.detect("Side effects of hydralazine?").drugs == ("hydralazine hydrochloride",)


def test_multi_word_brand(detector: DrugDetector) -> None:
    assert detector.detect("Can Toprol XL be crushed?").drugs == ("Toprol XL",)


def test_two_drugs_in_question_order(detector: DrugDetector) -> None:
    result = detector.detect("Compare bleeding risk of Xarelto and Eliquis")

    assert result.drugs == ("Xarelto", "Eliquis")


def test_one_close_fuzzy_candidate_is_used_and_marked(detector: DrugDetector) -> None:
    result = detector.detect("Is lipitr taken at night?")

    assert result.drugs == ("Lipitor",)
    assert result.fuzzy == ("Lipitor",)


def test_look_alike_with_a_clear_winner_is_fuzzy_not_ambiguous(detector: DrugDetector) -> None:
    # celebxa: Celexa 92.3, Celebrex 80.0 (margin 12.3)
    result = detector.detect("What does celebxa treat?")

    assert result.drugs == ("Celexa",)
    assert result.ambiguous == ()


def test_two_close_candidates_are_ambiguous(detector: DrugDetector) -> None:
    # hydrazine: hydralazine 90.0, hydroxyzine 80.0 (margin 10)
    result = detector.detect("What is the dose of hydrazine?")

    assert result.drugs == ()
    assert result.ambiguous == ("hydralazine hydrochloride", "hydroxyzine hydrochloride")


def test_no_drug_gives_no_filter(detector: DrugDetector) -> None:
    result = detector.detect("What is a statin and how do they work during pregnancy?")

    assert (result.drugs, result.fuzzy, result.ambiguous, result.not_in_corpus) == ((), (), (), ())


def test_named_drug_outside_the_corpus_is_marked(detector: DrugDetector) -> None:
    result = detector.detect("Is ramipril safe with metformin?")

    assert result.drugs == ()
    assert result.not_in_corpus == ("ramipril", "metformin")


def test_exact_match_wins_over_the_outside_corpus_rule(detector: DrugDetector) -> None:
    # rosuvastatin ends like a drug name, but it is in the corpus.
    result = detector.detect("rosuvastatin dose")

    assert (result.drugs, result.not_in_corpus) == (("Crestor",), ())


def test_common_words_do_not_fuzzy_match(detector: DrugDetector) -> None:
    result = detector.detect("Can I take this tablet with water after a meal?")

    assert (result.drugs, result.ambiguous) == ((), ())
