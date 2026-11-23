"""Answer-quality eval: run each question as a new conversation and
score it. Real model calls, so it costs credit. Writes evals/results/<time>-<label>.json.
The default set is the golden set (golden_set.jsonl); --questions evals/questions.json runs the
older 20-question set.
  python -m evals.run --label base
  python -m evals.run --label vector --search-mode vector
  python -m evals.run --label no-grader --grader-mode off
  python -m evals.run --label no-prefix --no-prefix
Other flags: --rewrite-model, --grade-model, --judge-model, --questions, --out."""

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY

from app.application.retrieval import RetrievalService, SearchMode
from app.config import Settings, get_settings
from app.domain.entities import ModelRole
from app.domain.runtime_settings import RuntimeSettings
from app.infrastructure.chunk_search import PostgresChunkSearch
from app.infrastructure.database import Connections, build_pool
from app.infrastructure.logging import configure_logging
from app.infrastructure.models import ModelFactory
from app.infrastructure.tracing import build_tracer
from app.wiring import chat_service, retrieval_service, runtime_settings, search_limits
from evals.judge import judge
from evals.metrics import (
    citation_valid,
    expected_outcome,
    number_grounding,
    retrieval_hit,
    section_matches,
    summarize,
)
from evals.search import CosineSearch, ModeRetriever, stored_chunks, unprefixed_vectors

EVALS = Path(__file__).parent
QUESTIONS = EVALS / "golden_set.jsonl"
CACHE = EVALS / "cache"


@dataclass(frozen=True, slots=True)
class Result:
    outcome: str  # final, refusal, clarify, error, or none
    answer: str
    citations: list[str]
    reason: str | None


def load_questions(path: Path) -> list[dict[str, Any]]:
    """The questions in the runner's fields. A .jsonl file is the golden set: one
    case per line; its history turns run first, in the same conversation."""
    if path.suffix != ".jsonl":
        questions: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["questions"]
        return questions
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [
        {
            "id": c["id"],
            "text": c["question"],
            "type": c["type"],
            "expect": c["expected_outcome"],
            "drugs": c.get("expected_drugs", []),
            "sections": c.get("expected_sections", {}),
            "reference": c.get("reference_answer", ""),
            "refusal": c.get("expected_refusal"),
            "history": [text for role, text in c.get("history", []) if role == "user"],
        }
        for c in cases
    ]


def result_of(events: list[dict[str, Any]]) -> Result:
    """The outcome of one turn. A clarify turn also sends its question as a final event; it
    stays a clarify outcome."""
    result = Result("none", "", [], None)
    for event in events:
        kind = event["type"]
        if kind == "final" and result.outcome != "clarify":
            result = Result("final", event["answer"], event["citations"], None)
        elif kind in ("refusal", "clarify", "error"):
            result = Result(kind, event.get("message", ""), [], event.get("reason"))
    return result


def _missing_outcome(question: dict[str, Any], result: Result) -> list[str] | None:
    """For a question that expects no cited answer: what is wrong ([] when nothing). None for
    an answer question."""
    expect = question["expect"]
    wanted = question.get("refusal")
    if expect == "clarify":
        return [] if result.outcome == "clarify" else ["clarify"]
    if expect == "refusal":
        if result.outcome != "refusal":
            return ["refusal"]
        return [f"refusal {wanted}"] if wanted and result.reason != wanted else []
    if expect == "no_answer":
        return ["no cited answer"] if result.outcome == "final" and result.citations else []
    if expect == "reply":
        return [] if result.outcome == "final" and not result.citations else ["reply"]
    return None


def score(
    question: dict[str, Any], result: Result, sources: Sequence[Mapping[str, Any]] = ()
) -> tuple[bool, list[str]]:
    """Pass or fail, and what was missing. An answer must cite each expected drug at one of
    its expected sections."""
    other = _missing_outcome(question, result)
    if other is not None:
        return not other, other
    if result.outcome != "final":
        return False, [f"outcome {result.outcome}"]
    if not result.citations:
        return False, ["citations"]
    cited = [s for s in sources if s["id"] in set(result.citations)]
    missing = [
        f"cited {drug} {' or '.join(sections)}"
        for drug, sections in question.get("sections", {}).items()
        if not any(
            s["drug"] == drug and any(section_matches(str(s["section"]), e) for e in sections)
            for s in cited
        )
    ]
    missing += [
        "|".join(group)
        for group in question.get("facts", [])
        if not any(re.search(pattern, result.answer, re.IGNORECASE) for pattern in group)
    ]
    return not missing, missing


def _cost() -> float:
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name == "docuchat_llm_cost_usd":
            total += sum(s.value for s in metric.samples if s.name.endswith("_total"))
    return total


async def _retrieval(
    settings: Settings, pool: Connections, runtime: RuntimeSettings, no_prefix: bool
) -> RetrievalService:
    if not no_prefix:
        return retrieval_service(settings, pool, runtime)
    embedder = ModelFactory(
        settings.model_copy(update={"embedding_model": runtime.embedding_model})
    ).embedder()
    chunks = await stored_chunks(pool, runtime.embedding_model)
    cache = CACHE / f"unprefixed-{runtime.embedding_model.replace('/', '_')}.json"
    vectors = await unprefixed_vectors(chunks, embedder, cache)
    search = CosineSearch(
        PostgresChunkSearch(
            pool,
            runtime.embedding_model,
            title_boost=settings.search_title_boost,
            phrase_boost=settings.search_phrase_boost,
        ),
        vectors,
    )
    return RetrievalService(search, embedder, top_k=runtime.top_k, limits=search_limits(settings))


def _outcome_ok(expect: str, result: Result) -> bool:
    wanted = expected_outcome(expect)
    if wanted == "refusal_or_reply":
        return result.outcome == "refusal" or (result.outcome == "final" and not result.citations)
    return result.outcome == wanted


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    questions = load_questions(args.questions)
    tracer = build_tracer(settings)
    rows: list[dict[str, Any]] = []
    async with build_pool(settings) as pool:
        runtime = await runtime_settings(settings, pool)
        runtime = replace(
            runtime,
            rewrite_model=args.rewrite_model or runtime.rewrite_model,
            grade_model=args.grade_model or runtime.grade_model,
            grader_mode=args.grader_mode or runtime.grader_mode,
        )
        retriever = ModeRetriever(
            await _retrieval(settings, pool, runtime, args.no_prefix), args.search_mode
        )
        service = chat_service(settings, pool, tracer, runtime, retriever)
        judge_id = args.judge_model or runtime.generate_model
        judge_model = (
            ModelFactory(settings.model_copy(update={"llm_grade_model": judge_id}))
            .chat_models()
            .for_role(ModelRole.GRADE)
        )
        for question in questions:
            conversation = await service.start()
            for earlier in question.get("history", []):
                async for _ in await service.ask(conversation, earlier):
                    pass
            retriever.take()  # the searches of the earlier turns do not count
            cost_before, started = _cost(), time.perf_counter()
            first_token: float | None = None
            sources: list[dict[str, Any]] = []
            events: list[dict[str, Any]] = []
            async for event in await service.ask(conversation, question["text"]):
                events.append(event)
                if event["type"] == "token" and first_token is None:
                    first_token = time.perf_counter() - started
                elif event["type"] == "sources":
                    sources = event["items"]
            result = result_of(events)
            seconds = time.perf_counter() - started
            cost = _cost() - cost_before
            searches = retriever.take()
            expected: dict[str, list[str]] = question.get("sections", {})
            found = [
                (f.chunk.drug_name, f.chunk.section_number)
                for f in (searches[0].selected if searches else [])
            ]
            verdict: bool | None = None
            reason = ""
            if question.get("reference") and result.outcome == "final":
                verdict, reason = await judge(
                    judge_model, question["text"], question["reference"], result.answer
                )
            passed, missing = score(question, result, sources)
            rows.append(
                {
                    "id": question["id"],
                    "passed": passed,
                    "missing": missing,
                    "outcome_ok": _outcome_ok(question["expect"], result),
                    "retrieval_hit": retrieval_hit(found, expected),
                    "citation_valid": citation_valid(
                        result.citations, sources, question.get("drugs") or list(expected)
                    ),
                    "numbers": list(number_grounding(result.answer, result.citations, sources)),
                    "judge": verdict,
                    "judge_reason": reason,
                    "seconds": round(seconds, 2),
                    "first_token_seconds": None if first_token is None else round(first_token, 2),
                    "cost_usd": round(cost, 5),
                    "searches": len(searches),
                    **asdict(result),
                }
            )
            print(f"{'PASS' if passed else 'FAIL'} {question['id']}: {missing or ''}", flush=True)
    tracer.shutdown()
    return {
        "label": args.label,
        "config": {
            "search_mode": args.search_mode,
            "grader_mode": runtime.grader_mode,
            "embedding_prefix": not args.no_prefix,
            "judge_model": judge_id,
            "questions": args.questions.name,
        },
        "models": {
            "rewrite": runtime.rewrite_model,
            "grade": runtime.grade_model,
            "generate": runtime.generate_model,
            "chat": runtime.chat_model,
        },
        "summary": summarize(rows),
        "results": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--rewrite-model")
    parser.add_argument("--grade-model")
    parser.add_argument("--judge-model", help="default: the generate model")
    parser.add_argument("--search-mode", choices=[m.value for m in SearchMode], default="hybrid")
    parser.add_argument("--grader-mode", choices=["off", "rule", "llm"])
    parser.add_argument("--no-prefix", action="store_true", help="vectors without the prefix")
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    configure_logging()
    report = asyncio.run(run(args))
    print(json.dumps({k: report[k] for k in ("label", "config", "summary")}, indent=2))
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    out = args.out or EVALS / "results" / f"{stamp}-{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
