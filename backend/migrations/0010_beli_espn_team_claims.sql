-- Confirmed Cozy profile links; only the backend may read or mutate identities.
create table if not exists public.espn_team_claims (
  id uuid primary key default gen_random_uuid(),
  season int not null,
  team_id int not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (season, team_id),
  unique (season, user_id)
);

alter table public.espn_team_claims enable row level security;
revoke all on public.espn_team_claims from public, anon, authenticated, service_role;
grant select, insert, delete on public.espn_team_claims to service_role;

-- A failed insert rolls back the deletion too. Serialize moves by one user;
-- the team uniqueness constraint arbitrates simultaneous claims by other users.
create or replace function public.espn_claim_team(p_season int, p_team_id int, p_user_id uuid)
returns void
language plpgsql
security invoker
set search_path = public
as $$
begin
  perform pg_advisory_xact_lock(hashtextextended(
    'espn_team_claims:' || p_season::text || ':' || p_user_id::text, 0));
  if exists (
    select 1 from public.espn_team_claims
    where season = p_season and team_id = p_team_id and user_id = p_user_id
  ) then
    return;
  end if;
  if exists (
    select 1 from public.espn_team_claims
    where season = p_season and team_id = p_team_id
  ) then
    raise unique_violation using message = 'team_claimed';
  end if;
  delete from public.espn_team_claims where season = p_season and user_id = p_user_id;
  insert into public.espn_team_claims (season, team_id, user_id)
    values (p_season, p_team_id, p_user_id);
end;
$$;

revoke all on function public.espn_claim_team(int, int, uuid) from public, anon, authenticated;
grant execute on function public.espn_claim_team(int, int, uuid) to service_role;
