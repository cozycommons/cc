-- ig_logger platform tables: generic Instagram source subscriptions and the
-- scan-job queue. The Beli app becomes the first sink on this platform;
-- existing Beli state is backfilled below so the watcher keeps working
-- with zero missed scans.
--
-- ig_sources: one row per (account, Instagram handle). The watermark
-- (last_seen_ts) moved here from beli_accounts.last_eats_scan so every
-- source gets its own per-account watermark.
-- ig_scan_jobs: replaces eats_scan_jobs, adding source_handle (which
-- Instagram account the fetch box should pull).

create table if not exists public.ig_sources (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null,
  handle text not null,
  enabled boolean not null default true,
  last_seen_ts text not null default '',
  created_at timestamptz not null default now(),
  unique (account_id, handle)
);

create table if not exists public.ig_scan_jobs (
  id uuid primary key default gen_random_uuid(),
  source_handle text not null,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed')),
  scope text not null,
  digest jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.ig_sources enable row level security;
revoke all on public.ig_sources from public, anon, authenticated;
grant select, insert, update on public.ig_sources to service_role;

alter table public.ig_scan_jobs enable row level security;
revoke all on public.ig_scan_jobs from public, anon, authenticated;
grant select, insert, update on public.ig_scan_jobs to service_role;

-- Backfill: every Beli account keeps its @beli_eats subscription and
-- watermark; every queued scan job is carried over. last_eats_scan is a
-- timestamptz, so render it in the exact ISO-8601 shape the old watcher
-- used (e.g. 2026-09-26T17:14:52+00:00) to keep watermark comparisons
-- identical.
insert into public.ig_sources (account_id, handle, enabled, last_seen_ts)
select id, 'beli_eats', watcher_opt_in,
       coalesce(
         to_char(last_eats_scan at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
         ''
       )
from public.beli_accounts
on conflict (account_id, handle) do nothing;

insert into public.ig_scan_jobs
  (id, source_handle, status, scope, digest, error, created_at, updated_at)
select id, 'beli_eats', status, scope, digest, error, created_at, updated_at
from public.eats_scan_jobs
on conflict (id) do nothing;

drop table public.eats_scan_jobs;
