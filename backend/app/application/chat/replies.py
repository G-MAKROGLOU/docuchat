"""Parsers of the model replies: intake, grade and suggestions. Bad JSON gives a safe default."""

import json
import logging
import re
from collections.abc import Sequence
from typing import Any, Literal

from app.application.chat.state import Verdict
from app.application.chat.validation import reply_is_safe

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_intake(text: str, max_reply_chars: int) -> tuple[Literal["reply", "search"], str]:
    """A reply needs its text; anything unclear or unsafe goes to the search, which can refuse."""
    data = _json_object(text)
    reply = data.get("reply")
    if data.get("action") == "reply" and isinstance(reply, str) and reply.strip():
        if reply_is_safe(reply.strip(), max_reply_chars):
            return "reply", reply.strip()
        logger.warning("intake reply with a dose, a link or too much text; searching instead")
    return "search", ""


def intake_medicines(text: str) -> tuple[str, ...]:
    """The medicine names in the intake reply, trimmed and without repeats."""
    names = _json_object(text).get("medicines")
    if not isinstance(names, list):
        return ()
    return tuple(dict.fromkeys(n.strip() for n in names if isinstance(n, str) and n.strip()))


def intake_query(text: str, max_chars: int) -> str | None:
    """The standalone search question of the intake reply; None when it is missing or too long."""
    query = _json_object(text).get("query")
    if not isinstance(query, str):
        return None
    query = " ".join(query.split())
    return query if 0 < len(query) <= max_chars else None


def parse_relevant(text: str, valid_ids: Sequence[str]) -> list[str] | None:
    """Known IDs in source order; None when the reply has no "relevant" list."""
    ids = _json_object(text).get("relevant")
    if not isinstance(ids, list):
        return None
    chosen = {i for i in ids if isinstance(i, str)}
    return [i for i in valid_ids if i in chosen]


def parse_grade(text: str, valid_ids: Sequence[str]) -> tuple[list[str], Verdict, str] | None:
    """Relevant IDs, verdict and feedback; None when the reply has no "relevant" list.
    A missing or unknown verdict counts as "sufficient" when an excerpt is relevant."""
    relevant = parse_relevant(text, valid_ids)
    if relevant is None:
        return None
    data = _json_object(text)
    stated = data.get("verdict")
    verdict: Verdict = "sufficient" if relevant else "insufficient"
    if relevant and stated in ("partial", "insufficient"):
        verdict = "partial" if stated == "partial" else "insufficient"
    feedback = data.get("feedback")
    return relevant, verdict, feedback.strip() if isinstance(feedback, str) else ""


def parse_suggestions(text: str, count: int, max_chars: int) -> list[str]:
    """Up to count unique, non-empty questions of max_chars at most; others are dropped."""
    items = _json_object(text).get("suggestions")
    if not isinstance(items, list):
        return []
    clean = (" ".join(i.split()) for i in items if isinstance(i, str))
    unique = dict.fromkeys(i for i in clean if 0 < len(i) <= max_chars)
    return list(unique)[:count]
