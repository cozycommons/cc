-- @beli_eats scan-job queue for the poll-model fetch box.
--
-- CC never touches Instagram and accepts no inbound connections from the
-- fetch box: the box (a tiny service on the operator's VM) polls
-- GET /beli/eats/scan/pending for work, fetches Instagram locally, and
-- POSTs the posts back to /beli/eats/scan/{id}/complete. CC then runs the
-- ingest pipeline under the job's stored scope ('all' = every opted-in
-- account, via CC's internal authority — the poller never holds the
-- service key) and stores the resulting digest(s) on the job row.

create table if not exists public.eats_scan_jobs (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'pending'
    check (status in ('pending', 'running', 'done', 'failed')),
  scope text not null,
  digest jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.eats_scan_jobs enable row level security;
revoke all on public.eats_scan_jobs from public, anon, authenticated;
grant select, insert, update on public.eats_scan_jobs to service_role;
