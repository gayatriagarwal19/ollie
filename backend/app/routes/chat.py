import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ollie_sdk import OllieSDK

from ..auth import get_current_user
from ..db import supabase
from ..llm.router import get_provider

router = APIRouter()

sdk = OllieSDK(
    ingest_url=os.environ.get("INGEST_URL", "http://localhost:4000/api/ingest"),
    get_provider=get_provider,
)

# Tracks in-flight generations so a client can cancel one mid-stream. Keyed
# by conversation id. A dict is fine for a single-process demo; a
# multi-instance deployment would need this in Redis (see README scaling).
active_generations: dict[str, asyncio.Task] = {}


class SendMessage(BaseModel):
    conversationId: Optional[str] = None
    model: str = "llama-3.3-70b-versatile"
    message: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    """List conversations for the current user, most recently active first."""
    res = (
        supabase.table("conversations")
        .select("*, messages(count)")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .execute()
    )
    conversations = []
    for row in res.data:
        messages = row.pop("messages", None) or []
        row["_count"] = {"messages": messages[0]["count"] if messages else 0}
        conversations.append(row)
    return conversations


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    """Resume a conversation: full message history."""
    conv_res = (
        supabase.table("conversations")
        .select("*")
        .eq("id", conversation_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not conv_res.data:
        raise HTTPException(status_code=404, detail="not_found")

    msgs_res = (
        supabase.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    return {**conv_res.data[0], "messages": msgs_res.data}


@router.post("/conversations/{conversation_id}/cancel")
async def cancel_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    """Cancel an in-flight generation."""
    task = active_generations.pop(conversation_id, None)
    if task:
        task.cancel()

    supabase.table("conversations").update({"status": "CANCELLED"}).eq("id", conversation_id).eq("user_id", user["id"]).execute()
    return {"status": "cancelled"}


@router.post("/chat")
async def chat(payload: SendMessage, user: dict = Depends(get_current_user)):
    """
    Send a message, stream the assistant's reply back over SSE. Maintains
    short conversational context by loading the last N messages for the
    conversation and passing them to the model.
    """
    if payload.conversationId:
        conv_res = (
            supabase.table("conversations")
            .select("*")
            .eq("id", payload.conversationId)
            .eq("user_id", user["id"])
            .execute()
        )
        if not conv_res.data:
            raise HTTPException(status_code=404, detail="not_found")
        conversation = conv_res.data[0]
    else:
        ins_res = supabase.table("conversations").insert({"title": payload.message[:60], "user_id": user["id"]}).execute()
        conversation = ins_res.data[0]

    supabase.table("messages").insert({
        "conversation_id": conversation["id"], "role": "USER", "content": payload.message,
    }).execute()

    # Short conversational context: last 20 messages is enough for a demo
    # chatbot without unbounded context growth. See README tradeoffs for why
    # this isn't full-history + summarization.
    hist_res = (
        supabase.table("messages")
        .select("*")
        .eq("conversation_id", conversation["id"])
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    history = list(reversed(hist_res.data))

    queue: asyncio.Queue = asyncio.Queue()

    async def run_generation():
        try:
            result = await sdk.chat(
                conversation_id=conversation["id"],
                model=payload.model,
                messages=[{"role": m["role"].lower(), "content": m["content"]} for m in history],
                on_chunk=lambda delta: queue.put_nowait(("delta", {"delta": delta})),
            )
            ins_res = supabase.table("messages").insert({
                "conversation_id": conversation["id"], "role": "ASSISTANT", "content": result["text"],
            }).execute()
            queue.put_nowait(("done", {"messageId": ins_res.data[0]["id"]}))
        except asyncio.CancelledError:
            queue.put_nowait(("cancelled", {}))
        except Exception as err:
            queue.put_nowait(("error", {"message": str(err)}))
        finally:
            active_generations.pop(conversation["id"], None)
            queue.put_nowait((None, None))  # sentinel: stop the SSE generator

    task = asyncio.create_task(run_generation())
    active_generations[conversation["id"]] = task

    async def event_stream():
        yield _sse("conversation", {"conversationId": conversation["id"]})
        while True:
            event, data = await queue.get()
            if event is None:
                break
            yield _sse(event, data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
