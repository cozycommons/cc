#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
db_url="${DB_URL:-}"

if [[ -z "$db_url" ]]; then
  echo "DB_URL is required for the isolated Dice test database." >&2
  exit 1
fi

psql "$db_url" --no-psqlrc --set ON_ERROR_STOP=1 <<'SQL'
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
end
$$;

create schema if not exists auth;
-- Match Supabase's service-role access for tables created by migrations.
grant usage on schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
create table if not exists auth.users (
  id uuid primary key,
  created_at timestamptz not null default now()
);
SQL

SUPABASE_DB_URL="$db_url" python3 "$repo_dir/backend/migration_runner.py" --family all

psql "$db_url" --no-psqlrc --set ON_ERROR_STOP=1 <<'SQL'
insert into auth.users (id) values
  ('00000000-0000-0000-0000-000000000001'),
  ('00000000-0000-0000-0000-000000000002'),
  ('00000000-0000-0000-0000-000000000003'),
  ('00000000-0000-0000-0000-000000000004'),
  ('10000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000002'),
  ('10000000-0000-0000-0000-000000000003'),
  ('10000000-0000-0000-0000-000000000004')
on conflict (id) do nothing;

insert into public.dice_profiles (
  user_id, display_name, elo_rating, rating_deviation,
  games_played, ranked_games_played, wins, losses, ranked_wins, ranked_losses
) values
  ('00000000-0000-0000-0000-000000000001', 'Test One', 1523, 297.5, 1, 1, 1, 0, 1, 0),
  ('00000000-0000-0000-0000-000000000002', 'Test Two', 1523, 297.5, 1, 1, 1, 0, 1, 0),
  ('00000000-0000-0000-0000-000000000003', 'Test Three', 1477, 297.5, 1, 1, 0, 1, 0, 1),
  ('00000000-0000-0000-0000-000000000004', 'Test Four', 1477, 297.5, 1, 1, 0, 1, 0, 1)
on conflict (user_id) do nothing;

insert into public.dice_profiles (user_id, display_name) values
  ('10000000-0000-0000-0000-000000000001', 'Live Test One'),
  ('10000000-0000-0000-0000-000000000002', 'Live Test Two'),
  ('10000000-0000-0000-0000-000000000003', 'Live Test Three'),
  ('10000000-0000-0000-0000-000000000004', 'Live Test Four')
on conflict (user_id) do nothing;

insert into public.dice_tournaments (id, name, starts_at, host_user_ids, created_by)
values (
  '30000000-0000-0000-0000-000000000001', 'Virtual Dice Test',
  '2026-01-01', array['10000000-0000-0000-0000-000000000001'::uuid],
  '10000000-0000-0000-0000-000000000001'
)
on conflict (id) do nothing;

insert into public.dice_tournament_enrollments (tournament_id, user_id) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002'),
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003')
on conflict (tournament_id, user_id) do nothing;

insert into public.dice_games (
  id, created_by, ranked, team1_score, team2_score, winner_team, played_at
) values (
  '10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  true, 21, 18, 1, '2026-01-01T00:00:00Z'
)
on conflict (id) do nothing;

insert into public.dice_game_players (
  game_id, user_id, team, elo_before, elo_after,
  rating_deviation_before, rating_deviation_after
) values
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 1, 1500, 1523, 350, 297.5),
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002', 1, 1500, 1523, 350, 297.5),
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000003', 2, 1500, 1477, 350, 297.5),
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000004', 2, 1500, 1477, 350, 297.5)
on conflict (game_id, user_id) do nothing;
SQL
