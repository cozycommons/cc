-- Beli on the shared Cozy Commons connector (/mcp).
-- A Commons user links one Beli account by presenting its existing ccb_ token
-- once; the connector then resolves the account from the signed-in user. The
-- token itself is never stored here (beli_accounts keeps only its sha256 hash).
-- Existing rows stay unlinked and the legacy token flow is unchanged.

alter table public.beli_accounts
  add column owner_user_id uuid references auth.users(id) on delete set null;
create unique index beli_accounts_owner_user_id_key
  on public.beli_accounts (owner_user_id) where owner_user_id is not null;

-- Durable receipts for connector writes: a retry with the same key returns the
-- original result. A row without a result is a reservation for a write in flight.
create table public.beli_agent_receipts (
  user_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 1 and 200),
  payload jsonb not null,
  result jsonb,
  created_at timestamptz not null default now(),
  primary key (user_id, idempotency_key)
);
alter table public.beli_agent_receipts enable row level security;
revoke all on public.beli_agent_receipts from public, anon, authenticated;
grant select, insert, update, delete on public.beli_agent_receipts to service_role;

-- Link atomically: refuse an account owned by someone else, and move the
-- caller's existing link (at most one per user) to the new account.
create function public.beli_link_account(p_account_id uuid, p_user_id uuid)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  current_owner uuid;
begin
  select owner_user_id into current_owner from public.beli_accounts
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
  update public.beli_accounts set owner_user_id = null where owner_user_id = p_user_id;
  update public.beli_accounts set owner_user_id = p_user_id where id = p_account_id;
  return 'linked';
end;
$$;
revoke all on function public.beli_link_account(uuid, uuid) from public, anon, authenticated;
grant execute on function public.beli_link_account(uuid, uuid) to service_role;
