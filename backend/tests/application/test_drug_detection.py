import uuid

import pytest

from app.application.drug_detection import MAX_CHOICES, DrugDetector, DrugEntry, product_key
from app.infrastructure.name_similarity import RapidFuzzSimilarity

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
    return DrugDetector(CATALOG, RapidFuzzSimilarity())


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


def test_one_edit_in_a_short_brand_name_is_found(detector: DrugDetector) -> None:
    # A swap in a six-letter name scores 83.3 ("celxea"), under the old fuzzy threshold of 85.
    assert detector.detect("What is the dose of celxea?").drugs == ("Celexa",)


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


def test_a_generic_name_inside_a_longer_one_is_another_drug() -> None:
    # omeprazole is not esomeprazole, venlafaxine is not desvenlafaxine; the scores are high.
    detector = DrugDetector(
        [
            DrugEntry(name="Nexium", brand="Nexium", generic="esomeprazole"),
            DrugEntry(name="Pristiq", brand="Pristiq", generic="desvenlafaxine"),
        ],
        RapidFuzzSimilarity(),
    )

    result = detector.detect("Compare omeprazole and venlafaxine")

    assert (result.drugs, result.ambiguous) == ((), ())
    assert result.not_in_corpus == ("omeprazole", "venlafaxine")
    # A misspelling of the longer name still finds it.
    assert detector.detect("esomeprazol dose").drugs == ("Nexium",)


INJECTION, TABLETS = uuid.uuid4(), uuid.uuid4()
OZEMPIC = [
    DrugEntry("Ozempic", "Ozempic", "semaglutide", label=INJECTION, form="INJECTION, SOLUTION"),
    DrugEntry("OZEMPIC", "OZEMPIC", "oral semaglutide", label=TABLETS, form="TABLET"),
]


def test_one_name_with_two_dosage_forms_asks_which_form() -> None:
    detector = DrugDetector(OZEMPIC, RapidFuzzSimilarity())

    for question in ("Ozempic dose", "ozempik dose"):
        result = detector.detect(question)
        assert result.drugs == ()
        assert result.ambiguous == ("Ozempic (injection)", "OZEMPIC (tablet)")


def test_the_named_form_or_a_clicked_candidate_picks_the_product() -> None:
    detector = DrugDetector(OZEMPIC, RapidFuzzSimilarity())

    for question in ("Ozempic tablets dose", "OZEMPIC (tablet)", "oral semaglutide dose"):
        result = detector.detect(question)
        assert (result.drugs, result.labels) == (("OZEMPIC",), (TABLETS,)), question
    both = detector.detect("Compare the Ozempic injection and the tablets")
    assert both.labels == (INJECTION, TABLETS)


def test_labels_of_one_product_give_its_preferred_label() -> None:
    # Entries come in preference order: the brand label first, then the generic labels.
    brand, generic = uuid.uuid4(), uuid.uuid4()
    detector = DrugDetector(
        [
            DrugEntry("Lipitor", "Lipitor", "atorvastatin calcium", label=brand, form="TABLET"),
            DrugEntry(
                "atorvastatin calcium",
                "",
                "atorvastatin calcium",
                label=generic,
                form="TABLET, FILM COATED",
            ),
        ],
        RapidFuzzSimilarity(),
    )

    for question in ("atorvastatin dose", "Lipitor dose", "Lipitor or atorvastatin?"):
        result = detector.detect(question)
        assert (result.drugs, result.labels) == (("Lipitor",), (brand,)), question


def test_a_product_is_its_ingredients_and_its_dosage_form() -> None:
    assert product_key("atorvastatin calcium", "TABLET, FILM COATED") == "atorvastatin|tablet"
    assert product_key("oral semaglutide", "TABLET") == "semaglutide|tablet"
    assert product_key("semaglutide", "INJECTION, SOLUTION") == "semaglutide|injection"
    assert (
        product_key("Hydrocodone Bitartrate and Acetaminophen", "TABLET")
        == "acetaminophen+hydrocodone|tablet"
    )


def test_exact_match_wins_over_the_outside_corpus_rule(detector: DrugDetector) -> None:
    # rosuvastatin ends like a drug name, but it is in the corpus.
    result = detector.detect("rosuvastatin dose")

    assert (result.drugs, result.not_in_corpus) == (("Crestor",), ())


def test_common_words_do_not_fuzzy_match(detector: DrugDetector) -> None:
    result = detector.detect("Can I take this tablet with water after a meal?")

    assert (result.drugs, result.ambiguous) == ((), ())


def test_ambiguous_word_is_kept_when_another_drug_matches(detector: DrugDetector) -> None:
    result = detector.detect("Compare Lipitor and hydrazine")

    assert result.drugs == ("Lipitor",)
    assert result.ambiguous == ("hydralazine hydrochloride", "hydroxyzine hydrochloride")


def test_ambiguous_word_next_to_a_named_drug_means_the_other_one(detector: DrugDetector) -> None:
    result = detector.detect("Compare hydralazine and hydrazine")

    assert result.drugs == ("hydralazine hydrochloride", "hydroxyzine hydrochloride")
    assert result.fuzzy == ("hydroxyzine hydrochloride",)
    assert result.ambiguous == ()


def test_catalog_names_each_label_once_with_its_generic_name() -> None:
    entries = [*CATALOG, DrugEntry(name="Lipitor", brand="Lipitor", generic="atorvastatin")]

    catalog = DrugDetector(entries, RapidFuzzSimilarity()).catalog()

    assert catalog[:3] == ["Celebrex (celecoxib)", "Celexa (citalopram)", "Crestor (rosuvastatin)"]
    assert catalog.count("Lipitor (atorvastatin)") == 1
    assert "hydralazine hydrochloride" in catalog
    assert len(catalog) == len(CATALOG)


def test_the_similarity_adapter_ranks_a_whole_list_above_a_floor() -> None:
    best = RapidFuzzSimilarity().best("lipitr", ["lipitor", "celexa", "lipitorr"], floor=70.0)

    assert [name for name, _ in best] == ["lipitor", "lipitorr"]
    assert all(score >= 70.0 for _, score in best)


def test_a_clarify_question_offers_at_most_five_candidates() -> None:
    # Seven look-alike names, all equally close to the question word.
    names = [f"zentrax{c}" for c in "abcdefg"]
    detector = DrugDetector([DrugEntry(n, n, n) for n in names], RapidFuzzSimilarity())

    result = detector.detect("What is the dose of zentrax?")

    assert result.drugs == ()
    assert len(result.ambiguous) == MAX_CHOICES == 5
