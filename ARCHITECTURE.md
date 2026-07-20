# Architecture Notes

## Ingestion flow

```
SDK (fire-and-forget POST, via a background asyncio task)
   → POST /api/ingest
       1. Pydantic-validate payload
       2. Insert raw_ingestion_events row (status=RECEIVED, or FAILED if invalid)
       3. Publish {rawEventId, ...event} to RabbitMQ queue "inference.logs"
       4. Return 202 immediately
   → RabbitMQ consumer (separate async task, same process for this demo)
       1. Redact PII in input/output previews
       2. Derive total_tokens if not provided
       3. Insert inference_logs row
       4. Update raw_ingestion_events.status = PROCESSED, link inference_log_id
       5. If messageId present, backfill messages.inference_log_id
       6. ack the message (or reject -> dropped, see failure handling)
```

If RabbitMQ is unreachable when `/api/ingest` tries to publish, it falls back
to calling the same processing function synchronously in the request, so the
log is still written — just without the async decoupling benefit for that
one event.

## Logging strategy

Every LLM call goes through `OllieSDK.chat()`, never through a provider SDK
directly from application code. This is the auto-instrumentation seam:
timing starts before the provider call and stops after; token counts come
straight off the provider's response object; success/error/timeout status is
derived from whether the call raised and what kind of exception. The event
is POSTed to the ingestion endpoint from a background `asyncio.create_task`,
never awaited by the caller, so a slow or down ingestion service adds zero
latency to the user-facing chat response — logging is strictly best-effort
relative to the product feature it's observing.

## Scaling considerations

- **Chat/API tier**: stateless except for `active_generations` (in-memory
  cancellation tracking) — horizontally scalable once that dict is moved to
  Redis (per-conversation key, so any instance can look up and cancel a
  generation regardless of which instance started it).
- **Ingestion tier**: already decoupled via the queue, so it scales
  independently of chat traffic — add more consumer instances (with
  RabbitMQ's built-in round-robin dispatch across consumers on the same
  queue) if ingestion volume grows faster than chat volume.
- **Database**: `inference_logs` is the highest-write-volume table and is
  append-only in practice (never updated except the one
  `raw_event_id`/`message_id` backfill), which makes it a good candidate for
  time-based partitioning once volume grows — partition by `created_at`
  month, drop/archive old partitions instead of deleting rows.
- **`supabase-py`'s sync client**: currently called directly from async
  FastAPI route handlers, which briefly blocks the event loop per query.
  At real scale, wrap these in `asyncio.to_thread(...)` (or move to
  `supabase-py`'s async client) so one slow query can't stall unrelated
  concurrent requests on the same worker.
- **Message queue choice**: RabbitMQ's single-queue model is enough while
  there's one consumer group (ingestion writes). If a second, independent
  consumer needs to read the same event stream at its own pace (e.g. a
  billing pipeline, a real-time dashboard websocket pusher), that's the
  signal to move to Kafka, where multiple consumer groups can each replay
  the log independently instead of competing for the same queued messages.

## Failure handling assumptions

- **Ingestion endpoint down / unreachable**: SDK's fire-and-forget POST
  fails silently (logged to stderr, not surfaced to the chat caller) — a
  missing log is preferred over a broken chat feature.
- **Queue down at publish time**: ingestion route falls back to a synchronous
  DB write of the same event, so the log isn't lost, only the async
  decoupling is (temporarily, for that request).
- **Payload fails validation**: still recorded in `raw_ingestion_events` with
  `status=FAILED` and the Pydantic validation error attached, rather than
  discarded — so malformed-payload bugs in the SDK are debuggable after the
  fact.
- **Consumer raises while processing a message**: `aio_pika`'s
  `message.process(requeue=False)` rejects the message without requeueing on
  exception (avoids an infinite poison-message loop in this demo).
  Documented improvement: route rejected messages to a dead-letter queue
  instead of dropping them, so they can be inspected/replayed.
- **LLM provider call fails or times out**: the SDK still logs the attempt
  (status=ERROR, with the exception message, and null token counts), and the
  error propagates to the chat route, which sends an `error` SSE event to
  the frontend rather than leaving the request hanging.
- **User cancels mid-stream**: the chat route runs generation as a tracked
  `asyncio.Task`; cancelling it raises `asyncio.CancelledError` inside
  `OllieSDK.chat()`, which logs status=ERROR ("Aborted") and re-raises; the
  chat route catches that and sends a `cancelled` SSE event, and the
  conversation is marked `CANCELLED` in Supabase via
  `POST /api/conversations/{id}/cancel`.

