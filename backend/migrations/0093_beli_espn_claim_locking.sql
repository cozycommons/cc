-- ESPN proven claims, hardened (follows 0091 and 0092, which stay as applied).
-- - The claim locks the target and the duplicate rows in one statement, in id
--   order, before branching: two claims over overlapping rows could otherwise
--   lock them in opposite orders and deadlock (40P01).
-- - A duplicate is detached only if it is for the same league and season as the
--   target, whatever ids the caller passes.
-- - A NULL user and empty cookies, token hash or prefix are refused.
-- - A takeover expires lineup previews by updating espn_lineup_runs.status. That
--   privilege came only from Supabase's default grants; it is now explicit, and
--   the schema contract fails readiness if it is ever revoked.

grant update (status) on public.espn_lineup_runs to service_role;

-- A MyDisney-proven claim. Returns linked | taken_over | already_linked |
-- other_owner | missing.
-- - linked / taken_over: the row becomes the caller's, proven, with the new
--   cookies and token (taken_over also sets the automation choice, which was the
--   previous owner's), and its proposals expire.
-- - already_linked: the caller's own row is marked proven; the new cookies and
--   token are written only when p_refresh_own (the cookies changed).
-- Nothing is written for other_owner or missing.
create or replace function public.espn_claim_account_proven(
  p_account_id uuid, p_user_id uuid, p_espn_s2_enc text, p_token_hash text, p_token_prefix text,
  p_automation boolean, p_refresh_own boolean, p_duplicate_ids uuid[]
)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  team_league bigint;
  team_season integer;
  current_owner uuid;
  current_proven boolean;
  detached uuid[];
  expiring uuid[];
begin
  if p_user_id is null or p_automation is null or p_refresh_own is null
      or coalesce(p_espn_s2_enc, '') = '' or coalesce(p_token_hash, '') = '' or coalesce(p_token_prefix, '') = '' then
    raise exception 'espn_claim_account_proven: user, cookies, token and automation are required';
  end if;
  select league_id, season into team_league, team_season from public.espn_accounts where id = p_account_id;
  if not found then
    return 'missing';
  end if;
  -- Lock the target and its duplicates in one statement, in id order, before reading any owner:
  -- two claims over overlapping rows then wait on each other instead of deadlocking.
  perform 1 from public.espn_accounts
    where id = p_account_id
       or (id = any(coalesce(p_duplicate_ids, '{}')) and league_id = team_league and season = team_season)
    order by id
    for update;
  select owner_user_id, owner_proven into current_owner, current_proven
    from public.espn_accounts where id = p_account_id;
  if not found then  -- deleted before the lock
    return 'missing';
  end if;
  if current_owner is not null and current_owner <> p_user_id and current_proven then
    return 'other_owner';
  end if;

  -- Only rows for the same league and season can be the same team (the API matched the SWID).
  select coalesce(pg_catalog.array_agg(id), '{}') into detached from public.espn_accounts
    where id = any(coalesce(p_duplicate_ids, '{}')) and id <> p_account_id
      and league_id = team_league and season = team_season
      and owner_user_id is not null and owner_user_id <> p_user_id and not owner_proven;
  update public.espn_accounts
    set owner_user_id = null, owner_proven = false, lineup_automation_enabled = false,
        token_hash = 'retired:' || pg_catalog.gen_random_uuid()::text, token_prefix = 'retired'
    where id = any(detached);

  -- Proposals on rows that change hands are never approvable by their new holder.
  expiring := case when current_owner = p_user_id then detached else detached || p_account_id end;
  update public.espn_roster_edits set status = 'expired'
    where account_id = any(expiring) and status = 'pending';
  update public.espn_trade_proposals set status = 'expired'
    where account_id = any(expiring) and status = 'pending';
  update public.espn_lineup_runs set status = 'expired'
    where account_id = any(expiring) and status = 'dry_run';

  if current_owner = p_user_id then
    if p_refresh_own then
      update public.espn_accounts
        set owner_proven = true, espn_s2_enc = p_espn_s2_enc, token_hash = p_token_hash,
            token_prefix = p_token_prefix
        where id = p_account_id;
    else
      update public.espn_accounts set owner_proven = true where id = p_account_id;
    end if;
    return 'already_linked';
  end if;

  update public.espn_accounts set owner_user_id = null, owner_proven = false
    where owner_user_id = p_user_id;
  update public.espn_accounts
    set owner_user_id = p_user_id, owner_proven = true, espn_s2_enc = p_espn_s2_enc,
        token_hash = p_token_hash, token_prefix = p_token_prefix,
        lineup_automation_enabled = case when current_owner is null then lineup_automation_enabled
                                         else p_automation end
    where id = p_account_id;
  return case when current_owner is null then 'linked' else 'taken_over' end;
end;
$$;
revoke all on function public.espn_claim_account_proven(uuid, uuid, text, text, text, boolean, boolean, uuid[])
  from public, anon, authenticated;
grant execute on function public.espn_claim_account_proven(uuid, uuid, text, text, text, boolean, boolean, uuid[])
  to service_role;
