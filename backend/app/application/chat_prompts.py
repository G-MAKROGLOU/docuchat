"""Prompt texts of the chat graph. The long prompts are files in backend/prompts, one per step."""

import hashlib
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
NAMES = ("intake", "rewrite", "grade", "generate", "suggest")
_TEXTS = {n: (PROMPT_DIR / f"{n}.md").read_text(encoding="utf-8").strip() for n in NAMES}
# A short hash of each prompt text; every trace records this map, so a prompt change shows.
PROMPT_VERSIONS = {n: hashlib.sha256(t.encode()).hexdigest()[:12] for n, t in _TEXTS.items()}

INTAKE = _TEXTS["intake"]
REWRITE = _TEXTS["rewrite"]
GRADE = _TEXTS["grade"]
GENERATE = _TEXTS["generate"]
SUGGEST = _TEXTS["suggest"]

INTAKE_LIBRARY = "The library holds the labels of these medicines: {names}."
INTAKE_LIBRARY_LARGE = (
    "The library holds the labels of {count} medicines, too many to list here. When the user "
    "asks which medicines you have, give that number and say that the Documents page lists "
    "them all."
)

REWRITE_RETRY = (
    "A first search with the question {query!r} did not find enough in the labels. "
    "What was missing: {feedback} Write a different question that can find it."
)

NO_ANSWER = "NO_ANSWER"

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["sufficient", "partial", "insufficient"]},
        "feedback": {"type": "string"},
    },
    "required": ["relevant", "verdict", "feedback"],
    "additionalProperties": False,
}

REFUSALS = {
    "no_relevant_context": (
        "I could not find this in the drug labels I have. Try to name the medicine or ask "
        "about a specific topic, such as dosage or side effects."
    ),
    "no_valid_citation": (
        "I could not give an answer that the drug labels support. Please rephrase the question."
    ),
    "out_of_scope": "I can only answer questions about the medicines in my library of drug labels.",
    "drug_not_in_corpus": (
        "This medicine is not in my library of drug labels. Ask about one of the medicines "
        "in the library."
    ),
}
