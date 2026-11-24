"""The chat graph: routes and nodes. Each node is a function of the state and injected ports.
Nodes send stream events through the injected emit port; only build_chat_graph knows LangGraph."""

import logging
from collections.abc import Sequence
from functools import partial
from typing import Any
from uuid import UUID

from langgraph.config import get_stream_writer
from langgraph.graph import END as END  # noqa: PLC0414  explicit re-export: the route value
from langgraph.graph import START, StateGraph

from app.application import chat_prompts
from app.application.chat.input_guard import guard_problem
from app.application.chat.replies import (
    intake_medicines,
    intake_query,
    parse_grade,
    parse_intake,
    parse_suggestions,
)
from app.application.chat.state import (
    ChatLimits,
    ChatState,
    Detector,
    DetectorSource,
    Emit,
    Retriever,
    SourceRef,
    Verdict,
)
from app.application.chat.validation import CITATION, excerpt_text, validate_answer
from app.application.topics import section_hints
from app.domain.entities import Message, MessageRole, ModelRole
from app.domain.ports import ChatModelProvider
from app.domain.runtime_settings import GraderMode

logger = logging.getLogger(__name__)


def outside_library(detector: Detector, names: Sequence[str]) -> tuple[str, ...]:
    """Named medicines that the detector does not find, also not by spelling."""
    found = [detector.detect(name) for name in names]
    return tuple(n for n, d in zip(names, found, strict=True) if not d.drugs and not d.ambiguous)


def rule_check(sources: Sequence[SourceRef], labels: Sequence[UUID]) -> list[SourceRef]:
    """Plain pre-check: drop empty excerpts and, when labels were searched, other labels'."""
    wanted = set(labels)
    return [
        s
        for s in sources
        if s.chunk.content.strip() and (not wanted or s.chunk.document_id in wanted)
    ]


def grade_decision(verdict: Verdict, has_relevant: bool, attempt: int, retries: int) -> str:
    """generate, retry or refuse. A partial result on the last attempt is still answered."""
    if verdict == "sufficient" and has_relevant:
        return "generate"
    if attempt < retries:
        return "retry"
    return "generate" if has_relevant else "refuse"


def merge_sources(first: Sequence[SourceRef], second: Sequence[SourceRef]) -> list[SourceRef]:
    """Both searches' relevant excerpts without repeats, numbered again from S1."""
    unique = {s.chunk.id: s.chunk for s in [*first, *second]}
    return [SourceRef(f"S{i}", c) for i, c in enumerate(unique.values(), start=1)]


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


def _status(emit: Emit, stage: str, message: str) -> None:
    emit({"type": "status", "stage": stage, "message": message})


def _refuse(emit: Emit, reason: str, **extra: object) -> ChatState:
    emit({"type": "refusal", "reason": reason, **extra})
    return {"refusal": reason}


def _conversation(system: str, state: ChatState) -> list[Message]:
    return [
        Message(MessageRole.SYSTEM, system),
        *state.get("history", []),
        Message(MessageRole.USER, state["question"]),
    ]


async def guard(state: ChatState, *, emit: Emit) -> ChatState:
    """Plain code before any model call: empty, too long, or a prompt injection."""
    problem = guard_problem(state["question"])
    if problem is None:
        return {}
    logger.info("question refused by the guard", extra={"problem": problem})
    return _refuse(emit, "out_of_scope")


def intake_prompt(catalog: Sequence[str], list_max: int) -> str:
    """The intake instructions plus the library list, so the chat model knows what it has. A
    large library gives only its size: 2000 names would add about 15,000 tokens to each turn."""
    if len(catalog) > list_max:
        library = chat_prompts.INTAKE_LIBRARY_LARGE.format(count=len(catalog))
    else:
        library = chat_prompts.INTAKE_LIBRARY.format(names=", ".join(catalog) or "none yet")
    return f"{chat_prompts.INTAKE}\n\n{library}"


async def intake(
    state: ChatState, *, models: ChatModelProvider, detectors: DetectorSource, limits: ChatLimits
) -> ChatState:
    system = intake_prompt((await detectors()).catalog(), limits.intake_list_max)
    text = await models.for_role(ModelRole.CHAT).complete(_conversation(system, state))
    action, reply = parse_intake(text, limits.max_reply_chars)
    state_update: ChatState = {"action": action, "reply": reply}
    if action == "search":
        if named := intake_medicines(text):
            state_update["named"] = named
        # With a query, the first search skips the rewrite node.
        if query := intake_query(text, limits.max_query_chars):
            state_update["query"] = query
    return state_update


async def reply(state: ChatState, *, emit: Emit) -> ChatState:
    emit({"type": "token", "text": state["reply"]})
    emit({"type": "final", "answer": state["reply"], "citations": []})
    return {}


async def rewrite(state: ChatState, *, models: ChatModelProvider, emit: Emit) -> ChatState:
    messages = _conversation(chat_prompts.REWRITE, state)
    if state.get("attempt", 0):
        _status(emit, "rewrite", "Searching again with other words")
        retry = chat_prompts.REWRITE_RETRY.format(
            query=state["query"], feedback=state.get("feedback") or "not stated."
        )
        # User words and grade output go in the user message, never in the system prompt.
        messages[-1] = Message(MessageRole.USER, f"{state['question']}\n\n{retry}")
    else:
        _status(emit, "rewrite", "Reading the question")
    query = await models.for_role(ModelRole.REWRITE).complete(messages)
    return {"query": query.strip() or state["question"]}


async def retrieve(
    state: ChatState,
    *,
    detectors: DetectorSource,
    retriever: Retriever,
    limits: ChatLimits,
    emit: Emit,
) -> ChatState:
    _status(emit, "retrieve", "Searching the drug labels")
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
        extra = {"available_drugs": catalog} if len(catalog) <= limits.intake_list_max else {}
        return _refuse(emit, "drug_not_in_corpus", **extra)
    result = await retriever.retrieve(
        state["query"],
        labels=labels,
        section_hints=section_hints(state["query"], comparing=len(labels) > 1),
    )
    sources = [SourceRef(f"S{i}", f.chunk) for i, f in enumerate(result.selected, start=1)]
    # On a retry, grade merges in the first search's excerpts, so an empty result can go on.
    if not sources and not state.get("kept"):
        return _refuse(emit, "no_relevant_context")
    return {"sources": sources, "labels": labels}


async def clarify(state: ChatState, *, emit: Emit) -> ChatState:
    candidates = state["candidates"]
    text = f"Which medicine do you mean: {' or '.join(candidates)}?"
    emit({"type": "clarify", "candidates": candidates})
    emit({"type": "token", "text": text})
    emit({"type": "final", "answer": text, "citations": []})
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


async def grade(
    state: ChatState,
    *,
    models: ChatModelProvider,
    mode: GraderMode,
    limits: ChatLimits,
    emit: Emit,
) -> ChatState:
    _status(emit, "grade", "Checking the excerpts")
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
    decision = grade_decision(verdict, bool(kept), attempt, limits.grade_retries)
    if decision == "retry":
        return {
            "retry": True,
            "attempt": attempt + 1,
            "kept": kept,
            "verdict": verdict,
            "feedback": feedback or "The excerpts do not answer the question.",
        }
    if decision == "refuse":
        return {**_refuse(emit, "no_relevant_context"), "retry": False, "verdict": verdict}
    emit(
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


async def generate(state: ChatState, *, models: ChatModelProvider, emit: Emit) -> ChatState:
    """Collects the answer but sends no tokens: the user sees only text that validate passed."""
    _status(emit, "generate", "Writing the answer")
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


async def validate(state: ChatState, *, emit: Emit) -> ChatState:
    """The answer check; its output in the trace lists numbers that no cited excerpt has."""
    _status(emit, "verify", "Checking the sources")
    result = validate_answer(state["answer"], state["sources"], state["question"])
    if result.refusal:
        return _refuse(emit, result.refusal)
    if result.ungrounded:
        logger.info(
            "answer numbers not in the cited excerpts", extra={"numbers": result.ungrounded}
        )
    # The checked answer is the first answer text the client gets.
    emit({"type": "token", "text": result.answer})
    emit({"type": "final", "answer": result.answer, "citations": result.citations})
    return {
        "answer": result.answer,
        "citations": result.citations,
        "ungrounded_numbers": list(result.ungrounded),
    }


async def suggest(
    state: ChatState, *, models: ChatModelProvider, limits: ChatLimits, emit: Emit
) -> ChatState:
    """Follow-up questions after an answer or a reply. A failure here never fails the turn."""
    if state.get("refusal"):
        return {}
    answer = CITATION.sub("", state.get("answer") or state.get("reply", ""))
    # One user message: providers refuse a request that ends with an assistant message.
    exchange = f"Question: {state['question']}\n\nAnswer:\n{answer}"
    try:
        text = await models.for_role(ModelRole.CHAT).complete(
            [Message(MessageRole.SYSTEM, chat_prompts.SUGGEST), Message(MessageRole.USER, exchange)]
        )
    except Exception:
        logger.warning("follow-up suggestions failed", exc_info=True)
        return {}
    suggestions = parse_suggestions(text, limits.max_suggestions, limits.max_suggestion_chars)
    if suggestions:
        emit({"type": "suggestions", "items": suggestions})
    return {}


def build_chat_graph(
    models: ChatModelProvider,
    detectors: DetectorSource,
    retriever: Retriever,
    limits: ChatLimits,
    grader_mode: GraderMode = "llm",
) -> Any:
    def emit(event: dict[str, object]) -> None:
        # The writer belongs to the running node, so it is read on each event.
        get_stream_writer()(event)

    graph = StateGraph(ChatState)
    graph.add_node("guard", partial(guard, emit=emit))
    graph.add_node("intake", partial(intake, models=models, detectors=detectors, limits=limits))
    graph.add_node("reply", partial(reply, emit=emit))
    graph.add_node("rewrite", partial(rewrite, models=models, emit=emit))
    graph.add_node(
        "retrieve",
        partial(retrieve, detectors=detectors, retriever=retriever, limits=limits, emit=emit),
    )
    graph.add_node("clarify", partial(clarify, emit=emit))
    graph.add_node(
        "grade", partial(grade, models=models, mode=grader_mode, limits=limits, emit=emit)
    )
    graph.add_node("generate", partial(generate, models=models, emit=emit))
    graph.add_node("validate", partial(validate, emit=emit))
    graph.add_node("suggest", partial(suggest, models=models, limits=limits, emit=emit))
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
