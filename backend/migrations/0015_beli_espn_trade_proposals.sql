-- ESPN Fantasy: approval-gated trade proposals.
-- A trade is proposed first: the backend validates it against the live
-- league (every give player is on the account's own roster, every
-- receive player is on the counterparty's roster, the post-trade
-- roster is legal for BOTH teams under the league's slot counts, IR
-- accounting included, and the league's trade deadline has not passed)
-- and persists the validated snapshot here with status 'pending' and a
-- short expiry. A separate approve call then submits the offer as ONE
-- ESPN TRADE transaction and records the outcome back on the row
-- (offered / failed). The counterparty's accept/decline happens on
-- ESPN and is not tracked here — this table is the audit trail for
-- every trade offer this module submits, the same role
-- espn_roster_edits (migration 0014) plays for add/drop writes, so
-- service_role needs update as well as select/insert.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.espn_trade_proposals (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.espn_accounts(id) on delete cascade,
  league_id bigint not null,
  season integer not null,
  team_id integer not null,
  counterparty_team_id integer not null,
  give_player_ids jsonb not null,
  receive_player_ids jsonb not null,
  give_players jsonb,
  receive_players jsonb,
  preview text not null,
  status text not null default 'pending',
  error text,
  espn_transaction jsonb,
  espn_transaction_id text,
  expires_at timestamptz not null,
  executed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists espn_trade_proposals_account_created_idx
  on public.espn_trade_proposals (account_id, created_at desc);

alter table public.espn_trade_proposals enable row level security;
revoke all on public.espn_trade_proposals from public, anon, authenticated;
grant select, insert, update on public.espn_trade_proposals to service_role;
