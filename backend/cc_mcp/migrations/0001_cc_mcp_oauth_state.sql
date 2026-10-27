create table public.cc_mcp_oauth_state (
  collection text not null check (length(collection) between 1 and 128),
  key text not null check (length(key) between 1 and 2048),
  value jsonb not null check (jsonb_typeof(value) = 'object'),
  expires_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (collection, key)
);

create index cc_mcp_oauth_state_expiry
  on public.cc_mcp_oauth_state(expires_at)
  where expires_at is not null;

alter table public.cc_mcp_oauth_state enable row level security;
revoke all on public.cc_mcp_oauth_state from public, anon, authenticated;
grant select, insert, update, delete on public.cc_mcp_oauth_state to service_role;

create function public.cc_mcp_release_readiness() returns boolean
language plpgsql stable set search_path = '' as $$
declare
  role_name text;
begin
  if not exists (select 1 from public.cc_mcp_schema_migrations where version = 1) then
    raise exception 'Cozy Commons MCP: migration receipt missing';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_class
    where oid = pg_catalog.to_regclass('public.cc_mcp_oauth_state') and relrowsecurity
  ) then
    raise exception 'Cozy Commons MCP: state table missing or RLS is disabled';
  end if;
  foreach role_name in array array['anon', 'authenticated'] loop
    if pg_catalog.has_any_column_privilege(role_name, 'public.cc_mcp_oauth_state', 'SELECT')
       or pg_catalog.has_table_privilege(role_name, 'public.cc_mcp_oauth_state', 'INSERT,UPDATE,DELETE,TRUNCATE') then
      raise exception 'Cozy Commons MCP: unsafe browser grants';
    end if;
  end loop;
  if not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_oauth_state', 'SELECT')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_oauth_state', 'INSERT')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_oauth_state', 'UPDATE')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_oauth_state', 'DELETE') then
    raise exception 'Cozy Commons MCP: service_role grants changed';
  end if;
  return true;
end;
$$;
revoke all on function public.cc_mcp_release_readiness() from public, anon, authenticated;
grant execute on function public.cc_mcp_release_readiness() to service_role;
