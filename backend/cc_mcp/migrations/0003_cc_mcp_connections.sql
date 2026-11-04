-- One row per agent connection (one approval and its refresh family), beside
-- the encrypted OAuth store so the account page can list and disconnect a
-- user's agents without decrypting every upstream token. The store remains the
-- authority: a connection works while its upstream token set exists.
create table public.cc_mcp_connections (
  id uuid primary key default gen_random_uuid(),
  upstream_token_id text not null unique check (length(upstream_token_id) between 1 and 256),
  user_id uuid not null references auth.users(id) on delete cascade,
  client_id text not null check (length(client_id) between 1 and 256),
  -- Self-reported at dynamic client registration: display only, never verified.
  client_name text check (client_name is null or length(client_name) between 1 and 80),
  redirect_host text check (redirect_host is null or length(redirect_host) between 1 and 255),
  scopes text[] not null,
  approved_at timestamptz not null,
  last_used_at timestamptz,
  expires_at timestamptz,
  revoked_at timestamptz
);

create index cc_mcp_connections_active_user
  on public.cc_mcp_connections(user_id)
  where revoked_at is null;

alter table public.cc_mcp_connections enable row level security;
revoke all on public.cc_mcp_connections from public, anon, authenticated;
grant select, insert, update, delete on public.cc_mcp_connections to service_role;

-- Index a connection on approval, refresh or use. Later calls only move
-- last_used_at forward and refresh expires_at; approved_at, the client details
-- and revoked_at are never overwritten.
create function public.cc_mcp_touch_connection(
  p_upstream_token_id text,
  p_user_id uuid,
  p_client_id text,
  p_client_name text,
  p_redirect_host text,
  p_scopes text[],
  p_approved_at timestamptz,
  p_expires_at timestamptz,
  p_last_used_at timestamptz
) returns void
language sql security invoker set search_path = '' as $$
  insert into public.cc_mcp_connections as c (
    upstream_token_id, user_id, client_id, client_name, redirect_host,
    scopes, approved_at, expires_at, last_used_at
  ) values (
    p_upstream_token_id, p_user_id, p_client_id, p_client_name, p_redirect_host,
    p_scopes, p_approved_at, p_expires_at, p_last_used_at
  )
  on conflict (upstream_token_id) do update set
    last_used_at = greatest(c.last_used_at, excluded.last_used_at),
    expires_at = coalesce(excluded.expires_at, c.expires_at)
  where c.user_id = excluded.user_id;
$$;
revoke all on function public.cc_mcp_touch_connection(text, uuid, text, text, text, text[], timestamptz, timestamptz, timestamptz)
  from public, anon, authenticated;
grant execute on function public.cc_mcp_touch_connection(text, uuid, text, text, text, text[], timestamptz, timestamptz, timestamptz)
  to service_role;

create function public.cc_mcp_connections_readiness() returns boolean
language plpgsql stable set search_path = '' as $$
declare
  role_name text;
  touch constant text := 'public.cc_mcp_touch_connection(text, uuid, text, text, text, text[], timestamptz, timestamptz, timestamptz)';
begin
  if not exists (select 1 from public.cc_mcp_schema_migrations where version = 3) then
    raise exception 'Cozy Commons MCP: connections migration receipt missing';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_class
    where oid = pg_catalog.to_regclass('public.cc_mcp_connections') and relrowsecurity
  ) then
    raise exception 'Cozy Commons MCP: connections table missing or RLS is disabled';
  end if;
  if pg_catalog.to_regprocedure(touch) is null then
    raise exception 'Cozy Commons MCP: connection touch function missing';
  end if;
  foreach role_name in array array['anon', 'authenticated'] loop
    if pg_catalog.has_any_column_privilege(role_name, 'public.cc_mcp_connections', 'SELECT')
       or pg_catalog.has_table_privilege(role_name, 'public.cc_mcp_connections', 'INSERT,UPDATE,DELETE,TRUNCATE')
       or pg_catalog.has_function_privilege(role_name, touch, 'EXECUTE') then
      raise exception 'Cozy Commons MCP: unsafe browser grants on connections';
    end if;
  end loop;
  if not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_connections', 'SELECT')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_connections', 'INSERT')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_connections', 'UPDATE')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_connections', 'DELETE')
     or not pg_catalog.has_function_privilege('service_role', touch, 'EXECUTE') then
    raise exception 'Cozy Commons MCP: connections service_role grants changed';
  end if;
  return true;
end;
$$;
revoke all on function public.cc_mcp_connections_readiness() from public, anon, authenticated;
grant execute on function public.cc_mcp_connections_readiness() to service_role;

-- Preserve the public readiness entry point while extending its attestation.
create or replace function public.cc_mcp_release_readiness() returns boolean
language plpgsql stable set search_path = '' as $$
begin
  perform public.cc_mcp_oauth_readiness();
  perform public.cc_mcp_project_settings_readiness();
  perform public.cc_mcp_connections_readiness();
  return true;
end;
$$;
revoke all on function public.cc_mcp_release_readiness() from public, anon, authenticated;
grant execute on function public.cc_mcp_release_readiness() to service_role;
