-- ESPN on the shared Cozy Commons connector (/mcp).
-- A Commons user links one ESPN account by presenting its existing cce_ token
-- once; the connector then resolves the account from the signed-in user. The
-- token itself is never stored here (espn_accounts keeps only its sha256 hash).
-- Linking changes only owner_user_id: the cookies, lineup automation opt-in and
-- espn_team_claims are untouched. Existing rows stay unlinked and the legacy
-- token flow is unchanged.

alter table public.espn_accounts
  add column owner_user_id uuid references auth.users(id) on delete set null;
create unique index espn_accounts_owner_user_id_key
  on public.espn_accounts (owner_user_id) where owner_user_id is not null;

-- Durable receipts for connector approvals (roster edits, trades, lineups). A
-- row is written just before the approval that may reach ESPN and is never
-- deleted by the connector: a row without a result means ESPN's answer was not
-- recorded, and only a read of ESPN settles it.
create table public.espn_agent_receipts (
  user_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 1 and 200),
  payload jsonb not null,
  target jsonb not null,
  result jsonb,
  created_at timestamptz not null default now(),
  primary key (user_id, idempotency_key)
);
alter table public.espn_agent_receipts enable row level security;
-- Revoke service_role too: Supabase default privileges would otherwise grant it DELETE.
revoke all on public.espn_agent_receipts from public, anon, authenticated, service_role;
grant select, insert, update on public.espn_agent_receipts to service_role;

-- Link atomically: refuse an account owned by someone else, and move the
-- caller's existing link (at most one per user) to the new account.
create function public.espn_link_account(p_account_id uuid, p_user_id uuid)
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
  update public.espn_accounts set owner_user_id = p_user_id where id = p_account_id;
  return 'linked';
end;
$$;
revoke all on function public.espn_link_account(uuid, uuid) from public, anon, authenticated;
grant execute on function public.espn_link_account(uuid, uuid) to service_role;
