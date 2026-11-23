"""Drug detector calibration. No model calls, so it costs nothing.

The labelled cases come from the library itself:
- typo: one-edit misspellings of every brand and generic name; expected: that drug.
- outside: real drug names that are not in the library; expected: no library drug.
- word: common words of label questions; expected: no drug.
A grid of thresholds is scored on them. The best setting has the lowest weighted cost (see
WRONG_COST), so a wrong medicine weighs far more than a missed typo.
  python -m evals.detector_calibration"""

import asyncio
import itertools
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.drug_detection import (
    DrugDetection,
    DrugDetector,
    DrugEntry,
)
from app.config import get_settings
from app.domain.documents import DocumentStatus
from app.domain.ports import NameSimilarity
from app.infrastructure.database import build_pool
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.name_similarity import RapidFuzzSimilarity
from app.wiring import detector_thresholds

QUESTION = "What is the dose of {}?"
# The detector ignores shorter names.
_MIN_KEY = 4

# Real medicines that are not in the library. Some are close to library names on purpose
# (omeprazole and esomeprazole, venlafaxine and desvenlafaxine, clonazepam and diazepam).
OUTSIDE = [
    "tylenol", "acetaminophen", "advil", "ibuprofen", "motrin", "aleve", "naproxen", "aspirin",
    "metformin", "glucophage", "amoxicillin", "augmentin", "prednisone", "omeprazole",
    "prilosec", "lansoprazole", "lasix", "furosemide", "norvasc", "amlodipine", "zocor",
    "simvastatin", "pravastatin", "benadryl", "claritin", "loratadine", "zyrtec", "cetirizine",
    "allegra", "ventolin", "albuterol", "humira", "ozempic", "semaglutide", "mounjaro",
    "viagra", "sildenafil", "lyrica", "pregabalin", "cymbalta", "duloxetine", "effexor",
    "venlafaxine", "klonopin", "clonazepam", "ativan", "lorazepam", "adderall", "tramadol",
    "oxycodone", "atenolol", "carvedilol", "cipro", "ciprofloxacin", "doxycycline", "keflex",
    "cephalexin", "flagyl", "metronidazole", "diflucan", "fluconazole", "pepcid", "famotidine",
    "plaquenil", "candesartan", "irbesartan", "olmesartan", "ramipril",
    "enalapril", "dabigatran", "pradaxa", "edoxaban", "canagliflozin", "saxagliptin",
    "trazodone", "risperidone", "haloperidol", "lithium", "valproate", "carbamazepine",
]  # fmt: skip

# Words of label questions that are not drug names.
WORDS = [
    "dosage", "tablets", "capsules", "pregnancy", "pregnant", "children", "kidney", "liver",
    "warnings", "interactions", "alcohol", "grapefruit", "breastfeeding", "elderly",
    "overdose", "missed", "allergy", "headache", "nausea", "dizziness", "insomnia", "anxiety",
    "depression", "diabetes", "cholesterol", "blood", "pressure", "seizures", "migraine",
    "asthma", "influenza", "shingles", "herpes", "arthritis", "cancer", "breast", "heart",
    "failure", "stroke", "bleeding", "surgery", "weight", "maximum", "starting", "recommended",
    "daily", "twice", "morning", "evening", "food", "stomach", "water", "contraindications",
    "boxed", "label", "compare", "difference", "between", "generic", "brand", "ingredients",
    "inactive", "lactose", "storage", "temperature", "infection", "fever", "pain", "sleep",
    "pediatric", "renal", "hepatic", "adverse", "reactions", "effects", "patients", "taking",
    "tablet", "injection", "vaccine", "supplement", "vitamin", "smoking", "driving",
    "statins", "antidepressant", "anticoagulant", "inhibitor", "blocker", "celery", "cilantro",
]  # fmt: skip

_NEIGHBOURS = dict(zip("aeioubcdgklmnprstvxz", "eaouisvsfjknmoetrcbz", strict=True))


@dataclass(frozen=True, slots=True)
class Case:
    word: str
    expected: str | None  # the canonical drug name, or None for no library drug
    kind: str  # typo, outside, word


@dataclass(frozen=True, slots=True)
class Thresholds:
    fuzzy: float
    floor: float
    margin: float


def typo_variants(word: str) -> list[str]:
    """One-edit misspellings: two deletions, a swap, a wrong letter, a doubled letter."""
    n = len(word)
    mid = n // 2
    found = [
        word[: n // 3] + word[n // 3 + 1 :],
        word[: 2 * n // 3] + word[2 * n // 3 + 1 :],
        word[: mid - 1] + word[mid] + word[mid - 1] + word[mid + 1 :],
        word[:mid] + _NEIGHBOURS.get(word[mid], "e") + word[mid + 1 :],
        word[:mid] + word[mid] + word[mid:],
    ]
    return [v for v in dict.fromkeys(found) if v != word]


def _name_keys(entry: DrugEntry) -> set[str]:
    return {
        k
        for k in (entry.brand.lower(), entry.generic.lower())
        if len(k) >= _MIN_KEY and " " not in k
    }


def build_cases(
    entries: Sequence[DrugEntry], outside: Iterable[str] = OUTSIDE, words: Iterable[str] = WORDS
) -> list[Case]:
    keys = {k for e in entries for k in _name_keys(e)}
    cases = [
        Case(variant, entry.name, "typo")
        for entry in entries
        for key in sorted(_name_keys(entry))
        for variant in typo_variants(key)
        if variant not in keys
    ]
    cases += [Case(w, None, "outside") for w in outside if w not in keys]
    cases += [Case(w, None, "word") for w in words if w not in keys]
    return list(dict.fromkeys(cases))


def classify(detection: DrugDetection, expected: str | None) -> str:
    if expected is None:
        if detection.drugs:
            return "wrong"
        return "clarify" if detection.ambiguous else "clean"
    # Two labels of one brand can differ in case ("OZEMPIC" and "Ozempic").
    want = expected.casefold()
    drugs = {d.casefold() for d in detection.drugs}
    if want in drugs:
        return "correct" if len(drugs) == 1 else "wrong"
    if drugs:
        return "wrong"
    return "clarify" if want in {d.casefold() for d in detection.ambiguous} else "missed"


class CachedSimilarity:
    """Scores do not depend on the thresholds, so the grid computes each pair once."""

    def __init__(self, inner: NameSimilarity) -> None:
        self._inner = inner
        self._scores: dict[tuple[str, str], float] = {}

    def ratio(self, a: str, b: str) -> float:
        key = (a, b)
        if key not in self._scores:
            self._scores[key] = self._inner.ratio(a, b)
        return self._scores[key]

    def best(self, query: str, choices: Sequence[str], floor: float) -> list[tuple[str, float]]:
        scores = ((choice, self.ratio(query, choice)) for choice in choices)
        return [(choice, score) for choice, score in scores if score >= floor]


def _detector(
    entries: Sequence[DrugEntry], similarity: NameSimilarity, t: Thresholds
) -> DrugDetector:
    calibrated = detector_thresholds(get_settings())
    return DrugDetector(
        list(entries),
        similarity,
        replace(
            calibrated, fuzzy_threshold=t.fuzzy, candidate_floor=t.floor, ambiguity_margin=t.margin
        ),
    )


def evaluate(
    entries: Sequence[DrugEntry],
    similarity: NameSimilarity,
    thresholds: Thresholds,
    cases: Sequence[Case],
) -> dict[str, dict[str, int]]:
    detector = _detector(entries, similarity, thresholds)
    counts: dict[str, Counter[str]] = {}
    for case in cases:
        result = classify(detector.detect(QUESTION.format(case.word)), case.expected)
        counts.setdefault(case.kind, Counter())[result] += 1
    return {kind: dict(counter) for kind, counter in counts.items()}


def _row(thresholds: Thresholds, counts: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    return {
        "thresholds": thresholds,
        "wrong": sum(c.get("wrong", 0) for c in counts.values()),
        "correct": counts.get("typo", {}).get("correct", 0),
        "missed": sum(c.get("missed", 0) for c in counts.values()),
        "clarify": sum(c.get("clarify", 0) for c in counts.values()),
        "counts": counts,
    }


# A wrong drug gives an answer about another medicine; a miss gives an unfiltered search or a
# refusal; a clarify question costs the user one click. ASSUMED weights, for the author to review.
WRONG_COST = 10.0
CLARIFY_COST = 0.5


def cost(row: Mapping[str, Any]) -> float:
    return float(WRONG_COST * row["wrong"] + row["missed"] + CLARIFY_COST * row["clarify"])


def _rank(row: Mapping[str, Any]) -> tuple[float, int]:
    return cost(row), row["wrong"]


def best(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return min(rows, key=_rank)


def grid() -> list[Thresholds]:
    fuzzy = [75.0 + 2.5 * i for i in range(9)]  # 75 to 95
    floors = [60.0 + 5 * i for i in range(6)]  # 60 to 85
    margins = [4.0 + 2 * i for i in range(9)]  # 4 to 20
    return [
        Thresholds(f, fl, m) for f, fl, m in itertools.product(fuzzy, floors, margins) if fl <= f
    ]


def errors(
    entries: Sequence[DrugEntry],
    similarity: NameSimilarity,
    thresholds: Thresholds,
    cases: Sequence[Case],
) -> list[dict[str, Any]]:
    detector = _detector(entries, similarity, thresholds)
    out = []
    for case in cases:
        detection = detector.detect(QUESTION.format(case.word))
        result = classify(detection, case.expected)
        if result not in ("correct", "clean"):
            out.append({**asdict(case), "result": result, "detected": detection.drugs,
                        "ambiguous": detection.ambiguous})  # fmt: skip
    return out


async def _entries() -> list[DrugEntry]:
    settings = get_settings()
    async with build_pool(settings) as pool:
        documents = await PostgresDocumentRepository(pool).list_all()
    return [
        DrugEntry(name=d.brand_name or d.generic_name, brand=d.brand_name, generic=d.generic_name)
        for d in documents
        if d.status is DocumentStatus.INGESTED
    ]


def main() -> int:
    entries = asyncio.run(_entries())
    cases = build_cases(entries)
    similarity = CachedSimilarity(RapidFuzzSimilarity())
    rows = [_row(t, evaluate(entries, similarity, t, cases)) for t in grid()]
    now = detector_thresholds(get_settings())
    current = next(
        r
        for r in rows
        if r["thresholds"]
        == Thresholds(now.fuzzy_threshold, now.candidate_floor, now.ambiguity_margin)
    )
    chosen = best(rows)
    kinds = Counter(c.kind for c in cases)
    report = {
        "labels": len(entries),
        "cases": dict(kinds),
        "current": current,
        "best": chosen,
        "best_errors": errors(entries, similarity, chosen["thresholds"], cases),
        "current_errors": errors(entries, similarity, current["thresholds"], cases),
        "top": sorted(rows, key=_rank)[:10],
    }
    text = json.dumps(report, indent=2, default=asdict)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    out = Path(__file__).parent / "results" / f"{stamp}-detector-calibration.json"
    out.write_text(text + "\n", encoding="utf-8")
    for name, row in (("current", current), ("best", chosen)):
        print(name, row["thresholds"], "cost", cost(row), "wrong", row["wrong"],
              "missed", row["missed"], "clarify", row["clarify"], row["counts"])  # fmt: skip
    print(f"cases {dict(kinds)}; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
