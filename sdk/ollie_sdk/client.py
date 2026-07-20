"""
OllieSDK: the "lightweight wrapper around LLM calls" deliverable.

Design goal is auto-instrumentation: any code path that wants to talk to an
LLM calls sdk.chat(...) instead of a provider SDK directly, and every
metadata field the assignment lists is captured automatically, with zero
extra code at the call site. The SDK itself doesn't know about any specific
provider (Anthropic, OpenAI, Groq, ...) — the caller passes in a `get_provider`
resolver, so this package stays a generic, reusable wrapper rather than
being coupled to one app's provider setup. If the host app adds a new
provider to its own resolver, calls through it are instrumented for free —
nothing in this file needs to change.

Logs are POSTed to the ingestion endpoint fire-and-forget (as a background
asyncio task, never awaited on the response path) so a slow or unavailable
ingestion service never adds latency to the user-facing chat response.
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx


class OllieSDK:
    def __init__(
        self,
        ingest_url: str,
        get_provider: Callable[[str], Any],
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.ingest_url = ingest_url
        self.get_provider = get_provider
        self._client = http_client or httpx.AsyncClient(timeout=5.0)

    async def chat(
        self,
        *,
        conversation_id: str,
        model: str,
        messages: list[dict],
        system: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> dict:
        provider = self.get_provider(model)
        requested_at = datetime.now(timezone.utc)
        started_at = time.perf_counter()

        try:
            if on_chunk:
                result = await provider.stream(model=model, messages=messages, system=system, on_chunk=on_chunk)
            else:
                result = await provider.complete(model=model, messages=messages, system=system)
        except asyncio.CancelledError:
            self._log_fire_and_forget(
                conversation_id, provider.id, model, "ERROR", "Aborted",
                started_at, requested_at, messages, None,
            )
            raise
        except Exception as err:
            self._log_fire_and_forget(
                conversation_id, provider.id, model, "ERROR", str(err),
                started_at, requested_at, messages, None,
            )
            raise

        self._log_fire_and_forget(
            conversation_id, provider.id, model, "SUCCESS", None,
            started_at, requested_at, messages, result,
        )
        return result

    def _preview(self, messages: list[dict]) -> Optional[str]:
        return messages[-1]["content"] if messages else None

    def _log_fire_and_forget(self, conversation_id, provider_id, model, status, error_message, started_at, requested_at, messages, result):
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        input_tokens = result.get("input_tokens") if result else None
        output_tokens = result.get("output_tokens") if result else None
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        event = {
            "id": str(uuid.uuid4()),
            "conversationId": conversation_id,
            "provider": provider_id,
            "model": model,
            "status": status,
            "errorMessage": error_message,
            "latencyMs": latency_ms,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
            "inputPreview": self._preview(messages),
            "outputPreview": result.get("text") if result else None,
            "requestedAt": requested_at.isoformat(),
            "respondedAt": datetime.now(timezone.utc).isoformat(),
        }
        # Fire-and-forget: scheduled as a background task, never awaited by
        # the caller. Errors are swallowed (with a stderr warning) rather
        # than surfaced — a logging failure should never break the chat
        # feature it's observing.
        asyncio.create_task(self._post_log(event))

    async def _post_log(self, event: dict):
        try:
            await self._client.post(self.ingest_url, json=event)
        except Exception as err:
            print(f"[OllieSDK] failed to send log: {err}")
