"""Eval metrics. Pure functions over the events of one turn and the rows of a
run. A metric is None for a question that has no data for it, and a rate counts only the
questions that have the data."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.application.chat import answer_numbers, text_numbers

_OUTCOMES = {
    "answer": "final",
    "reply": "final",
    # The guard refuses or the chat model replies without citations; both are correct.
    "no_answer": "refusal_or_reply",
    "refusal": "refusal",
    "clarify": "clarify",
}


def expected_outcome(expect: str) -> str:
    return _OUTCOMES[expect]


def _section_matches(section: str, expected: str) -> bool:
    number = section.split(" ", 1)[0]
    return number == expected or number.startswith(f"{expected}.")


def retrieval_hit(
    found: Sequence[tuple[str, str]], expected: Mapping[str, Sequence[str]]
) -> bool | None:
    """True when, for each expected drug, a found (drug, section) has one of its sections."""
    if not expected:
        return None
    return all(
        any(
            d.lower() == drug.lower() and any(_section_matches(s, e) for e in sections)
            for d, s in found
        )
        for drug, sections in expected.items()
    )


def citation_valid(
    citations: Sequence[str], sources: Sequence[Mapping[str, Any]], drugs: Sequence[str]
) -> bool | None:
    """Every citation names a sent source, and the source is about an expected drug."""
    if not citations:
        return None
    by_id = {s["id"]: s for s in sources}
    wanted = {d.lower() for d in drugs}
    return all(
        c in by_id and (not wanted or str(by_id[c]["drug"]).lower() in wanted) for c in citations
    )


def number_grounding(
    answer: str, citations: Sequence[str], sources: Sequence[Mapping[str, Any]]
) -> tuple[int, int]:
    """(numbers of the answer found in the cited excerpts, numbers of the answer). An answer
    without citations is not a sourced answer and gives (0, 0)."""
    if not citations:
        return 0, 0
    cited = " ".join(str(s["text"]) for s in sources if s["id"] in set(citations))
    known = text_numbers(cited)
    numbers = answer_numbers(answer)
    return len(numbers & known), len(numbers)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between the closest ranks."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _rate(values: Sequence[Any]) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(bool(v) for v in known) / len(known), 3) if known else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    seconds = [float(r["seconds"]) for r in rows]
    first = [float(r["first_token_seconds"]) for r in rows if r["first_token_seconds"] is not None]
    grounded = sum(r["numbers"][0] for r in rows)
    numbers = sum(r["numbers"][1] for r in rows)
    cost = sum(float(r["cost_usd"]) for r in rows)
    return {
        "questions": len(rows),
        "passed": sum(bool(r["passed"]) for r in rows),
        "outcome_accuracy": _rate([r["outcome_ok"] for r in rows]),
        "retrieval_hit_rate": _rate([r["retrieval_hit"] for r in rows]),
        "citation_validity_rate": _rate([r["citation_valid"] for r in rows]),
        "numeric_grounding_rate": round(grounded / numbers, 3) if numbers else None,
        "judge_correct_rate": _rate([r["judge"] for r in rows]),
        "latency_p50_seconds": _round(percentile(seconds, 50)),
        "latency_p95_seconds": _round(percentile(seconds, 95)),
        "first_token_p50_seconds": _round(percentile(first, 50)),
        "first_token_p95_seconds": _round(percentile(first, 95)),
        "cost_usd": round(cost, 4),
        "cost_per_question_usd": round(cost / len(rows), 4) if rows else None,
    }
