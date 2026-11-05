-- ESPN proven claims commit in one transaction (follows 0091).
-- 0091 linked the row in espn_claim_account_proven and wrote the new cookies,
-- the replacement token and the automation choice in a second statement from
-- the API. If that second write failed, the claim was proven while the previous
-- holder's cce_ token still worked, and a retry saw already_linked and kept the
-- previous owner's automation choice. The claim now takes the encrypted cookies,
-- the replacement token hash and prefix and the automation choice, and commits
-- them with the ownership change and the proposal expiry or not at all.
--
-- Also:
-- - A takeover expires the row's lineup previews (espn_lineup_runs with status
--   'dry_run') as well as its pending roster edits and trade offers.
-- - A row a function unlinks from a user (their previous link) drops to
--   unproven with them.
-- - A proven claim also detaches other rows for the same SWID, league and
--   season that someone holds without proof (p_duplicate_ids, matched by the API
--   because the SWID is encrypted): racing claimants could otherwise create a
--   duplicate the squatter keeps. Detached rows are unowned and unproven, get a
--   token nobody holds, lose lineup automation and have their proposals expired.

create or replace function public.espn_link_account(p_account_id uuid, p_user_id uuid)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  current_owner uuid;
begin
  select owner_user_id into current_owner from public.espn_accounts
    where id = p_account_id for update;
  if not found then
    return 'missing';
  end if;
  if current_owner = p_user_id then
    return 'already_linked';
  end if;
  if current_owner is not null then
    return 'other_owner';
  end if;
  update public.espn_accounts set owner_user_id = null, owner_proven = false
    where owner_user_id = p_user_id;
  update public.espn_accounts set owner_user_id = p_user_id, owner_proven = false
    where id = p_account_id;
  return 'linked';
end;
$$;
revoke all on function public.espn_link_account(uuid, uuid) from public, anon, authenticated;
grant execute on function public.espn_link_account(uuid, uuid) to service_role;

drop function public.espn_claim_account_proven(uuid, uuid);

-- A MyDisney-proven claim. Returns linked | taken_over | already_linked |
-- other_owner | missing.
-- - linked / taken_over: the row becomes the caller's, proven, with the new
--   cookies and token (taken_over also sets the automation choice, which was the
--   previous owner's), and its proposals expire.
-- - already_linked: the caller's own row is marked proven; the new cookies and
--   token are written only when p_refresh_own (the cookies changed).
-- Nothing is written for other_owner or missing.
create function public.espn_claim_account_proven(
  p_account_id uuid, p_user_id uuid, p_espn_s2_enc text, p_token_hash text, p_token_prefix text,
  p_automation boolean, p_refresh_own boolean, p_duplicate_ids uuid[]
)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  current_owner uuid;
  current_proven boolean;
  detached uuid[];
  expiring uuid[];
begin
  if p_espn_s2_enc is null or p_token_hash is null or p_token_prefix is null or p_automation is null
      or p_refresh_own is null then
    raise exception 'espn_claim_account_proven: cookies, token and automation are required';
  end if;
  select owner_user_id, owner_proven into current_owner, current_proven
    from public.espn_accounts where id = p_account_id for update;
  if not found then
    return 'missing';
  end if;
  if current_owner is not null and current_owner <> p_user_id and current_proven then
    return 'other_owner';
  end if;

  select coalesce(pg_catalog.array_agg(held.id), '{}') into detached from (
    select id from public.espn_accounts
      where id = any(coalesce(p_duplicate_ids, '{}')) and id <> p_account_id
        and owner_user_id is not null and owner_user_id <> p_user_id and not owner_proven
      for update
  ) held;
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
