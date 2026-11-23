from evals.table import table


def report(label: str, mode: str, hit: float | None, cost: float) -> dict[str, object]:
    return {
        "label": label,
        "config": {"search_mode": mode, "grader_mode": "llm", "embedding_prefix": True},
        "summary": {
            "questions": 20,
            "passed": 18,
            "outcome_accuracy": 0.95,
            "retrieval_hit_rate": hit,
            "citation_validity_rate": 1.0,
            "numeric_grounding_rate": 0.9,
            "judge_correct_rate": None,
            "latency_p50_seconds": 8.1,
            "latency_p95_seconds": 12.0,
            "cost_per_question_usd": cost,
        },
    }


def test_the_table_has_one_row_per_run_and_a_dash_for_missing_values() -> None:
    lines = table([report("base", "hybrid", 0.9, 0.015), report("vector", "vector", None, 0.01)])

    assert lines[0].startswith("| Run | Search | Grader | Prefix | Passed |")
    assert lines[1].startswith("|---")
    assert lines[2] == (
        "| base | hybrid | llm | on | 18/20 | 95% | 90% | 100% | 90% | - | 8.1 | 12.0 | 0.0150 |"
    )
    assert "| vector | vector | llm | on | 18/20 | 95% | - |" in lines[3]
