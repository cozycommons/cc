-- One live approval per connector lineup proposal.
-- A lineup proposal is a dry-run row in the append-only espn_lineup_runs, so
-- unlike a roster edit or trade it has no status to claim. Receipts are unique
-- only per (user, idempotency_key), so without this a second key could approve
-- the same proposal again and replan from lagging ESPN reads. The first
-- approval inserts this row just before its live run; a later approval of the
-- same proposal, under any key, finds it and replays or rereads the first
-- attempt instead of submitting. Rows are never released by the connector.
create table public.espn_lineup_approvals (
  proposal_id uuid primary key references public.espn_lineup_runs(id) on delete cascade,
  user_id uuid not null,
  idempotency_key text not null,
  created_at timestamptz not null default now(),
  foreign key (user_id, idempotency_key)
    references public.espn_agent_receipts(user_id, idempotency_key) on delete cascade
);
alter table public.espn_lineup_approvals enable row level security;
-- Revoke service_role too: Supabase default privileges would otherwise grant it UPDATE and DELETE.
revoke all on public.espn_lineup_approvals from public, anon, authenticated, service_role;
grant select, insert on public.espn_lineup_approvals to service_role;
