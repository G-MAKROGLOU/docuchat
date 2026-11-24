"""Retrieval eval with no LLM calls: questions generated from the library, gold keys that a
re-ingest keeps (the label set ID and a section number), recall@8 and MRR.

For each ingested label and each topic section it has, one question; the drug name rotates over
brand, generic, a one-edit typo and lower case. Comparison questions pair labels that share a
topic. The run uses the real drug detector, topic hints and hybrid retrieval, so it measures what
a chat turn searches (without the rewrite or intake query).
  python -m evals.retrieval_set"""

import asyncio
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from app.application.topics import section_hints
from app.config import get_settings
from app.domain.documents import DocumentStatus
from app.infrastructure.database import build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.runtime_defaults import default_runtime_settings
from app.wiring import (
    detector_thresholds,
    drug_detector,
    retrieval_service,
)
from evals.detector_calibration import typo_variants

# Topic: the section that answers it, and one question per name.
TOPICS = {
    "dosage": ("2", "What is the recommended dose of {}?"),
    "contraindications": ("4", "Who should not take {}?"),
    "warnings": ("5", "What are the serious warnings and precautions for {}?"),
    "side_effects": ("6", "What are the most common side effects of {}?"),
    "interactions": ("7", "Which other medicines interact with {}?"),
    "pregnancy": ("8.1", "Is it safe to take {} during pregnancy?"),
    "lactation": ("8.2", "Can I breastfeed while taking {}?"),
    "children": ("8.4", "Can children take {}?"),
    "overdose": ("10", "What happens in an overdose of {}?"),
    "storage": ("16", "How should I store {}?"),
}
COMPARISONS = {
    "side_effects": "Compare the side effects of {} and {}",
    "interactions": "Compare the drug interactions of {} and {}",
}
NAME_KINDS = ("brand", "generic", "typo", "lower")
TOP = 8  # the excerpts that the answer model reads


@dataclass(frozen=True, slots=True)
class Label:
    source_id: str  # the DailyMed set ID: the same after a re-ingest
    brand: str
    generic: str
    sections: frozenset[str]


@dataclass(frozen=True, slots=True)
class Gold:
    source_id: str
    section: str


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    text: str
    topic: str
    kind: str  # single, comparison
    name_kind: str  # brand, generic, typo, lower, both
    gold: tuple[Gold, ...]


def section_matches(found: str, expected: str) -> bool:
    """A found section answers when it is the expected one or one of its subsections."""
    return found == expected or found.startswith(f"{expected}.")


def _has(label: Label, section: str) -> bool:
    return any(section_matches(s, section) for s in label.sections)


def _name(label: Label, kind: str) -> tuple[str, str]:
    brand = label.brand or label.generic
    if kind == "generic" and label.generic:
        return label.generic.lower(), kind
    if kind == "typo" and len(brand) >= 5:  # noqa: PLR2004
        variants = typo_variants(brand.lower())
        if variants:
            return variants[0], kind
    if kind == "lower":
        return brand.lower(), kind
    return brand, "brand"


def build_questions(labels: Sequence[Label]) -> list[Question]:
    ordered = sorted(labels, key=lambda lb: (lb.brand or lb.generic).lower())
    questions: list[Question] = []
    for i, label in enumerate(ordered):
        for j, (topic, (section, template)) in enumerate(TOPICS.items()):
            if not _has(label, section):
                continue
            name, kind = _name(label, NAME_KINDS[(i + j) % len(NAME_KINDS)])
            questions.append(
                Question(
                    id=f"{label.source_id}:{topic}",
                    text=template.format(name),
                    topic=topic,
                    kind="single",
                    name_kind=kind,
                    gold=(Gold(label.source_id, section),),
                )
            )
    for topic, template in COMPARISONS.items():
        section = TOPICS[topic][0]
        able = [lb for lb in ordered if _has(lb, section)]
        for a, b in zip(able[::2], able[1::2], strict=False):
            questions.append(
                Question(
                    id=f"{a.source_id}+{b.source_id}:{topic}",
                    text=template.format(a.brand or a.generic, b.brand or b.generic),
                    topic=topic,
                    kind="comparison",
                    name_kind="both",
                    gold=(Gold(a.source_id, section), Gold(b.source_id, section)),
                )
            )
    return questions


def _gold_found(item: tuple[str, str], gold: Gold) -> bool:
    return item[0] == gold.source_id and section_matches(item[1], gold.section)


def gold_hits(ranked: Sequence[tuple[str, str]], gold: Sequence[Gold]) -> int:
    """How many gold keys have a (source ID, section) in the ranked list."""
    return sum(any(_gold_found(item, g) for item in ranked) for g in gold)


def reciprocal_rank(ranked: Sequence[tuple[str, str]], gold: Sequence[Gold]) -> float:
    """Mean over the gold keys of 1 / the rank of the first match (0 when absent)."""
    ranks = [
        next((1 / r for r, item in enumerate(ranked, start=1) if _gold_found(item, g)), 0.0)
        for g in gold
    ]
    return mean(ranks) if ranks else 0.0


def _summary(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, float]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return {
        name: {
            "questions": len(items),
            "recall_at_8": round(mean(r["recall"] for r in items), 3),
            "mrr": round(mean(r["mrr"] for r in items), 3),
            "clarify": sum(r["clarify"] for r in items),
        }
        for name, items in sorted(groups.items())
    }


async def _run() -> dict[str, Any]:
    settings = get_settings()
    async with build_pool(settings) as pool:
        documents = [
            d
            for d in await PostgresDocumentRepository(pool).list_all()
            if d.status is DocumentStatus.INGESTED
        ]
        source_of = {d.id: d.source_id for d in documents}
        async with pool.connection() as conn:
            cursor = await conn.execute("SELECT DISTINCT document_id, section_number FROM chunks")
            sections: dict[str, set[str]] = defaultdict(set)
            for document_id, section in await cursor.fetchall():
                sections[source_of.get(document_id, "")].add(section)
        labels = [
            Label(d.source_id, d.brand_name, d.generic_name, frozenset(sections[d.source_id]))
            for d in documents
        ]
        questions = build_questions(labels)
        detector = drug_detector(documents, detector_thresholds(settings))
        service = retrieval_service(settings, pool, default_runtime_settings(settings))
        rows = []
        for q in questions:
            detection = detector.detect(q.text)
            clarify = bool(detection.ambiguous) and not detection.labels
            result = await service.retrieve(
                q.text,
                labels=detection.labels,
                section_hints=section_hints(q.text, comparing=len(detection.labels) > 1),
            )
            selected = [
                (source_of[f.chunk.document_id], f.chunk.section_number) for f in result.selected
            ]
            ranked = [
                (source_of[f.chunk.document_id], f.chunk.section_number) for f in result.candidates
            ]
            rows.append(
                {
                    **asdict(q),
                    "detected": list(detection.drugs),
                    "clarify": clarify,
                    "recall": 0.0 if clarify else gold_hits(selected[:TOP], q.gold) / len(q.gold),
                    "mrr": 0.0 if clarify else reciprocal_rank(ranked, q.gold),
                }
            )
    overall = _summary(({**r, "all": "all"} for r in rows), "all")["all"]
    return {
        "labels": len(labels),
        "questions": len(rows),
        "overall": overall,
        "by_topic": _summary(rows, "topic"),
        "by_name_kind": _summary(rows, "name_kind"),
        "misses": [
            {"id": r["id"], "text": r["text"], "detected": r["detected"], "clarify": r["clarify"]}
            for r in rows
            if r["recall"] < 1.0
        ],
    }


def main() -> int:
    report = asyncio.run(_run())
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    out = Path(__file__).parent / "results" / f"{stamp}-retrieval-set.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"labels {report['labels']} questions {report['questions']} "
        f"recall@8 {report['overall']['recall_at_8']} mrr {report['overall']['mrr']} "
        f"clarify {report['overall']['clarify']}"
    )
    for group in ("by_topic", "by_name_kind"):
        for name, values in report[group].items():
            print(f"  {group[3:]:9} {name:18} {values}")
    print(f"misses {len(report['misses'])}; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
