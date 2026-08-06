-- Solo Worker OS — Supabase schema (production-ready)
-- Run this in the Supabase SQL editor.
--
-- This is the single source of truth for the database schema.
-- It includes: user_id columns, user-scoped RLS policies, notifications,
-- workflow_steps, and router_weights tables.
-- Previous separate migration files (auth-migration.sql, migrate-columns.sql)
-- are now merged here for new deployments.

-- Extensions
create extension if not exists "pgcrypto";

-- ─── Tables ──────────────────────────────────────────────────────────────────

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  client_name text not null,
  project_type text not null,
  budget numeric not null,
  currency text not null default 'CNY'
    check (currency in ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'SGD')),
  deadline date not null,
  status text not null default 'active'
    check (status in ('active', 'delivered', 'invoiced', 'paid')),
  casper_address text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  project_id uuid references projects(id) on delete set null,
  conversation_id text,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

-- Migration: add conversation_id to existing tables (safe if column exists)
alter table messages add column if not exists conversation_id text;

create table if not exists agent_actions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  project_id uuid references projects(id) on delete cascade,
  action_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists knowledge_docs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  title text not null,
  content text not null,
  doc_type text not null default 'note',
  tags text[] default '{}',
  created_at timestamptz not null default now()
);

create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  -- project_id and the reminder/report types are written by app/api/cron/route.ts.
  project_id uuid references projects(id) on delete cascade,
  type text not null default 'info'
    check (type in ('info', 'reminder', 'report', 'warning',
                    'deadline_reminder', 'weekly_report')),
  title text not null,
  body text,
  read boolean not null default false,
  created_at timestamptz not null default now()
);

-- One row per project, keyed by project_id: app/api/workflow/[id]/route.ts upserts
-- with onConflict: 'project_id' and reads/writes a `checks` map, so project_id
-- must carry a unique constraint for that upsert to resolve.
create table if not exists workflow_steps (
  id uuid primary key default gen_random_uuid(),
  project_id uuid unique references projects(id) on delete cascade,
  stage text not null default 'kickoff',
  checks jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ─── Financial tables (commercialization) ─────────────────────────────────────

create table if not exists invoices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  project_id uuid not null references projects(id) on delete cascade,
  invoice_number text not null,
  amount numeric not null,
  currency text not null default 'CNY'
    check (currency in ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'SGD')),
  status text not null default 'sent'
    check (status in ('draft', 'sent', 'paid', 'overdue', 'cancelled')),
  issued_date date not null default current_date,
  due_date date,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists payments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  project_id uuid not null references projects(id) on delete cascade,
  invoice_id uuid references invoices(id) on delete set null,
  amount numeric not null,
  currency text not null default 'CNY'
    check (currency in ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'SGD')),
  method text not null default 'bank_transfer'
    check (method in ('bank_transfer', 'wechat', 'alipay', 'stripe', 'cash', 'other')),
  received_date date not null default current_date,
  notes text,
  created_at timestamptz not null default now()
);

-- Billing. Written only by the Stripe webhook (service role); clients read it
-- through lib/entitlements.ts to resolve quotas. One live row per user.
create table if not exists subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  plan text not null default 'free'
    check (plan in ('free', 'pro', 'team')),
  status text not null default 'incomplete'
    check (status in ('active', 'trialing', 'past_due', 'canceled',
                      'incomplete', 'paused')),
  stripe_customer_id text,
  stripe_subscription_id text,
  current_period_end timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Per-user daily usage counters, enforced by lib/rate-limit.ts.
--
-- This lives in Postgres rather than process memory because a serverless
-- deployment runs N instances, each with its own memory: an in-memory counter
-- turns a "30 messages/day" cap into "30 per instance per day", which is not a
-- cap at all. Every chat turn can fan out into several LLM calls, so an
-- ineffective cap is a direct billing exposure.
create table if not exists usage_counters (
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  kind text not null default 'chat',
  count integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, day, kind)
);

alter table usage_counters enable row level security;

-- Owner may read their own usage (to show "x/30 left"); writes go only through
-- the SECURITY DEFINER function below, so the count cannot be tampered with.
create policy "usage_counters_own_read" on usage_counters
  for select to authenticated
  using (user_id = auth.uid());

-- Atomic check-and-increment. Returns the post-increment count and whether the
-- call was allowed. Doing this in one statement avoids the race that a
-- read-then-write from the application layer would have under concurrency.
create or replace function increment_usage(
  p_kind text,
  p_limit integer
) returns table (allowed boolean, current_count integer)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid := auth.uid();
  v_day date := (now() at time zone 'utc')::date;
  v_count integer;
begin
  if v_user_id is null then
    return query select false, 0;
    return;
  end if;

  insert into usage_counters (user_id, day, kind, count, updated_at)
  values (v_user_id, v_day, p_kind, 1, now())
  on conflict (user_id, day, kind)
    do update set count = usage_counters.count + 1, updated_at = now()
  returning count into v_count;

  return query select (v_count <= p_limit), v_count;
end;
$$;

revoke all on function increment_usage(text, integer) from public;
grant execute on function increment_usage(text, integer) to authenticated;

-- Router self-learning persistence (keyword weight adjustments from user feedback)
create table if not exists router_weights (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  subagent_id text not null,
  keyword text not null,
  weight numeric not null default 1.0
    check (weight >= 0.1 and weight <= 2.0),
  adjustment_count integer not null default 0,
  updated_at timestamptz not null default now(),
  unique (user_id, subagent_id, keyword)
);

-- ─── Migrations for existing deployments ─────────────────────────────────────
-- `create table if not exists` above is a no-op on a database that already has
-- the older shape, so bring those columns forward explicitly.

alter table notifications add column if not exists project_id uuid
  references projects(id) on delete cascade;

do $$
begin
  alter table notifications drop constraint if exists notifications_type_check;
  alter table notifications add constraint notifications_type_check
    check (type in ('info', 'reminder', 'report', 'warning',
                    'deadline_reminder', 'weekly_report'));
end $$;

alter table workflow_steps add column if not exists checks jsonb not null default '{}'::jsonb;
alter table workflow_steps alter column stage set default 'kickoff';

-- Carry any data from the old status/payload shape into `checks`, then retire them.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'workflow_steps' and column_name = 'payload'
  ) then
    update workflow_steps
       set checks = coalesce(payload, '{}'::jsonb)
     where checks = '{}'::jsonb and payload is not null and payload <> '{}'::jsonb;
    alter table workflow_steps drop column payload;
  end if;

  if exists (
    select 1 from information_schema.columns
    where table_name = 'workflow_steps' and column_name = 'status'
  ) then
    alter table workflow_steps drop column status;
  end if;
end $$;

-- Collapse duplicate rows before adding the unique constraint the upsert needs.
delete from workflow_steps a
  using workflow_steps b
 where a.project_id = b.project_id
   and a.project_id is not null
   and a.created_at < b.created_at;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'workflow_steps_project_id_key'
  ) then
    alter table workflow_steps add constraint workflow_steps_project_id_key
      unique (project_id);
  end if;
end $$;

-- ─── Indexes ─────────────────────────────────────────────────────────────────

-- ─── Deliverables table (交付物沉淀) ─────────────────────────────────────────
create table if not exists deliverables (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  project_id uuid not null references projects(id) on delete cascade,
  title text not null,
  url text,
  content text,
  type text not null default 'final_delivery'
    check (type in ('final_delivery', 'draft', 'source_file', 'documentation', 'other')),
  status text not null default 'filed'
    check (status in ('filed', 'sent', 'accepted', 'rejected')),
  notes text,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_projects_status on projects(status);
create index if not exists idx_projects_deadline on projects(deadline);
create index if not exists idx_projects_user on projects(user_id);
create index if not exists idx_messages_created on messages(created_at desc);
create index if not exists idx_messages_user on messages(user_id);
create index if not exists idx_messages_conversation on messages(conversation_id, created_at desc);
create index if not exists idx_agent_actions_project on agent_actions(project_id, created_at desc);
create index if not exists idx_agent_actions_user on agent_actions(user_id);
create index if not exists idx_knowledge_docs_created on knowledge_docs(created_at desc);
create index if not exists idx_knowledge_docs_user on knowledge_docs(user_id);
create index if not exists idx_notifications_user on notifications(user_id, created_at desc);
create index if not exists idx_notifications_unread on notifications(user_id, read) where read = false;
-- Supports the cron dedupe check: same project + type, already created today?
create index if not exists idx_notifications_project_type
  on notifications(project_id, type, created_at desc);
create index if not exists idx_invoices_project on invoices(project_id);
create index if not exists idx_invoices_user on invoices(user_id);
create index if not exists idx_invoices_status on invoices(status);
create index if not exists idx_payments_project on payments(project_id);
create index if not exists idx_payments_user on payments(user_id);
create index if not exists idx_payments_received on payments(received_date desc);
create index if not exists idx_router_weights_lookup on router_weights(user_id, subagent_id);
create index if not exists idx_subscriptions_customer on subscriptions(stripe_customer_id);
create index if not exists idx_deliverables_project on deliverables(project_id);
create index if not exists idx_deliverables_user on deliverables(user_id);
create index if not exists idx_deliverables_type on deliverables(type, status);

-- Full-text search index (English + Chinese-friendly simple config)
create index if not exists knowledge_docs_fts
  on knowledge_docs
  using gin(to_tsvector('simple', title || ' ' || content));

-- ─── Triggers ────────────────────────────────────────────────────────────────

create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_projects_updated on projects;
create trigger trg_projects_updated
  before update on projects
  for each row execute function set_updated_at();

drop trigger if exists trg_workflow_steps_updated on workflow_steps;
create trigger trg_workflow_steps_updated
  before update on workflow_steps
  for each row execute function set_updated_at();

drop trigger if exists trg_invoices_updated on invoices;
create trigger trg_invoices_updated
  before update on invoices
  for each row execute function set_updated_at();

drop trigger if exists trg_deliverables_updated on deliverables;
create trigger trg_deliverables_updated
  before update on deliverables
  for each row execute function set_updated_at();

-- ─── Row Level Security ──────────────────────────────────────────────────────
-- User-scoped policies: each user can only access their own data.
-- user_id is nullable to support demo mode (no auth) and legacy rows.
-- Service role bypasses RLS entirely (used for cron jobs and admin tasks).

alter table projects enable row level security;
alter table messages enable row level security;
alter table agent_actions enable row level security;
alter table knowledge_docs enable row level security;
alter table notifications enable row level security;
alter table workflow_steps enable row level security;
alter table invoices enable row level security;
alter table payments enable row level security;
alter table router_weights enable row level security;
alter table subscriptions enable row level security;
alter table deliverables enable row level security;

-- Drop legacy permissive policies
drop policy if exists "projects_anon_all" on projects;
drop policy if exists "messages_anon_all" on messages;
drop policy if exists "agent_actions_anon_all" on agent_actions;
drop policy if exists "knowledge_docs_anon_all" on knowledge_docs;

-- User-scoped policies (user_id IS NULL allows demo-mode rows)
create policy "projects_own" on projects
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "messages_own" on messages
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "agent_actions_own" on agent_actions
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "knowledge_docs_own" on knowledge_docs
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "notifications_own" on notifications
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "invoices_own" on invoices
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "payments_own" on payments
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

create policy "deliverables_own" on deliverables
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

-- workflow_steps has no user_id — gated via project ownership
create policy "workflow_steps_via_project" on workflow_steps
  for all to anon, authenticated
  using (
    project_id in (
      select id from projects where user_id is null or user_id = auth.uid()
    )
  );

create policy "router_weights_own" on router_weights
  for all to anon, authenticated
  using (user_id is null or user_id = auth.uid())
  with check (user_id is null or user_id = auth.uid());

-- Read-only to the owner. There is deliberately no insert/update policy: the
-- Stripe webhook writes this table with the service role, so a client cannot
-- grant itself a paid plan even with a valid session.
create policy "subscriptions_own_read" on subscriptions
  for select to authenticated
  using (user_id = auth.uid());

-- The service role bypasses RLS entirely.

-- ─── External API keys (P2-5: API output layer) ───────────────────────────────
-- Allows external consumers (investors, FA firms, AI product teams) to access
-- anonymous benchmark data via a versioned API. Keys are hashed — we never
-- store plaintext keys after creation.
create table if not exists api_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  key_hash text not null unique,
  key_prefix text not null,          -- first 8 chars for display (sk_live_xxxx…)
  label text not null default 'Default',
  tier text not null default 'free'
    check (tier in ('free', 'pro', 'enterprise')),
  daily_limit integer not null default 100,
  requests_today integer not null default 0,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);

create index if not exists idx_api_keys_hash on api_keys(key_hash) where revoked_at is null;
create index if not exists idx_api_keys_user on api_keys(user_id);

alter table api_keys enable row level security;

create policy "api_keys_own" on api_keys
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Atomic daily reset + increment for API key usage.
create or replace function touch_api_key(p_hash text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row api_keys%rowtype;
  v_today date := (now() at time zone 'utc')::date;
begin
  select * into v_row from api_keys
    where key_hash = p_hash and revoked_at is null
    for update;

  if not found then
    raise exception 'invalid key';
  end if;

  -- Reset daily counter if the day changed
  if v_row.last_used_at is null
     or (v_row.last_used_at at time zone 'utc')::date < v_today then
    update api_keys
      set requests_today = 1, last_used_at = now()
      where id = v_row.id;
  else
    if v_row.requests_today >= v_row.daily_limit then
      raise exception 'rate limit';
    end if;
    update api_keys
      set requests_today = requests_today + 1, last_used_at = now()
      where id = v_row.id;
  end if;
end;
$$;

revoke all on function touch_api_key(text) from public;
grant execute on function touch_api_key(text) to authenticated, anon;
