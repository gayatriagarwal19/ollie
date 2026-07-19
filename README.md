# Ollive — Inference Logging & Ingestion System

A chatbot backed by an auto-instrumenting LLM SDK, an event-driven ingestion
pipeline, and Supabase (Postgres) for messages + inference logs.

**Stack:** React (frontend) · FastAPI (backend) · Supabase (DB) · RabbitMQ
(event queue) · Anthropic + OpenAI (LLM providers).

```
┌──────────┐   SSE stream    ┌──────────────┐   sdk.chat()   ┌───────────────┐
│  React   │ ◄─────────────► │   FastAPI    │ ─────────────► │  OllieSDK     │
│  Chat UI │                 │  chat routes │                │ (auto-instr.) │
└──────────┘                 └──────┬───────┘                └───────┬───────┘
                                     │ writes                          │ POST /api/ingest
                                     ▼                                  ▼
                              ┌────────────┐                    ┌───────────────┐
                              │  Supabase  │ ◄───────────────── │  Ingestion    │
                              │ (Postgres: │     consumer       │  API + queue  │
                              │  messages, │ ◄───writes───────  │  (RabbitMQ)   │
                              │  logs)     │                    │               │
                              └────────────┘                    └───────────────┘
```

## 1. Setup

### 0. One-time: create the schema in Supabase

1. Create a project at supabase.com (or run `supabase start` locally if you
   have the Supabase CLI).
2. Open the SQL editor and run `backend/supabase/schema.sql` once (or
   `supabase db push` if you're using the CLI with migrations).
3. Grab your project URL and `service_role` key from Settings -> API.

### Docker Compose (recommended — one command)

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
# (and OPENAI_API_KEY if you want the gpt-4o models)
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:4000 (interactive docs at `/docs`, courtesy
  of FastAPI's automatic OpenAPI generation)
- RabbitMQ management UI: http://localhost:15672 (guest/guest)

Postgres itself isn't a container here — the backend talks to your Supabase
project directly, so step 0 above has to happen before this will work.

### Local (without Docker)

```bash
# 1. RabbitMQ
docker compose up rabbitmq

# 2. Backend
cd backend
cp ../.env.example .env   # fill in SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / RABBITMQ_URL=amqp://localhost
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../sdk
uvicorn app.main:app --reload --port 4000

# 3. Frontend
cd frontend
npm install
npm run dev
```

## 2. Architecture overview

**Chatbot (deliverable 1).** React SPA talks to FastAPI over SSE for
streaming replies. Conversations and messages are stored in Supabase;
"short conversational context" is implemented as the last 20 messages in the
conversation, sent to the model on every turn (see tradeoffs below for why
not full history or summarization).

**SDK / wrapper (deliverable 2).** `sdk/ollie_sdk` is a standalone,
pip-installable package exporting `OllieSDK`. It doesn't know about any
specific LLM provider — the host app passes in a `get_provider(model)`
resolver, so the SDK stays generic and reusable rather than being coupled to
this app's provider setup. Every LLM call in the app goes through
`sdk.chat(...)`, which:
- routes to the right provider adapter (`backend/app/llm/providers/*`) based
  on the model name, so adding a provider is a one-line change to
  `backend/app/llm/router.py` and nothing else — this is the
  "auto-instrument" mechanism the assignment asks about: any call made
  *through the SDK* is logged automatically, with no per-call-site logging
  code.
- captures every metadata field the assignment lists: model, provider,
  latency, input/output tokens, timestamps, status/errors, conversation ID,
  and input/output previews.
- POSTs the resulting event to the ingestion endpoint **fire-and-forget**,
  scheduled as a background `asyncio` task and never awaited on the response
  path, so ingestion downtime or slowness never adds latency to the chat
  response itself.

**Ingestion pipeline (deliverable 3).** `POST /api/ingest`:
1. Validates the payload against a Pydantic model.
2. Stores the raw payload verbatim in `raw_ingestion_events` (audit/replay
   buffer — see schema notes below).
3. Publishes a message onto a RabbitMQ queue (via `aio-pika`) and returns
   `202` immediately.
4. A separate async consumer (started alongside the API process) pulls from
   the queue, redacts PII in preview fields, extracts/derives metadata (e.g.
   `total_tokens` when only input/output are given), and writes the
   `inference_logs` row, linking it back to the raw event and the chat
   message it produced.

This is the event-based architecture bonus: the HTTP endpoint's job is
"validate and hand off," not "validate and write," which decouples ingestion
throughput from chat traffic.

**Database (deliverable 4).** Supabase project (Postgres underneath). See
schema design decisions below.

**Bonus items implemented:** multi-provider support (Anthropic + OpenAI
behind one interface), streaming responses (SSE + provider-level streaming),
Docker Compose one-command setup, event-based architecture (RabbitMQ), PII
redaction on log previews. Not implemented: live dashboards (see "what I'd
improve"), k8s deployment (documented approach instead, since that needs
infra I don't have in this environment).

## 3. Schema design decisions

Schema lives in `backend/supabase/schema.sql` as plain SQL — applied to a
Supabase project directly (SQL editor or `supabase db push`), not through an
ORM's migration tool.

- **`conversations` / `messages` vs. `inference_logs` are separate tables**,
  not one table with nullable "log" columns. They're on different access
  paths: messages are read/written transactionally on every chat turn;
  inference logs are written once (by the ingestion consumer, not the chat
  request) and read for observability queries (by time range, by provider,
  by status). Mixing them would mean every message read carries dead log
  columns, and every log query has to filter out user/assistant rows that
  aren't logs.
- **`raw_ingestion_events` is kept separate from `inference_logs`.** It
  stores exactly what the SDK sent, before parsing. If a bug in metadata
  extraction is found later, the raw events can be reprocessed without
  having lost data — `inference_logs` is a derived, indexable view over it,
  not the source of truth for "what actually happened."
- **`messages.inference_log_id` is nullable and unique**, linking an
  assistant message to the exact inference call that produced it. User
  messages have no log. This lets the UI (or an analytics query) go from
  "this reply felt slow" straight to its latency/token numbers, without a
  fuzzy join on timestamps.
- **Indexes** are on the actual query patterns: `(conversation_id,
  created_at)` for resuming/scrolling a conversation, `(provider, model,
  created_at)` and `(status, created_at)` for dashboard-style aggregation.
- **Previews, not full payloads, in `inference_logs`.** Input/output
  previews are truncated (300 chars) and PII-redacted. Full content already
  lives in `messages.content`; duplicating it untruncated in the log table
  would double storage and double the PII surface for no query benefit.
- **RLS is enabled on every table, but the backend connects with the
  `service_role` key**, which bypasses it. That's a deliberate tradeoff for
  this app's shape: the frontend never talks to Supabase directly, only to
  our own FastAPI service, so there's no browser-facing client that needs
  row-level policies yet. RLS is left on (rather than disabled) so that if
  a browser client is ever added later, it fails closed by default instead
  of open.

## 4. Tradeoffs made

- **RabbitMQ over Kafka.** For this scale (a single chatbot's logs), Kafka's
  partitioning/replay-log model is more operational overhead than benefit;
  RabbitMQ's simple durable queue gives the "decouple ingestion from
  writing" benefit with far less setup. Kafka would be the right call once
  there are multiple independent consumers needing their own offsets (e.g.
  a dashboard consumer and a billing consumer reading the same stream
  independently) — see "what I'd improve."
- **Fire-and-forget logging from the SDK, with a synchronous fallback in the
  ingestion route if the queue is down.** Availability of the chat feature
  is prioritized over never losing a log; if RabbitMQ is briefly down, the
  ingestion API just writes the log row directly instead of queuing it, so
  no message-loss vs. no downtime is resolved in favor of "log write still
  happens, just synchronously."
- **`supabase-py`'s synchronous client, called from async route handlers.**
  Each `.execute()` call briefly blocks the event loop rather than being
  awaited natively. Fine at this request volume; a production version would
  wrap these calls in `asyncio.to_thread(...)` or move to `supabase-py`'s
  async client so a slow query can't stall other in-flight requests.
- **Short context window (last 20 messages) instead of full history or
  summarization.** Simpler and predictable-cost, at the expense of losing
  detail on very long conversations. A real product would summarize older
  turns instead of dropping them.
- **Single-process `active_generations` dict for cancellation** rather than
  Redis. Correct for one backend instance; would break with multiple
  instances behind a load balancer (see scaling considerations).
- **Pattern-based PII redaction**, not an ML/NER-based approach. Cheap and
  fast, catches the common structured cases (emails, phone numbers, card
  numbers, API keys), but will miss free-text PII (names, addresses in
  prose). Applied only to log previews, never to what's shown to the user
  or sent to the model.

## 5. What I'd improve with more time

- **Dashboards.** Latency/throughput/error-rate charts (p50/p95 latency by
  model, error rate over time, tokens/cost by conversation) — the schema
  already supports these queries via the `(provider, model, created_at)` and
  `(status, created_at)` indexes; I'd add a `/api/metrics` aggregation
  endpoint and a small charts view in the frontend.
- **Async Supabase calls.** Replace the synchronous `supabase-py` calls with
  `asyncio.to_thread(...)` or the async client, so a slow DB query can't
  block other requests on the same worker.
- **Multi-instance cancellation and streaming.** Move `active_generations`
  into Redis (key per conversation, TTL'd) so cancel works when the backend
  is horizontally scaled.
- **Dead-letter queue** for ingestion events that repeatedly fail to
  process, instead of dropping after one reject.
- **Kafka migration path** if a second independent consumer appears (e.g.
  a billing pipeline reading the same log stream as the dashboard).
- **k8s manifests.** I've documented the deployment shape below rather than
  standing up a live cluster, since that requires infrastructure/credentials
  I don't have in this environment. See `ARCHITECTURE.md`.
- **Auth.** There's currently no auth on the API — fine for a take-home demo,
  not for anything real.

See `ARCHITECTURE.md` for ingestion flow, logging strategy, scaling, and
failure-handling notes in more depth.
