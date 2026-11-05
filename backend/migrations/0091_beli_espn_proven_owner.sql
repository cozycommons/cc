-- ESPN claims from the account page: a proven claim beats an unproven one.
-- Only a MyDisney login proves that the caller owns an account's SWID. Typed
-- espn_s2/SWID cookies and a legacy cce_ token prove only that the caller can
-- read the league, and the league's mTeam view lists every member's SWID, so a
-- league-mate could otherwise claim a row for someone else's team first.
-- owner_proven records which kind of claim the current owner made. A proven
-- claim takes over a row whose owner is unproven; nothing takes over a proven
-- owner. Existing links were all made with a cce_ token, so they start
-- unproven.

alter table public.espn_accounts
  add column owner_proven boolean not null default false;

-- Unproven links (cookies, a cce_ token) never mark a claim proven, and a row
-- that changes owner this way starts unproven.
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
  update public.espn_accounts set owner_user_id = null where owner_user_id = p_user_id;
  update public.espn_accounts set owner_user_id = p_user_id, owner_proven = false
    where id = p_account_id;
  return 'linked';
end;
$$;
revoke all on function public.espn_link_account(uuid, uuid) from public, anon, authenticated;
grant execute on function public.espn_link_account(uuid, uuid) to service_role;

-- A MyDisney-proven claim: link an unowned row, take over a row whose owner is
-- unproven, or mark the caller's own row proven. Returns linked | taken_over |
-- already_linked | other_owner | missing. When the owner changes, roster edits
-- and trade offers left pending on the row are expired, so the new owner can
-- never approve a proposal someone else made.
create function public.espn_claim_account_proven(p_account_id uuid, p_user_id uuid)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  current_owner uuid;
  current_proven boolean;
begin
  select owner_user_id, owner_proven into current_owner, current_proven
    from public.espn_accounts where id = p_account_id for update;
  if not found then
    return 'missing';
  end if;
  if current_owner = p_user_id then
    update public.espn_accounts set owner_proven = true where id = p_account_id;
    return 'already_linked';
  end if;
  if current_owner is not null and current_proven then
    return 'other_owner';
  end if;
  update public.espn_roster_edits set status = 'expired'
    where account_id = p_account_id and status = 'pending';
  update public.espn_trade_proposals set status = 'expired'
    where account_id = p_account_id and status = 'pending';
  update public.espn_accounts set owner_user_id = null where owner_user_id = p_user_id;
  update public.espn_accounts set owner_user_id = p_user_id, owner_proven = true
    where id = p_account_id;
  return case when current_owner is null then 'linked' else 'taken_over' end;
end;
$$;
revoke all on function public.espn_claim_account_proven(uuid, uuid) from public, anon, authenticated;
grant execute on function public.espn_claim_account_proven(uuid, uuid) to service_role;
