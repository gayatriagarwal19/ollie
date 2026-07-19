from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from ..db import supabase
from ..queue.rabbitmq import publish_log_event
from ..redaction.pii import to_preview

router = APIRouter()


class IngestionEvent(BaseModel):
    """
    The contract the SDK (see /sdk/ollie_sdk) sends. Kept intentionally
    close to the assignment's example metadata list.
    """
    conversationId: str
    provider: str
    model: str
    status: str  # SUCCESS | ERROR | TIMEOUT
    errorMessage: Optional[str] = None
    latencyMs: Optional[int] = None
    inputTokens: Optional[int] = None
    outputTokens: Optional[int] = None
    totalTokens: Optional[int] = None
    inputPreview: Optional[str] = None
    outputPreview: Optional[str] = None
    requestedAt: str
    respondedAt: Optional[str] = None
    # Ties this log to the assistant message it produced, once that message
    # has been persisted. See routes/chat.py for the two-step write.
    messageId: Optional[str] = None


@router.post("")
async def ingest(request: Request):
    """
    Receives logs from the SDK "in near real time". Deliberately thin:
    validate shape, stash the raw payload, hand off to the queue, return
    immediately. All the actual DB writes for inference_logs happen in the
    consumer (queue/rabbitmq.py -> process_ingestion_event below), which is
    what makes this an event-based pipeline rather than a synchronous one.
    """
    body = await request.json()

    parse_error = None
    event: Optional[IngestionEvent] = None
    try:
        event = IngestionEvent(**body)
    except ValidationError as err:
        parse_error = err.json()

    raw_res = (
        supabase.table("raw_ingestion_events")
        .insert({
            "payload": body,
            "status": "RECEIVED" if event else "FAILED",
            "parse_error": parse_error,
        })
        .execute()
    )
    raw_row = raw_res.data[0]

    if event is None:
        return JSONResponse(status_code=422, content={"error": "invalid_payload", "details": parse_error})

    event_dict = event.model_dump()
    event_dict["rawEventId"] = raw_row["id"]

    try:
        await publish_log_event(event_dict)
        return {"status": "queued", "rawEventId": raw_row["id"]}
    except Exception as err:
        # Queue is down: fall back to writing the log synchronously so we
        # don't silently drop data. This trades the async-pipeline benefit
        # for durability during a queue outage -- see README failure handling.
        print(f"Queue publish failed, falling back to sync write: {err}")
        await process_ingestion_event(event_dict)
        return {"status": "written_sync", "rawEventId": raw_row["id"]}


async def process_ingestion_event(event: dict) -> dict:
    """
    The actual ingestion logic: extract metadata, redact PII in previews,
    persist inference_logs, link it back to raw_ingestion_events and (if
    provided) the message it produced. Called by the RabbitMQ consumer in
    main.py, and directly above as a same-process fallback if the queue is
    unreachable.
    """
    input_tokens = event.get("inputTokens")
    output_tokens = event.get("outputTokens")
    total_tokens = event.get("totalTokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    log_res = (
        supabase.table("inference_logs")
        .insert({
            "conversation_id": event["conversationId"],
            "provider": event["provider"],
            "model": event["model"],
            "status": event["status"],
            "error_message": event.get("errorMessage"),
            "latency_ms": event.get("latencyMs"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "input_preview": to_preview(event["inputPreview"]) if event.get("inputPreview") else None,
            "output_preview": to_preview(event["outputPreview"]) if event.get("outputPreview") else None,
            "requested_at": event["requestedAt"],
            "responded_at": event.get("respondedAt"),
        })
        .execute()
    )
    log = log_res.data[0]

    supabase.table("raw_ingestion_events").update(
        {"status": "PROCESSED", "inference_log_id": log["id"]}
    ).eq("id", event["rawEventId"]).execute()

    if event.get("messageId"):
        supabase.table("messages").update(
            {"inference_log_id": log["id"]}
        ).eq("id", event["messageId"]).execute()

    return log
