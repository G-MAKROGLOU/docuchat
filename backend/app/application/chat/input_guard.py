"""Plain checks of the question before any model call."""

import re

# API contract: the request schema and the frontend use the same limit.
MAX_QUESTION_CHARS = 2000

# Requests to drop the rules or show the prompt. Plain wording only; the prompts still say
# that excerpt text is data.
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:of\s+)?(?:the\s+|your\s+|my\s+)?"
    r"(?:previous|prior|above|earlier|system)\s+(?:instructions|rules|prompts?)\b"
    r"|\b(?:ignore|disregard|override)\s+(?:all\s+|your\s+)(?:instructions|rules)\b"
    r"|\b(?:system|developer)\s+prompt\b"
    r"|\b(?:reveal|show|print|repeat)\s+(?:me\s+)?your\s+(?:hidden\s+)?(?:instructions|prompt|rules)\b"
    r"|\byou\s+are\s+now\b|\bdeveloper\s+mode\b|\bjailbreak\b",
    re.IGNORECASE,
)


def guard_problem(question: str) -> str | None:
    """Why the question cannot go to the models, or None when it can."""
    text = question.strip()
    if not text:
        return "empty"
    if len(text) > MAX_QUESTION_CHARS:
        return "too_long"
    if _INJECTION.search(text):
        return "injection"
    return None
