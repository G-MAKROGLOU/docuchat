"""Markdown table of eval runs, one row per result file.
python -m evals.table evals/results/A.json evals/results/B.json > ablation.md"""

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HEADER = (
    "| Run | Search | Grader | Prefix | Passed | Outcome | Retrieval hit | Citation valid "
    "| Numbers grounded | Judge correct | p50 s | p95 s | USD per question |"
)


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _number(value: float | None, digits: int) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def row(report: Mapping[str, Any]) -> str:
    c, s = report["config"], report["summary"]
    cells = [
        report["label"],
        c["search_mode"],
        c["grader_mode"],
        "on" if c["embedding_prefix"] else "off",
        f"{s['passed']}/{s['questions']}",
        _percent(s["outcome_accuracy"]),
        _percent(s["retrieval_hit_rate"]),
        _percent(s["citation_validity_rate"]),
        _percent(s["numeric_grounding_rate"]),
        _percent(s["judge_correct_rate"]),
        _number(s["latency_p50_seconds"], 1),
        _number(s["latency_p95_seconds"], 1),
        _number(s["cost_per_question_usd"], 4),
    ]
    return "| " + " | ".join(cells) + " |"


def table(reports: Sequence[Mapping[str, Any]]) -> list[str]:
    separator = "|" + "|".join("---" for _ in HEADER.strip("|").split("|")) + "|"
    return [HEADER, separator, *(row(r) for r in reports)]


def main(argv: Sequence[str] | None = None) -> int:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    print("\n".join(table(reports)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
