-- Partiful on the shared Cozy Commons connector (/mcp).
-- A Commons user links one Partiful account by presenting its existing ccp_
-- token once; the connector then resolves the account from the signed-in user.
-- The token itself is never stored here (partiful_accounts keeps only its
-- sha256 hash). Linking changes only owner_user_id, never the stored Partiful
-- refresh token. Existing rows stay unlinked and the legacy token flow is
-- unchanged. The connector's Partiful tools are read-only, so there is no
-- receipts table.

alter table public.partiful_accounts
  add column owner_user_id uuid references auth.users(id) on delete set null;
create unique index partiful_accounts_owner_user_id_key
  on public.partiful_accounts (owner_user_id) where owner_user_id is not null;

-- Link atomically: refuse an account owned by someone else, and move the
-- caller's existing link (at most one per user) to the new account.
create function public.partiful_link_account(p_account_id uuid, p_user_id uuid)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  current_owner uuid;
begin
  select owner_user_id into current_owner from public.partiful_accounts
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
  update public.partiful_accounts set owner_user_id = null where owner_user_id = p_user_id;
  update public.partiful_accounts set owner_user_id = p_user_id where id = p_account_id;
  return 'linked';
end;
$$;
revoke all on function public.partiful_link_account(uuid, uuid) from public, anon, authenticated;
grant execute on function public.partiful_link_account(uuid, uuid) to service_role;
