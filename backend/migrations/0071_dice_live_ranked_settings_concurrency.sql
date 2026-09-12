-- Serialize pre-finish settings with live materialization. Once an official
-- game exists, the canonical rating mutation owns the ranked update.
create or replace function public.dice_live_set_ranked(
  p_match_id uuid,
  p_ranked boolean
)
returns jsonb
language plpgsql
security definer
set search_path = ''
set lock_timeout = '2s'
as $$
declare
  v_result_id uuid;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:elo:canonical', 0)
  );
  select official_result_id into v_result_id
  from public.dice_live_matches
  where id = p_match_id and deleted_at is null
  for update;
  if not found then
    return jsonb_build_object('status', 'missing');
  end if;
  if v_result_id is not null then
    return jsonb_build_object('status', 'official');
  end if;
  update public.dice_live_matches
  set ranked = p_ranked
  where id = p_match_id;
  return jsonb_build_object('status', 'updated');
end;
$$;

revoke all on function public.dice_live_set_ranked(uuid, boolean)
  from public, anon, authenticated;
grant execute on function public.dice_live_set_ranked(uuid, boolean)
  to service_role;

-- Completed settings use the canonical mutation, but with a settings-specific
-- timeout so lock contention becomes a retryable API conflict instead of a
-- one-minute upstream timeout. The wrapper preserves the canonical function's
-- validation and transaction boundary.
create or replace function public.dice_live_apply_ranked_rating_mutation(
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
  p_request_fingerprint text
)
returns jsonb
language sql
security definer
set search_path = ''
set lock_timeout = '2s'
as $$
  select public.dice_rating_apply_game_mutation(
    p_mutation_id, p_source, p_operation, p_game, p_players,
    p_expected_source, p_player_snapshots, p_profile_states,
    p_source_digest, p_output_digest, p_actor_id, p_request_fingerprint
  );
$$;

revoke all on function public.dice_live_apply_ranked_rating_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.dice_live_apply_ranked_rating_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) to service_role;

create or replace function public.dice_live_sync_ranked_from_result()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.source_live_match_id is not null then
    update public.dice_live_matches
    set ranked = new.ranked
    where id = new.source_live_match_id;
  end if;
  return new;
end;
$$;

drop trigger if exists dice_live_sync_ranked_from_result on public.dice_games;
create trigger dice_live_sync_ranked_from_result
after update of ranked on public.dice_games
for each row execute function public.dice_live_sync_ranked_from_result();

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('dice:elo:canonical', 0)
);
update public.dice_live_matches live
set ranked = game.ranked
from public.dice_games game
where game.source_live_match_id = live.id
  and live.ranked is distinct from game.ranked;

revoke all on function public.dice_live_sync_ranked_from_result()
  from public, anon, authenticated, service_role;

comment on function public.dice_live_sync_ranked_from_result()
  is 'Keeps a materialized live result and its source match ranked flag atomic.';
