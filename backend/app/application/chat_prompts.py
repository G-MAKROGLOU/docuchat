"""Prompt texts of the chat graph. The long prompts are versioned files in backend/prompts."""

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
# The version of each prompt file in use; every trace records this map.
PROMPT_VERSIONS = {
    "intake": "v3",
    "rewrite": "v1",
    "grade": "v1",
    "generate": "v2",
    "suggest": "v1",
}


def _load(name: str) -> str:
    return (PROMPT_DIR / f"{name}.{PROMPT_VERSIONS[name]}.md").read_text(encoding="utf-8").strip()


INTAKE = _load("intake")
REWRITE = _load("rewrite")
GRADE = _load("grade")
GENERATE = _load("generate")
SUGGEST = _load("suggest")

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
