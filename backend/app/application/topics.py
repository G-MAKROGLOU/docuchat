"""Question topics to the label sections that answer them. Plain code.

Section numbers follow the prescribing information layout (21 CFR 201.57(c)), so they are
the same in every label of the corpus. Patterns match whole words only."""

import re

_TOPICS: tuple[tuple[str, str], ...] = (
    ("1", r"used (?:for|to)|indications?|indicated|what is \w+ for"),
    (
        "2",
        r"doses?|dosage|dosing|dosed|administ\w*"
        r"|how (?:should|do|to|is|are)[^?.]{0,40} tak(?:e|en|ing)",
    ),
    ("3", r"strengths?|dosage forms?|tablets? sizes?|come in"),
    ("4", r"contraindicat\w*|should not (?:take|use)|who (?:should|can) ?not"),
    ("BW", r"boxed warnings?|black box"),
    ("5", r"warnings?|precautions?"),
    ("6", r"side effects?|adverse(?: reactions?| effects?| events?)?"),
    ("7", r"interact\w*|other (?:drugs|medicines|medications)"),
    ("8.1", r"pregnan\w*"),
    ("8.2", r"breast-?\s?feed\w*|breastfed|lactation|nursing"),
    ("8.4", r"child|children|kids?|pediatric|infants?|adolescents?"),
    ("8.5", r"elderly|older (?:adults|patients|people)|geriatric|seniors?"),
    ("10", r"overdos\w*"),
    ("16", r"stor(?:e|ed|age|ing)"),
)
_PATTERNS = tuple(
    (section, re.compile(rf"\b(?:{words})\b", re.IGNORECASE)) for section, words in _TOPICS
)


# What a comparison of two drugs is about when the question names no topic.
COMPARISON_SECTIONS = ("1", "2", "4", "5", "6")


def section_hints(question: str, *, comparing: bool = False) -> tuple[str, ...]:
    """The sections whose topic the question names, in label order. A comparison without a
    topic ("compare X and Y") gets the standard comparison sections."""
    hints = tuple(section for section, pattern in _PATTERNS if pattern.search(question))
    return hints or (COMPARISON_SECTIONS if comparing else ())
