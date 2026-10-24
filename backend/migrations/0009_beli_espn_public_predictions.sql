-- Public-v1 estimates only; private ESPN account/snapshot data stays separate.
-- The shared app-schema ("beli") release family applies this before HTTP starts.
create table if not exists public.espn_public_predictions (
  id uuid primary key default gen_random_uuid(),
  matchup_id bigint not null,
  generated_at timestamptz not null,
  received_at timestamptz not null default now(),
  payload jsonb not null,
  unique (matchup_id, generated_at)
);

create index if not exists espn_public_predictions_generated_idx
  on public.espn_public_predictions (generated_at desc, received_at desc);

alter table public.espn_public_predictions enable row level security;
revoke all on public.espn_public_predictions from public, anon, authenticated;
-- Uploads use ON CONFLICT DO NOTHING; existing snapshots cannot be overwritten.
revoke update, delete, truncate on public.espn_public_predictions from service_role;
grant select, insert on public.espn_public_predictions to service_role;
