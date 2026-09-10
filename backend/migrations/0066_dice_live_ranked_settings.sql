-- Live results may be corrected as ranked/unranked metadata without changing
-- the append-only scoring ledger. The API recomputes profile aggregates after
-- changing the materialized game's ranked flag.
alter table public.dice_live_matches
  add column if not exists ranked boolean not null default false;
