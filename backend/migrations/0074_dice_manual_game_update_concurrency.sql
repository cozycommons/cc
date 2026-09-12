-- Reject a stale completed-game editor inside the same transaction that owns
-- the canonical rating replay. The expected revision is transaction-local, so
-- live materialization and other rating mutations keep their existing path.

create or replace function public.dice_game_reject_stale_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  expected_updated_at text;
begin
  expected_updated_at := current_setting('dice.game_expected_updated_at', true);
  if coalesce(expected_updated_at, '') <> ''
     and old.updated_at is distinct from expected_updated_at::timestamptz then
    raise exception using errcode = 'P0001', message = 'dice_game.stale_update';
  end if;
  return new;
end;
$$;

drop trigger if exists dice_game_reject_stale_update on public.dice_games;
create trigger dice_game_reject_stale_update
before update on public.dice_games
for each row execute function public.dice_game_reject_stale_update();

create or replace function public.dice_rating_apply_game_mutation_if_current(
  p_mutation_id uuid,
  p_source jsonb,
  p_operation text,
  p_game jsonb,
  p_players jsonb,
  p_expected_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb,
  p_source_digest text,
  p_output_digest text,
  p_actor_id text,
  p_request_fingerprint text,
  p_expected_updated_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  if coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', ''
  ) <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  if p_operation is distinct from 'update' or p_expected_updated_at is null then
    raise exception using errcode = '22023', message = 'dice_game.invalid_update_revision';
  end if;

  perform pg_catalog.set_config(
    'dice.game_expected_updated_at', p_expected_updated_at::text, true
  );
  return public.dice_rating_apply_game_mutation(
    p_mutation_id, p_source, p_operation, p_game, p_players,
    p_expected_source, p_player_snapshots, p_profile_states,
    p_source_digest, p_output_digest, p_actor_id, p_request_fingerprint
  );
end;
$$;

revoke all on function public.dice_game_reject_stale_update()
  from public, anon, authenticated, service_role;
revoke all on function public.dice_rating_apply_game_mutation_if_current(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb,
  text, text, text, text, timestamptz
) from public, anon, authenticated;
grant execute on function public.dice_rating_apply_game_mutation_if_current(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb,
  text, text, text, text, timestamptz
) to service_role;
