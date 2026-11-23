"""Readiness: named checks with a time limit. A failed required check makes the service not
ready; a failed optional check only shows as a warning."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

# A check returns (ok, detail) and may raise; the detail must hold no secrets.
CheckRun = Callable[[], Awaitable[tuple[bool, str | None]]]


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    required: bool
    run: CheckRun


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str | None
    duration_ms: float


async def _run(check: ReadinessCheck, limit_seconds: float) -> CheckResult:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(limit_seconds):
            ok, detail = await check.run()
    except TimeoutError:
        ok, detail = False, f"timed out after {limit_seconds:g} s"
    except Exception as exc:
        # The type only: driver and HTTP messages can hold hosts or keys.
        ok, detail = False, f"failed ({type(exc).__name__})"
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return CheckResult(check.name, ok, check.required, detail, duration_ms)


async def run_checks(
    checks: Sequence[ReadinessCheck], limit_seconds: float
) -> tuple[bool, list[CheckResult]]:
    """All checks at once. Ready when every required check passed."""
    results = list(await asyncio.gather(*(_run(c, limit_seconds) for c in checks)))
    return all(r.ok for r in results if r.required), results
