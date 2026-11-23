"""Chat load test: concurrent users, each in its own conversation, ask questions in turn.
Usage: python -m loadtest.run --base http://backend:8000 --users 20 --turns 5 [--out report.json]"""

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

TOPICS = (
    "What is the recommended dose of {}?",
    "What are the common side effects of {}?",
    "What are the warnings and precautions for {}?",
    "Can {} be used during pregnancy?",
    "Which drugs interact with {}?",
)
TERMINAL = {"final", "refusal", "clarify", "error"}
# The API caps one page of documents at 100.
PAGE_SIZE = 100


@dataclass
class Turn:
    outcome: str
    seconds: float
    first_token_seconds: float | None


async def drug_names(client: httpx.AsyncClient) -> list[str]:
    """Every ingested drug, page by page, so the questions cover the whole library."""
    names: list[str] = []
    page = 1
    while True:
        response = await client.get(
            "/api/v1/documents", params={"page": page, "page_size": PAGE_SIZE}
        )
        response.raise_for_status()
        body = response.json()
        names += [d["brand_name"] for d in body["items"] if d["status"] == "ingested"]
        if page * PAGE_SIZE >= body["total"]:
            return names
        page += 1


async def ask(client: httpx.AsyncClient, conversation: str, text: str) -> Turn:
    started = time.perf_counter()
    first: float | None = None
    outcome = "no_final"
    try:
        url = f"/api/v1/conversations/{conversation}/messages"
        async with client.stream("POST", url, json={"text": text}) as response:
            if response.status_code != httpx.codes.OK:
                return Turn(f"http_{response.status_code}", time.perf_counter() - started, None)
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                kind = json.loads(line[6:]).get("type")
                if kind == "token" and first is None:
                    first = time.perf_counter() - started
                if kind in TERMINAL and outcome == "no_final":
                    outcome = kind
    except httpx.HTTPError as exc:
        outcome = type(exc).__name__
    return Turn(outcome, time.perf_counter() - started, first)


async def user(
    client: httpx.AsyncClient, names: list[str], turns: int, rng: random.Random
) -> list[Turn]:
    try:
        response = await client.post("/api/v1/conversations")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return [Turn(f"create_{type(exc).__name__}", 0.0, None)]
    conversation = response.json()["id"]
    drug = rng.choice(names)
    return [await ask(client, conversation, rng.choice(TOPICS).format(drug)) for _ in range(turns)]


def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 3)


def summary(turns: list[Turn], wall: float, users: int) -> dict[str, object]:
    done = [t.seconds for t in turns if t.outcome == "final"]
    first = [t.first_token_seconds for t in turns if t.first_token_seconds is not None]
    outcomes: dict[str, int] = {}
    for t in turns:
        outcomes[t.outcome] = outcomes.get(t.outcome, 0) + 1
    return {
        "users": users,
        "turns": len(turns),
        "wall_seconds": round(wall, 1),
        "turns_per_second": round(len(turns) / wall, 2) if wall else None,
        "outcomes": outcomes,
        "answered_seconds": {
            "p50": percentile(done, 0.5),
            "p95": percentile(done, 0.95),
            "p99": percentile(done, 0.99),
            "mean": round(statistics.fmean(done), 3) if done else None,
        },
        "first_token_seconds": {"p50": percentile(first, 0.5), "p95": percentile(first, 0.95)},
    }


async def main_async(args: argparse.Namespace) -> tuple[dict[str, object], list[Turn]]:
    limits = httpx.Limits(max_connections=args.users * 2)
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(base_url=args.base, limits=limits, timeout=timeout) as client:
        names = await drug_names(client)
        if not names:
            raise SystemExit("no ingested documents; fill the library first")
        # Seeded and repeatable test data, not security.
        rng = random.Random(args.seed)  # noqa: S311
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                user(client, names, args.turns, random.Random(rng.random()))  # noqa: S311
                for _ in range(args.users)
            )
        )
        wall = time.perf_counter() - started
    turns = [t for r in results for t in r]
    return summary(turns, wall, args.users), turns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://backend:8000")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    report, turns = asyncio.run(main_async(args))
    if args.out:
        detail = {**report, "turn_detail": [asdict(t) for t in turns]}
        Path(args.out).write_text(json.dumps(detail, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    outcomes = report["outcomes"]
    return 0 if isinstance(outcomes, dict) and set(outcomes) <= {"final"} else 1


if __name__ == "__main__":
    sys.exit(main())
