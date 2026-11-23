import asyncio
from collections.abc import Mapping, Sequence
from uuid import UUID

from app.application.retrieval import RetrievalResult, SearchMode
from app.domain.entities import Chunk, Message
from evals.judge import judge
from evals.metrics import (
    citation_valid,
    expected_outcome,
    number_grounding,
    percentile,
    retrieval_hit,
    summarize,
)
from evals.search import CosineSearch, ModeRetriever
from tests.support.factories import label_of, make_chunk


def source(id_: str, drug: str, section: str, text: str) -> dict[str, object]:
    return {"id": id_, "drug": drug, "section": section, "text": text}


def test_expected_outcome_maps_each_expectation() -> None:
    assert expected_outcome("answer") == "final"
    assert expected_outcome("reply") == "final"
    assert expected_outcome("no_answer") == "refusal_or_reply"
    assert expected_outcome("refusal") == "refusal"
    assert expected_outcome("clarify") == "clarify"


def test_retrieval_hit_needs_an_expected_section_for_every_expected_drug() -> None:
    found = [("Lexapro", "2.1"), ("Celexa", "5.1"), ("Celexa", "2")]
    assert retrieval_hit(found, {"Lexapro": ["2.1"], "Celexa": ["2"]}) is True
    assert retrieval_hit(found, {"Lexapro": ["2.1"], "Celexa": ["6"]}) is False
    assert retrieval_hit([("Singulair", "BW")], {"Singulair": ["BW", "5.1"]}) is True
    assert retrieval_hit(found, {}) is None


def test_a_section_matches_only_itself_not_its_subsections() -> None:
    assert retrieval_hit([("Lexapro", "2.1")], {"Lexapro": ["2"]}) is False
    assert retrieval_hit([("Lipitor", "20")], {"Lipitor": ["2"]}) is False


def test_the_drug_match_keeps_the_case_so_two_labels_of_one_name_differ() -> None:
    # "Ozempic" is the injection label, "OZEMPIC" the tablet label.
    assert retrieval_hit([("Ozempic", "2.2")], {"OZEMPIC": ["2.2"]}) is False
    sources = [source("S1", "Ozempic", "2.2 Dosage", "x")]
    assert citation_valid(["S1"], sources, ["OZEMPIC"]) is False
    assert citation_valid(["S1"], sources, ["Ozempic"]) is True


def test_a_citation_is_valid_when_it_was_sent_and_names_an_expected_drug() -> None:
    sources = [
        source("S1", "Plavix", "7.2 CYP2C19 Inhibitors", "x"),
        source("S2", "Zoloft", "6", "y"),
    ]
    assert citation_valid(["S1"], sources, ["Plavix"]) is True
    assert citation_valid(["S1", "S3"], sources, ["Plavix"]) is False
    assert citation_valid(["S2"], sources, ["Plavix"]) is False
    assert citation_valid(["S2"], sources, []) is True
    assert citation_valid([], sources, ["Plavix"]) is None


def test_number_grounding_counts_answer_numbers_found_in_the_cited_sources() -> None:
    sources = [source("S1", "Lipitor", "2", "10 or 20 mg once daily"), source("S2", "x", "2", "80")]
    answer = "Start with 10 mg or 40 mg [S1]. Section 2.1 says so [S1]."
    # 10 is grounded; 40 and the section number 2.1 are not (the answer check counts them too);
    # 80 is only in S2, which is not cited; the marker S1 is not a number.
    assert number_grounding(answer, ["S1"], sources) == (1, 3)
    # A reply without citations (a greeting) is not a sourced answer, so it does not count.
    assert number_grounding("I answer 24 hours a day.", [], sources) == (0, 0)


def test_percentile_interpolates_and_handles_empty_input() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([5.0], 95) == 5.0
    assert percentile([], 50) is None


def test_summarize_reports_rates_over_the_questions_that_have_the_data() -> None:
    rows: list[dict[str, object]] = [
        {
            "passed": True,
            "outcome_ok": True,
            "retrieval_hit": True,
            "citation_valid": True,
            "numbers": [2, 2],
            "judge": True,
            "seconds": 2.0,
            "first_token_seconds": 1.0,
            "cost_usd": 0.01,
        },
        {
            "passed": False,
            "outcome_ok": False,
            "retrieval_hit": False,
            "citation_valid": None,
            "numbers": [1, 2],
            "judge": None,
            "seconds": 4.0,
            "first_token_seconds": None,
            "cost_usd": 0.03,
        },
    ]
    summary = summarize(rows)
    assert summary["passed"] == 1
    assert summary["outcome_accuracy"] == 0.5
    assert summary["retrieval_hit_rate"] == 0.5
    assert summary["citation_validity_rate"] == 1.0
    assert summary["numeric_grounding_rate"] == 0.75
    assert summary["judge_correct_rate"] == 1.0
    assert summary["latency_p50_seconds"] == 3.0
    assert summary["first_token_p50_seconds"] == 1.0
    assert summary["cost_per_question_usd"] == 0.02


class JudgeModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[Sequence[Message]] = []

    async def complete(
        self, messages: Sequence[Message], *, json_schema: Mapping[str, object] | None = None
    ) -> str:
        self.prompts.append(messages)
        return self.reply


def test_the_judge_reads_a_verdict_and_treats_bad_output_as_unknown() -> None:
    good = JudgeModel('{"correct": true, "reason": "same dose"}')
    assert asyncio.run(judge(good, "Q?", "10 mg", "10 mg [S1]")) == (True, "same dose")
    assert "10 mg" in good.prompts[0][-1].content

    bad = JudgeModel("not json")
    verdict, reason = asyncio.run(judge(bad, "Q?", "10 mg", "10 mg"))
    assert verdict is None
    assert reason


class FakeSearch:
    async def vector_search(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[Chunk]:
        raise AssertionError("not used")

    async def text_search(self, query: str, labels: Sequence[UUID], limit: int) -> list[Chunk]:
        return [make_chunk("bm25")]

    async def vector_search_each(
        self, embedding: Sequence[float], labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        raise AssertionError("not used")

    async def text_search_each(
        self, query: str, labels: Sequence[UUID], limit: int
    ) -> list[list[Chunk]]:
        return [[make_chunk("bm25")] for _ in labels]


def test_cosine_search_ranks_by_similarity_with_the_label_filter() -> None:
    near = make_chunk("near", drug="Lipitor")
    far = make_chunk("far", drug="Lipitor")
    other = make_chunk("other", drug="Zoloft")
    search = CosineSearch(
        FakeSearch(), [(near, (1.0, 0.0)), (far, (0.0, 1.0)), (other, (1.0, 0.1))]
    )

    ranked = asyncio.run(search.vector_search((2.0, 0.1), [label_of("Lipitor")], 5))
    assert [c.content for c in ranked] == ["near", "far"]
    assert [c.content for c in asyncio.run(search.vector_search((1.0, 0.0), [], 1))] == ["near"]
    assert [c.content for c in asyncio.run(search.text_search("q", [], 3))] == ["bm25"]


class InnerRetriever:
    def __init__(self) -> None:
        self.modes: list[SearchMode] = []

    async def retrieve(
        self,
        query: str,
        *,
        labels: Sequence[UUID] = (),
        section_hints: Sequence[str] = (),
        mode: SearchMode = SearchMode.HYBRID,
    ) -> RetrievalResult:
        self.modes.append(mode)
        return RetrievalResult(query, tuple(labels), tuple(section_hints), mode)


def test_the_mode_retriever_forces_the_mode_and_records_each_result() -> None:
    inner = InnerRetriever()
    retriever = ModeRetriever(inner, "vector")

    asyncio.run(retriever.retrieve("q", labels=[label_of("Lipitor")]))
    asyncio.run(retriever.retrieve("q2"))

    assert inner.modes == ["vector", "vector"]
    assert [r.query for r in retriever.take()] == ["q", "q2"]
    assert retriever.take() == []
