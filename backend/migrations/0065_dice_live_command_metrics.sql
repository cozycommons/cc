-- Durable, low-volume telemetry for adaptive live-command hedging.
-- The browser reports through the authenticated backend; only the service
-- role can access the table directly.

create table public.dice_live_command_metrics (
  id bigint generated always as identity primary key,
  operation_id text not null,
  match_id uuid not null references public.dice_live_matches(id) on delete cascade,
  referee_id uuid not null references public.dice_profiles(user_id) on delete cascade,
  attempts smallint not null,
  winner text not null,
  outcome text not null,
  status smallint not null,
  duration_ms integer not null,
  hedge_delay_ms integer not null,
  loser_cancelled boolean not null,
  created_at timestamptz not null default now(),
  constraint dice_live_command_metrics_operation_id_check check (
    operation_id ~ '^[A-Za-z0-9._:-]{1,128}$'
  ),
  constraint dice_live_command_metrics_attempts_check check (attempts in (1, 2)),
  constraint dice_live_command_metrics_winner_check check (
    winner in ('original', 'hedge', 'retry')
  ),
  constraint dice_live_command_metrics_outcome_check check (
    outcome in ('resolved', 'rejected')
  ),
  constraint dice_live_command_metrics_status_check check (status between 0 and 599),
  constraint dice_live_command_metrics_duration_check check (
    duration_ms between 0 and 120000
  ),
  constraint dice_live_command_metrics_hedge_delay_check check (
    hedge_delay_ms between 750 and 2500
  ),
  unique (match_id, referee_id, operation_id)
);

create index dice_live_command_metrics_created_at_idx
  on public.dice_live_command_metrics (created_at desc);

alter table public.dice_live_command_metrics enable row level security;
revoke all on table public.dice_live_command_metrics from public, anon, authenticated;
grant all on table public.dice_live_command_metrics to service_role;
grant usage, select on sequence public.dice_live_command_metrics_id_seq to service_role;
