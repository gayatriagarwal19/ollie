-- Ollive schema for Supabase (plain Postgres — run this in the Supabase
-- SQL editor once, or via `supabase db push` if you're using the CLI).
-- Language-agnostic: unaffected by the backend being Node or FastAPI.
--
-- Design notes (see README for full rationale):
--
-- - conversations/messages are the "product" tables: what the chatbot UI
--   reads/writes on every turn. Kept lean because they're on the hot path.
--
-- - inference_logs is the "observability" table: one row per LLM call,
--   written by the ingestion consumer, not the chat request path.
--   Deliberately a separate table (not extra nullable columns on messages)
--   because it's queried by time range / provider / status for dashboards,
--   a different access pattern than "load this conversation's messages".
--
-- - raw_ingestion_events stores the payload the SDK sent, before parsing.
--   Kept separate so a parsing bug never loses raw data — it's the
--   audit/replay buffer.

create extension if not exists "pgcrypto"; -- for gen_random_uuid()

create type conversation_status as enum ('ACTIVE', 'CANCELLED');
create type message_role as enum ('USER', 'ASSISTANT', 'SYSTEM');
create type ingestion_status as enum ('RECEIVED', 'PROCESSED', 'FAILED');
create type inference_status as enum ('SUCCESS', 'ERROR', 'TIMEOUT');

create table conversations (
  id          uuid primary key default gen_random_uuid(),
  title       text,
  status      conversation_status not null default 'ACTIVE',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index idx_conversations_status_updated on conversations (status, updated_at desc);

create table inference_logs (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  provider        text not null,
  model           text not null,
  status          inference_status not null,
  error_message   text,
  latency_ms      integer,
  input_tokens    integer,
  output_tokens   integer,
  total_tokens    integer,
  input_preview   text,
  output_preview  text,
  requested_at    timestamptz not null,
  responded_at    timestamptz,
  created_at      timestamptz not null default now()
);
create index idx_logs_conversation_created on inference_logs (conversation_id, created_at);
create index idx_logs_provider_model_created on inference_logs (provider, model, created_at);
create index idx_logs_status_created on inference_logs (status, created_at);

create table messages (
  id                uuid primary key default gen_random_uuid(),
  conversation_id   uuid not null references conversations(id) on delete cascade,
  role              message_role not null,
  content           text not null,
  -- Links an assistant message back to the inference call that produced it.
  -- Null for user messages. Unique so each log backs at most one message.
  inference_log_id  uuid unique references inference_logs(id),
  created_at        timestamptz not null default now()
);
create index idx_messages_conversation_created on messages (conversation_id, created_at);

create table raw_ingestion_events (
  id                uuid primary key default gen_random_uuid(),
  inference_log_id  uuid unique references inference_logs(id),
  status            ingestion_status not null default 'RECEIVED',
  payload           jsonb not null,
  parse_error       text,
  received_at       timestamptz not null default now()
);
create index idx_raw_events_status_received on raw_ingestion_events (status, received_at);

-- The backend connects with the service_role key and talks to Postgres
-- directly through PostgREST, bypassing RLS by design (this is a trusted
-- server, not a browser client) — see README "schema design decisions" for
-- the tradeoff this implies. If you ever expose these tables to a browser
-- client directly, add RLS policies before doing so.
alter table conversations enable row level security;
alter table messages enable row level security;
alter table inference_logs enable row level security;
alter table raw_ingestion_events enable row level security;
