"""Chat turn: a cheap model handles the conversation; the document pipeline answers with
citations. Nodes emit stream events (the shape of app/api/schemas/stream.py) as custom data."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from typing import Any, Literal, Protocol, TypedDict
from uuid import UUID

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.application import chat_prompts
from app.application.drug_detection import DrugDetection
from app.application.retrieval import RetrievalResult
from app.application.topics import section_hints
from app.domain.conversations import ConversationRepository, Turn
from app.domain.entities import Chunk, Message, MessageRole, ModelRole
from app.domain.ports import ChatModelProvider, TurnTracer

logger = logging.getLogger(__name__)

HISTORY_TURNS = 10
MAX_QUESTION_CHARS = 2000
# A longer intake query is not one search question; the rewrite node makes the query then.
MAX_QUERY_CHARS = 500
# One rewrite and search again after a weak grade; never more.
MAX_RETRIES = 1
# Seconds for a whole chat turn, all model calls included.
TURN_DEADLINE_SECONDS = 120.0
_CITATION = re.compile(r"\[(S\d+)\]")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
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
# Greetings and library lists are short; a long reply is more than the front desk should say.
MAX_REPLY_CHARS = 500
# Up to this many names, the intake prompt lists the library.
INTAKE_LIST_MAX = 100

GraderMode = Literal["off", "rule", "llm"]
Verdict = Literal["sufficient", "partial", "insufficient"]


class Detector(Protocol):
    def detect(self, question: str) -> DrugDetection: ...

    def catalog(self) -> list[str]: ...


# Read per turn, so labels ingested after startup are known.
DetectorSource = Callable[[], Awaitable[Detector]]


class Retriever(Protocol):
    async def retrieve(
        self, query: str, *, labels: Sequence[UUID] = (), section_hints: Sequence[str] = ()
    ) -> RetrievalResult: ...


@dataclass(frozen=True, slots=True)
class SourceRef:
    id: str  # "S1"
    chunk: Chunk


class ChatState(TypedDict, total=False):
    question: str
    history: list[Message]
    action: str
    reply: str
    # Medicines the intake model found in the question; code checks them against the library.
    named: tuple[str, ...]
    query: str
    labels: tuple[UUID, ...]  # the searched labels (document IDs)
    candidates: list[str]
    sources: list[SourceRef]
    # Relevant excerpts of the first search, kept for the second one.
    kept: list[SourceRef]
    attempt: int
    verdict: str
    feedback: str
    retry: bool
    answer: str
    citations: list[str]
    ungrounded_numbers: list[str]
    refusal: str


# ─────────────────── plain functions (unit-tested) ───────────────────


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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


def reply_is_safe(reply: str) -> bool:
    """The front desk never gives a dose or a link; only cited answers may."""
    return len(reply) <= MAX_REPLY_CHARS and not _DOSE.search(reply) and not _LINK.search(reply)


def parse_intake(text: str) -> tuple[Literal["reply", "search"], str]:
    """A reply needs its text; anything unclear or unsafe goes to the search, which can refuse."""
    data = _json_object(text)
    reply = data.get("reply")
    if data.get("action") == "reply" and isinstance(reply, str) and reply.strip():
        if reply_is_safe(reply.strip()):
            return "reply", reply.strip()
        logger.warning("intake reply with a dose, a link or too much text; searching instead")
    return "search", ""


def intake_medicines(text: str) -> tuple[str, ...]:
    """The medicine names in the intake reply, trimmed and without repeats."""
    names = _json_object(text).get("medicines")
    if not isinstance(names, list):
        return ()
    return tuple(dict.fromkeys(n.strip() for n in names if isinstance(n, str) and n.strip()))


def intake_query(text: str) -> str | None:
    """The standalone search question of the intake reply; None when it is missing or too long."""
    query = _json_object(text).get("query")
    if not isinstance(query, str):
        return None
    query = " ".join(query.split())
    return query if 0 < len(query) <= MAX_QUERY_CHARS else None


def outside_library(detector: Detector, names: Sequence[str]) -> tuple[str, ...]:
    """Named medicines that the detector does not find, also not by spelling."""
    found = [detector.detect(name) for name in names]
    return tuple(n for n, d in zip(names, found, strict=True) if not d.drugs and not d.ambiguous)


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


def rule_check(sources: Sequence[SourceRef], labels: Sequence[UUID]) -> list[SourceRef]:
    """Plain pre-check: drop empty excerpts and, when labels were searched, other labels'."""
    wanted = set(labels)
    return [
        s
        for s in sources
        if s.chunk.content.strip() and (not wanted or s.chunk.document_id in wanted)
    ]


def grade_decision(verdict: Verdict, has_relevant: bool, attempt: int) -> str:
    """generate, retry or refuse. A partial result on the last attempt is still answered."""
    if verdict == "sufficient" and has_relevant:
        return "generate"
    if attempt < MAX_RETRIES:
        return "retry"
    return "generate" if has_relevant else "refuse"


def merge_sources(first: Sequence[SourceRef], second: Sequence[SourceRef]) -> list[SourceRef]:
    """Both searches' relevant excerpts without repeats, numbered again from S1."""
    unique = {s.chunk.id: s.chunk for s in [*first, *second]}
    return [SourceRef(f"S{i}", c) for i, c in enumerate(unique.values(), start=1)]


MAX_SUGGESTIONS = 3
MAX_SUGGESTION_CHARS = 120


def parse_suggestions(text: str) -> list[str]:
    """Up to MAX_SUGGESTIONS unique, non-empty questions; anything else is dropped."""
    items = _json_object(text).get("suggestions")
    if not isinstance(items, list):
        return []
    clean = (" ".join(i.split()) for i in items if isinstance(i, str))
    unique = dict.fromkeys(i for i in clean if 0 < len(i) <= MAX_SUGGESTION_CHARS)
    return list(unique)[:MAX_SUGGESTIONS]


def cited_ids(answer: str, valid_ids: Sequence[str]) -> list[str]:
    """Valid source IDs in order of first citation."""
    valid = set(valid_ids)
    return list(dict.fromkeys(i for i in _CITATION.findall(answer) if i in valid))


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
    return plain_line and not _CITATION.search(line) and not line.endswith((".", "!", "?"))


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
        if markers := _CITATION.findall(raw):
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
            ids = frozenset(_CITATION.findall(sentence)) or ids
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
            covered = covered or bool(_CITATION.search(sentence))
            has_number = _NUMBER.search(_REFERENCE.sub("", _CITATION.sub("", sentence)))
            if has_number and not covered and not _ABSENCE.search(sentence):
                found.append(sentence)
        uncited.extend(reversed(found))
    return uncited


def text_numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def answer_numbers(answer: str) -> set[str]:
    """The numbers of an answer, without the citation markers."""
    return {n for s in _sentences(answer) for n in _NUMBER.findall(_CITATION.sub("", s))}


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
        text = _CITATION.sub("", sentence)
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
    if not citations or uncited_number_sentences(cleaned):
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


def source_block(sources: Sequence[SourceRef]) -> str:
    return "\n\n".join(
        f"[{s.id}] {s.chunk.drug_name}, section {s.chunk.section_number} "
        f"{s.chunk.section_title}, page {s.chunk.page_start}:\n"
        f"{excerpt_text(s.chunk)}"
        for s in sources
    )


# Named functions, not partials: the trace shows each route by its function name.
def route_after_guard(state: ChatState) -> str:
    return END if state.get("refusal") else "intake"


def route_after_intake(state: ChatState) -> str:
    if state.get("action") == "reply":
        return "reply"
    return "retrieve" if state.get("query") else "rewrite"


def route_after_retrieve(state: ChatState) -> str:
    if state.get("refusal"):
        return END
    return "clarify" if state.get("candidates") else "grade"


def route_after_grade(state: ChatState) -> str:
    if state.get("refusal"):
        return END
    return "rewrite" if state.get("retry") else "generate"


def route_after_validate(state: ChatState) -> str:
    return END if state.get("refusal") else "suggest"


# ─────────────────── nodes ───────────────────


def _status(stage: str, message: str) -> None:
    get_stream_writer()({"type": "status", "stage": stage, "message": message})


def _refuse(reason: str, **extra: object) -> ChatState:
    get_stream_writer()({"type": "refusal", "reason": reason, **extra})
    return {"refusal": reason}


def _conversation(system: str, state: ChatState) -> list[Message]:
    return [
        Message(MessageRole.SYSTEM, system),
        *state.get("history", []),
        Message(MessageRole.USER, state["question"]),
    ]


async def guard(state: ChatState) -> ChatState:
    """Plain code before any model call: empty, too long, or a prompt injection."""
    problem = guard_problem(state["question"])
    if problem is None:
        return {}
    logger.info("question refused by the guard", extra={"problem": problem})
    return _refuse("out_of_scope")


def intake_prompt(catalog: Sequence[str]) -> str:
    """The intake instructions plus the library list, so the chat model knows what it has. A
    large library gives only its size: 2000 names would add about 15,000 tokens to each turn."""
    if len(catalog) > INTAKE_LIST_MAX:
        library = chat_prompts.INTAKE_LIBRARY_LARGE.format(count=len(catalog))
    else:
        library = chat_prompts.INTAKE_LIBRARY.format(names=", ".join(catalog) or "none yet")
    return f"{chat_prompts.INTAKE}\n\n{library}"


async def intake(
    state: ChatState, *, models: ChatModelProvider, detectors: DetectorSource
) -> ChatState:
    system = intake_prompt((await detectors()).catalog())
    text = await models.for_role(ModelRole.CHAT).complete(_conversation(system, state))
    action, reply = parse_intake(text)
    state_update: ChatState = {"action": action, "reply": reply}
    if action == "search":
        if named := intake_medicines(text):
            state_update["named"] = named
        # With a query, the first search skips the rewrite node.
        if query := intake_query(text):
            state_update["query"] = query
    return state_update


async def reply(state: ChatState) -> ChatState:
    write = get_stream_writer()
    write({"type": "token", "text": state["reply"]})
    write({"type": "final", "answer": state["reply"], "citations": []})
    return {}


async def rewrite(state: ChatState, *, models: ChatModelProvider) -> ChatState:
    messages = _conversation(chat_prompts.REWRITE, state)
    if state.get("attempt", 0):
        _status("rewrite", "Searching again with other words")
        retry = chat_prompts.REWRITE_RETRY.format(
            query=state["query"], feedback=state.get("feedback") or "not stated."
        )
        # User words and grade output go in the user message, never in the system prompt.
        messages[-1] = Message(MessageRole.USER, f"{state['question']}\n\n{retry}")
    else:
        _status("rewrite", "Reading the question")
    query = await models.for_role(ModelRole.REWRITE).complete(messages)
    return {"query": query.strip() or state["question"]}


async def retrieve(
    state: ChatState, *, detectors: DetectorSource, retriever: Retriever
) -> ChatState:
    _status("retrieve", "Searching the drug labels")
    detector = await detectors()
    detection = detector.detect(state["query"])
    labels = detection.labels
    # A retry keeps the labels of the first search; its rewrite can drop or misspell the name.
    retry_labels = state.get("labels", ()) if state.get("attempt", 0) else ()
    if retry_labels:
        labels = labels or retry_labels
    elif detection.ambiguous:
        return {"candidates": list(detection.ambiguous)}
    elif not labels and (
        detection.not_in_corpus or outside_library(detector, state.get("named", ()))
    ):
        catalog = detector.catalog()
        # The list is for a small library only; a large one has the Documents page.
        extra = {"available_drugs": catalog} if len(catalog) <= INTAKE_LIST_MAX else {}
        return _refuse("drug_not_in_corpus", **extra)
    result = await retriever.retrieve(
        state["query"],
        labels=labels,
        section_hints=section_hints(state["query"], comparing=len(labels) > 1),
    )
    sources = [SourceRef(f"S{i}", f.chunk) for i, f in enumerate(result.selected, start=1)]
    # On a retry, grade merges in the first search's excerpts, so an empty result can go on.
    if not sources and not state.get("kept"):
        return _refuse("no_relevant_context")
    return {"sources": sources, "labels": labels}


async def clarify(state: ChatState) -> ChatState:
    candidates = state["candidates"]
    text = f"Which medicine do you mean: {' or '.join(candidates)}?"
    write = get_stream_writer()
    write({"type": "clarify", "candidates": candidates})
    write({"type": "token", "text": text})
    write({"type": "final", "answer": text, "citations": []})
    return {"reply": text}


async def _llm_grade(
    state: ChatState, sources: list[SourceRef], models: ChatModelProvider
) -> tuple[list[SourceRef], Verdict, str]:
    text = await models.for_role(ModelRole.GRADE).complete(
        [
            Message(MessageRole.SYSTEM, chat_prompts.GRADE),
            Message(
                MessageRole.USER,
                f"Question: {state['query']}\n\nExcerpts:\n\n{source_block(sources)}",
            ),
        ],
        json_schema=chat_prompts.GRADE_SCHEMA,
    )
    graded = parse_grade(text, [s.id for s in sources])
    if graded is None:
        # An unreadable grade must not refuse an answer that retrieval found: keep every excerpt.
        logger.warning("grade reply is not valid JSON; keeping all excerpts")
        return sources, "sufficient", ""
    relevant, verdict, feedback = graded
    return [s for s in sources if s.id in relevant], verdict, feedback


async def grade(state: ChatState, *, models: ChatModelProvider, mode: GraderMode) -> ChatState:
    _status("grade", "Checking the excerpts")
    attempt = state.get("attempt", 0)
    sources = state["sources"]
    verdict: Verdict
    if mode == "off":
        kept, verdict, feedback = sources, "sufficient", ""
    else:
        kept = rule_check(sources, state.get("labels", ()))
        verdict, feedback = ("sufficient" if kept else "insufficient"), ""
        if mode == "llm" and kept:
            kept, verdict, feedback = await _llm_grade(state, kept, models)
    if attempt:
        kept = merge_sources(state.get("kept", []), kept)
    decision = grade_decision(verdict, bool(kept), attempt)
    if decision == "retry":
        return {
            "retry": True,
            "attempt": attempt + 1,
            "kept": kept,
            "verdict": verdict,
            "feedback": feedback or "The excerpts do not answer the question.",
        }
    if decision == "refuse":
        return {**_refuse("no_relevant_context"), "retry": False, "verdict": verdict}
    get_stream_writer()(
        {
            "type": "sources",
            "items": [
                {
                    "id": s.id,
                    "document": str(s.chunk.document_id),
                    "drug": s.chunk.drug_name,
                    "section": f"{s.chunk.section_number} {s.chunk.section_title}",
                    "page": s.chunk.page_start,
                    "text": s.chunk.content,
                    "anchor": s.chunk.anchor,
                }
                for s in kept
            ],
        }
    )
    return {"sources": kept, "retry": False, "verdict": verdict}


async def generate(state: ChatState, *, models: ChatModelProvider) -> ChatState:
    """Collects the answer but sends no tokens: the user sees only text that validate passed."""
    _status("generate", "Writing the answer")
    parts: list[str] = []
    messages = [
        Message(MessageRole.SYSTEM, chat_prompts.GENERATE),
        Message(
            MessageRole.USER,
            f"Question: {state['query']}\n\nExcerpts:\n\n{source_block(state['sources'])}",
        ),
    ]
    async for token in models.for_role(ModelRole.GENERATE).stream(messages):
        parts.append(token)
    return {"answer": "".join(parts)}


async def validate(state: ChatState) -> ChatState:
    """The answer check; its output in the trace lists numbers that no cited excerpt has."""
    _status("verify", "Checking the sources")
    result = validate_answer(state["answer"], state["sources"], state["question"])
    if result.refusal:
        return _refuse(result.refusal)
    if result.ungrounded:
        logger.info(
            "answer numbers not in the cited excerpts", extra={"numbers": result.ungrounded}
        )
    write = get_stream_writer()
    # The checked answer is the first answer text the client gets.
    write({"type": "token", "text": result.answer})
    write({"type": "final", "answer": result.answer, "citations": result.citations})
    return {
        "answer": result.answer,
        "citations": result.citations,
        "ungrounded_numbers": list(result.ungrounded),
    }


async def suggest(state: ChatState, *, models: ChatModelProvider) -> ChatState:
    """Follow-up questions after an answer or a reply. A failure here never fails the turn."""
    if state.get("refusal"):
        return {}
    answer = _CITATION.sub("", state.get("answer") or state.get("reply", ""))
    # One user message: providers refuse a request that ends with an assistant message.
    exchange = f"Question: {state['question']}\n\nAnswer:\n{answer}"
    try:
        text = await models.for_role(ModelRole.CHAT).complete(
            [Message(MessageRole.SYSTEM, chat_prompts.SUGGEST), Message(MessageRole.USER, exchange)]
        )
    except Exception:
        logger.warning("follow-up suggestions failed", exc_info=True)
        return {}
    suggestions = parse_suggestions(text)
    if suggestions:
        get_stream_writer()({"type": "suggestions", "items": suggestions})
    return {}


def build_chat_graph(
    models: ChatModelProvider,
    detectors: DetectorSource,
    retriever: Retriever,
    grader_mode: GraderMode = "llm",
) -> Any:
    graph = StateGraph(ChatState)
    graph.add_node("guard", guard)
    graph.add_node("intake", partial(intake, models=models, detectors=detectors))
    graph.add_node("reply", reply)
    graph.add_node("rewrite", partial(rewrite, models=models))
    graph.add_node("retrieve", partial(retrieve, detectors=detectors, retriever=retriever))
    graph.add_node("clarify", clarify)
    graph.add_node("grade", partial(grade, models=models, mode=grader_mode))
    graph.add_node("generate", partial(generate, models=models))
    graph.add_node("validate", validate)
    graph.add_node("suggest", partial(suggest, models=models))
    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", route_after_guard, ["intake", END])
    graph.add_conditional_edges("intake", route_after_intake, ["reply", "rewrite", "retrieve"])
    graph.add_edge("reply", "suggest")
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges("retrieve", route_after_retrieve, ["grade", "clarify", END])
    graph.add_edge("clarify", END)
    graph.add_conditional_edges("grade", route_after_grade, ["generate", "rewrite", END])
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", route_after_validate, ["suggest", END])
    graph.add_edge("suggest", END)
    return graph.compile()


# ─────────────────── service ───────────────────


class ConversationNotFoundError(LookupError):
    pass


class ChatService:
    def __init__(  # noqa: PLR0913  # five ports plus the grader switch from the settings
        self,
        conversations: ConversationRepository,
        models: ChatModelProvider,
        detectors: DetectorSource,
        retriever: Retriever,
        tracer: TurnTracer,
        *,
        grader_mode: GraderMode = "llm",
        turn_deadline: float = TURN_DEADLINE_SECONDS,
    ) -> None:
        self._conversations = conversations
        self._deadline = turn_deadline
        self._tracer = tracer
        self._graph = build_chat_graph(models, detectors, retriever, grader_mode)
        # Every trace records the prompt versions and the grader mode of its turn.
        self._run_metadata: dict[str, object] = {
            "prompts": dict(chat_prompts.PROMPT_VERSIONS),
            "grader": grader_mode,
        }

    async def start(self) -> UUID:
        return await self._conversations.create()

    async def end(self, conversation_id: UUID) -> None:
        """Delete the conversation. An unknown ID is not an error."""
        await self._conversations.delete(conversation_id)

    async def history(self, conversation_id: UUID) -> list[Turn]:
        if not await self._conversations.exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        return await self._conversations.turns(conversation_id)

    async def ask(self, conversation_id: UUID, question: str) -> AsyncGenerator[dict[str, Any]]:
        """Stream events; store the question, and the answer when its final event arrives."""
        if not await self._conversations.exists(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        history = [
            Message(t.role, t.text)
            for t in await self._conversations.turns(conversation_id, limit=HISTORY_TURNS)
        ]
        await self._conversations.add_turn(conversation_id, MessageRole.USER, question)
        return self._run(conversation_id, {"question": question, "history": history})

    async def _run(self, conversation_id: UUID, state: ChatState) -> AsyncGenerator[dict[str, Any]]:
        trace = self._tracer.start_turn(conversation_id, state["question"])
        stored: tuple[str, dict[str, object]] | None = None
        ended = False
        try:
            # A stuck provider must not hold the stream and its connection open forever.
            async with asyncio.timeout(self._deadline):
                async for part in self._graph.astream(
                    state, config=dict(trace.run_config), stream_mode="custom", version="v2"
                ):
                    event: dict[str, Any] = part["data"]
                    if event["type"] in {"final", "refusal"}:
                        # Stored now: the suggestions that follow must not decide if it is kept.
                        stored = await self._store_answer(conversation_id, event)
                    yield event
        except TimeoutError:
            logger.warning(
                "chat turn past its deadline", extra={"conversation_id": str(conversation_id)}
            )
            trace.end(None, {"outcome": "timeout", **self._run_metadata}, failed=True)
            ended = True
            yield {"type": "error", "message": "The answer took too long. Please try again."}
            return
        except Exception:
            logger.exception("chat turn failed", extra={"conversation_id": str(conversation_id)})
            trace.end(None, {"outcome": "error", **self._run_metadata}, failed=True)
            ended = True
            yield {"type": "error", "message": "The answer failed. Please try again."}
            return
        finally:
            # The client can close the stream early; the trace still ends.
            if not ended:
                text, metadata = stored or (None, {"outcome": "incomplete"})
                trace.end(text, {**metadata, **self._run_metadata}, failed=False)

    async def _store_answer(
        self, conversation_id: UUID, event: dict[str, Any]
    ) -> tuple[str, dict[str, object]]:
        if event["type"] == "final":
            text, citations = event["answer"], event["citations"]
            metadata: dict[str, object] = {"outcome": "answer", "citations": citations}
        else:
            text, citations = chat_prompts.REFUSALS[event["reason"]], []
            metadata = {"outcome": "refusal", "reason": event["reason"]}
        await self._conversations.add_turn(conversation_id, MessageRole.ASSISTANT, text, citations)
        return text, metadata
