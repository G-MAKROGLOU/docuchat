"""The answer checks: citations, figures, doses and links against the cited excerpts."""

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.application import chat_prompts
from app.application.chat.state import SourceRef
from app.domain.entities import Chunk

logger = logging.getLogger(__name__)

CITATION = re.compile(r"\[(S\d+)\]")
_LIST_MARK = re.compile(r"^(?:#+|[-*+]|\d+[.)])\s+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
# A figure such as "10", "2.5" or "34%"; digits inside a name such as "CYP2C19" are not one.
_NUMBER = re.compile(r"(?<![A-Za-z\d.,])\d+(?:[.,]\d+)?")
# "The excerpts do not give a dose below 10 years": a statement of absence has no source.
_ABSENCE = re.compile(
    r"\b(?:excerpts?|labels?)\s+(?:do|does|did)\s+not\b|\bnot\s+in\s+the\s+(?:excerpts?|labels?)\b",
    re.IGNORECASE,
)
# "Table 1" and "section 2.1" point into the label; they are not figures that need a source.
# Lists count too: "sections 2.1, 2.3 and 5.4", "tables 1 to 3".
_REFERENCE = re.compile(
    r"\b(?:tables?|sections?|figures?)\s+(?:(?:are|is|include|includes)\s+)?\d+(?:\.\d+)*"
    r"(?:\s*(?:,\s*(?:and\s+|or\s+)?|and\s+|or\s+|to\s+)\d+(?:\.\d+)*)*",
    re.IGNORECASE,
)
# "1,000" is one thousand; "2,5" is 2.5.
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_FIGURE = rf"{_THOUSANDS.pattern}|\d+(?:[.,]\d+)?"
# "10 to 20", "10-20", or a list that ends in "or" or "and" such as "10, 20, or 40".
_FIGURES = (
    rf"(?:{_FIGURE})(?:\s*,\s*(?:{_FIGURE}))*\s*,?\s*(?:or|and)\s*(?:{_FIGURE})"
    rf"|(?:{_FIGURE})\s*(?:-|\u2013|\u2014|to)\s*(?:{_FIGURE})|{_FIGURE}"
)
_UNITS = {
    **dict.fromkeys(("mg", "milligram", "milligrams"), ("mass", 1000)),
    **dict.fromkeys(("mcg", "\u00b5g", "\u03bcg", "ug", "microgram", "micrograms"), ("mass", 1)),
    **dict.fromkeys(("g", "gram", "grams"), ("mass", 1_000_000)),
    "kg": ("mass", 1_000_000_000),
    "ml": ("volume", 1),
    "l": ("volume", 1000),
    **dict.fromkeys(("%", "percent"), ("%", 1)),
    **dict.fromkeys(("unit", "units"), ("unit", 1)),
    **dict.fromkeys(("hour", "hours", "hr", "hrs"), ("hour", 1)),
    **{u: (u.rstrip("s"), 1) for u in ("iu", "mmol", "meq", "day", "days", "week", "weeks")},
    **{u: (u.rstrip("s"), 1) for u in ("month", "months", "year", "years")},
}
_PER_UNITS = {
    **dict.fromkeys(("m2", "m\u00b2"), "m2"),
    **dict.fromkeys(("day", "d"), "day"),
    **dict.fromkeys(("hour", "hr", "h"), "hour"),
    **dict.fromkeys(("min", "minute"), "min"),
    **{u: u for u in ("kg", "dose", "week", "ml", "dl", "l")},
}


def _alternatives(names: Iterable[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))


# A figure or a range with a clinical unit, such as "10 mg", "10 to 20 mg", "2.5 mg/kg/day",
# "20%" or "every 12 hours". Group 1 holds the figures, group 2 the unit, group 3 any "/kg".
_DOSE = re.compile(
    rf"(?<![A-Za-z\d.,])({_FIGURES})\s*-?\s*({_alternatives(_UNITS)})"
    rf"((?:\s*(?:/|per\s)\s*(?:{_alternatives(_PER_UNITS)})s?)*)(?![A-Za-z])",
    re.IGNORECASE,
)
_PER = re.compile(rf"(?:/|per\s)\s*({_alternatives(_PER_UNITS)})s?", re.IGNORECASE)
# "40 mg daily" in an excerpt also supports "40 mg/day"; "twice daily" does not.
_DAILY = re.compile(r"\s*,?\s*(?:once\s+)?(?:daily|a\s+day|each\s+day|every\s+day)\b", re.I)

Dose = tuple[str, Decimal, tuple[str, ...]]
_LINK = re.compile(r"https?://[^\s)\]]+|www\.[^\s)\]]+", re.IGNORECASE)


def reply_is_safe(reply: str, max_chars: int) -> bool:
    """The front desk never gives a dose or a link; only cited answers may."""
    return len(reply) <= max_chars and not _DOSE.search(reply) and not _LINK.search(reply)


def cited_ids(answer: str, valid_ids: Sequence[str]) -> list[str]:
    """Valid source IDs in order of first citation."""
    valid = set(valid_ids)
    return list(dict.fromkeys(i for i in CITATION.findall(answer) if i in valid))


def drop_unknown_markers(answer: str, valid_ids: Sequence[str]) -> str:
    """Remove markers of excerpts that were not sent, with the space before them."""
    valid = set(valid_ids)
    return re.sub(r"[ \t]*\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", answer)


def _is_heading(raw: str, line: str) -> bool:
    """Markdown and bold headings, labels that end in ":", and a plain line (not a list item)
    without a marker or end punctuation, such as "Dosage for patients 10 years and older"."""
    text = raw.strip()
    if text.startswith("#") or (text.startswith("**") and text.endswith("**")):
        return True
    if line.endswith(":"):
        return True
    plain_line = not _LIST_MARK.match(text)
    return plain_line and not CITATION.search(line) and not line.endswith((".", "!", "?"))


def _statement_lines(answer: str) -> list[tuple[list[str], frozenset[str]]]:
    """The sentences of each line, and the IDs of a marker on a line above that covers the line
    because it is indented deeper. Headings and blank lines are left out (a heading can carry the
    marker)."""
    lines: list[tuple[list[str], frozenset[str]]] = []
    covers: list[tuple[int, frozenset[str]]] = []  # the lines above with a marker, outermost first
    for raw in answer.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        while covers and indent <= covers[-1][0]:
            covers.pop()
        covering = covers[-1][1] if covers else frozenset()
        if markers := CITATION.findall(raw):
            covers.append((indent, frozenset(markers)))
        line = _LIST_MARK.sub("", raw.strip()).replace("*", "").replace("_", " ").strip()
        if line and not _is_heading(raw, line):
            lines.append((_SENTENCE_BREAK.split(line), covering))
    return lines


def _sentences(answer: str) -> list[str]:
    return [s for line, _ in _statement_lines(answer) for s in line]


def _cited_sentences(answer: str) -> list[tuple[str, frozenset[str]]]:
    """Each sentence with the IDs that cite it: its own markers, else those of the next marker in
    its line, else those of the line above that covers it (the rule of uncited_number_sentences)."""
    found: list[tuple[str, frozenset[str]]] = []
    for line, covering in _statement_lines(answer):
        ids = covering
        scoped: list[tuple[str, frozenset[str]]] = []
        for sentence in reversed(line):
            ids = frozenset(CITATION.findall(sentence)) or ids
            scoped.append((sentence, ids))
        found.extend(reversed(scoped))
    return found


def uncited_number_sentences(answer: str) -> list[str]:
    """Sentences with a number that no marker covers. A marker covers its sentence and the
    sentences before it in its line, and a marker on a line covers the lines nested under it; a
    statement of what the labels do not contain is exempt."""
    uncited: list[str] = []
    for line, covering in _statement_lines(answer):
        covered = bool(covering)
        found: list[str] = []
        for sentence in reversed(line):
            covered = covered or bool(CITATION.search(sentence))
            has_number = _NUMBER.search(_REFERENCE.sub("", CITATION.sub("", sentence)))
            if has_number and not covered and not _ABSENCE.search(sentence):
                found.append(sentence)
        uncited.extend(reversed(found))
    return uncited


def text_numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def answer_numbers(answer: str) -> set[str]:
    """The numbers of an answer, without the citation markers."""
    return {n for s in _sentences(answer) for n in _NUMBER.findall(CITATION.sub("", s))}


def ungrounded_numbers(answer: str, cited: Sequence[SourceRef]) -> list[str]:
    """Numbers of the answer that no cited excerpt contains. A warning, not a refusal."""
    known = text_numbers(" ".join(excerpt_text(s.chunk) for s in cited))
    return sorted(answer_numbers(answer) - known)


def _figure(text: str) -> Decimal:
    thousands = _THOUSANDS.fullmatch(text)
    return Decimal(text.replace(",", "") if thousands else text.replace(",", "."))


def _match_doses(match: re.Match[str]) -> set[Dose]:
    """Each figure of a dose match as (kind, amount in the base unit, "per" units)."""
    # A spelling that only matches without case (such as a dotted capital I) stays its own unit.
    unit = match.group(2).lower()
    kind, factor = _UNITS.get(unit, (unit, 1))
    per = tuple(_PER_UNITS.get(u.lower(), u.lower()) for u in _PER.findall(match.group(3)))
    return {(kind, _figure(f) * factor, per) for f in re.findall(_FIGURE, match.group(1))}


def doses_in(text: str) -> set[Dose]:
    """The doses of a text; "1 g" and "1000 mg" are the same dose, "10 mg/kg" is not "10 mg"."""
    found: set[Dose] = set()
    for match in _DOSE.finditer(text):
        doses = _match_doses(match)
        found |= doses
        if _DAILY.match(text, match.end()):
            found |= {(kind, amount, (*per, "day")) for kind, amount, per in doses}
    return found


def table_percents(text: str) -> set[Dose]:
    """Cells of a table with a "(%)" unit label ("A1C (%)") support the same figure with "%".
    A value such as "36%" is data, not a label. Only "%" gets this; dose units stay strict."""
    if "(%)" not in text:
        return set()
    rows = " ".join(line for line in text.split("\n") if " | " in line)
    return {("%", _figure(f), ()) for f in re.findall(_FIGURE, rows)}


# Ages and durations; a statement of absence may repeat one from the question.
_TIME_KINDS = {"hour", "day", "week", "month", "year"}


def unsupported_facts(answer: str, cited: Sequence[SourceRef], question: str = "") -> list[str]:
    """Doses and links of the answer without a source. These refuse the answer. A dose needs
    an excerpt that its sentence cites; a statement of absence may use any cited excerpt, or an
    age or a duration of the question."""
    by_id = {
        s.id: doses_in(excerpt_text(s.chunk)) | table_percents(excerpt_text(s.chunk)) for s in cited
    }
    asked = {d for d in doses_in(question) if d[0] in _TIME_KINDS}
    anywhere = set().union(*by_id.values(), asked)
    doses: set[str] = set()
    for sentence, ids in _cited_sentences(answer):
        known = (
            anywhere
            if _ABSENCE.search(sentence)
            else set().union(*(by_id.get(i, set()) for i in ids))
        )
        text = CITATION.sub("", sentence)
        doses |= {m.group(0).strip() for m in _DOSE.finditer(text) if not _match_doses(m) <= known}
    text = " ".join(excerpt_text(s.chunk) for s in cited).lower()
    links = {link.rstrip(".,;:").lower() for link in _LINK.findall(answer)}
    return sorted(doses | {link for link in links if link not in text})


@dataclass(frozen=True, slots=True)
class Validation:
    answer: str
    citations: list[str]
    refusal: str | None = None
    ungrounded: tuple[str, ...] = ()


def drop_question_echoes(answer: str, question: str) -> str:
    """Removes uncited sentences whose only figures come from the question, such as a lead-in
    "Here is when the dose is 2.5 mg." Any other uncited figure is left for the check."""
    asked = set(_NUMBER.findall(question))
    uncited = uncited_number_sentences(answer)
    numbers = (set(_NUMBER.findall(_REFERENCE.sub("", s))) for s in uncited)
    if not asked or not all(found <= asked for found in numbers):
        return answer
    for sentence in uncited:
        answer = answer.replace(sentence, "", 1)
    return answer.strip()


def validate_answer(answer: str, sources: Sequence[SourceRef], question: str = "") -> Validation:
    """The rules of the answer check, in order; the first broken rule refuses."""
    if answer.strip().startswith(chat_prompts.NO_ANSWER):
        return Validation(answer, [], "no_relevant_context")
    ids = [s.id for s in sources]
    cleaned = drop_question_echoes(drop_unknown_markers(answer, ids).strip(), question)
    citations = cited_ids(cleaned, ids)
    uncited = uncited_number_sentences(cleaned)
    if uncited:
        logger.info("answer refused: uncited sentence with figures", extra={"sentences": uncited})
    if not citations or uncited:
        return Validation(cleaned, citations, "no_valid_citation")
    cited = [s for s in sources if s.id in citations]
    if unsupported := unsupported_facts(cleaned, cited, question):
        logger.info("answer refused: dose or link without a source", extra={"facts": unsupported})
        return Validation(cleaned, citations, "no_valid_citation")
    return Validation(cleaned, citations, None, tuple(ungrounded_numbers(cleaned, cited)))


def excerpt_text(chunk: Chunk) -> str:
    """What the model reads of a chunk: the table caption and header it continues, then its text.
    The answer checks read the same text."""
    return f"{chunk.table_header}\n{chunk.content}" if chunk.table_header else chunk.content
