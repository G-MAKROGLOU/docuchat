import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_chat_service
from app.api.schemas.chat import AskRequest, ConversationCreated, ConversationOut, TurnOut
from app.api.schemas.stream import STREAM_EVENT_ADAPTER
from app.application.chat import ChatService, ConversationNotFoundError
from app.infrastructure.metrics import CHAT_FIRST_TOKEN_SECONDS, CHAT_TURN_SECONDS, CHAT_TURNS

router = APIRouter(tags=["chat"])

Service = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(service: Service) -> ConversationCreated:
    return ConversationCreated(id=await service.start())


@router.get("/conversations/{conversation_id}", responses={404: {"description": "Unknown."}})
async def get_conversation(conversation_id: UUID, service: Service) -> ConversationOut:
    try:
        turns = await service.history(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found") from exc
    return ConversationOut(
        id=conversation_id,
        turns=[
            TurnOut(
                id=t.id,
                role=cast(Literal["user", "assistant"], t.role.value),
                text=t.text,
                citations=list(t.citations),
                created_at=t.created_at,
            )
            for t in turns
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: UUID, service: Service) -> None:
    # Idempotent: the browser sends it when the page unloads, maybe more than once.
    await service.end(conversation_id)


def _outcome(event: dict[str, Any]) -> str | None:
    """The turn outcome that a last event gives, for the metrics."""
    kind = event.get("type")
    if kind == "final":
        return "answer" if event.get("citations") else "reply"
    if kind == "refusal":
        return f"refusal_{event.get('reason')}"
    return str(kind) if kind in ("clarify", "error") else None


async def _sse(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[bytes]:
    started = time.perf_counter()
    first_token = True
    outcome = "disconnected"
    try:
        async for event in events:
            if event.get("type") == "token" and first_token:
                first_token = False
                CHAT_FIRST_TOKEN_SECONDS.observe(time.perf_counter() - started)
            # A clarify turn ends with a final event that carries the question; keep clarify.
            if outcome != "clarify":
                outcome = _outcome(event) or outcome
            # Validation keeps the stream inside the published event contract.
            payload = STREAM_EVENT_ADAPTER.dump_json(STREAM_EVENT_ADAPTER.validate_python(event))
            yield b"data: " + payload + b"\n\n"
    finally:
        CHAT_TURNS.labels(outcome).inc()
        CHAT_TURN_SECONDS.labels(outcome).observe(time.perf_counter() - started)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "StreamEvent objects."},
        404: {"description": "Unknown conversation."},
    },
)
async def ask(conversation_id: UUID, body: AskRequest, service: Service) -> StreamingResponse:
    try:
        events = await service.ask(conversation_id, body.text.strip())
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found") from exc
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
