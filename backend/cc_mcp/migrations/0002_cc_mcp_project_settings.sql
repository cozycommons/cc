-- Per-user project enablement for the shared connector. A missing row means
-- "use the project's default"; linked project accounts live in project tables.
create table public.cc_mcp_project_settings (
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null check (project_id ~ '^[a-z][a-z0-9-]{0,63}$'),
  enabled boolean not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, project_id)
);

alter table public.cc_mcp_project_settings enable row level security;
revoke all on public.cc_mcp_project_settings from public, anon, authenticated;
grant select, insert, update, delete on public.cc_mcp_project_settings to service_role;

create function public.cc_mcp_project_settings_readiness() returns boolean
language plpgsql stable set search_path = '' as $$
declare
  role_name text;
begin
  if not exists (select 1 from public.cc_mcp_schema_migrations where version = 2) then
    raise exception 'Cozy Commons MCP: project settings migration receipt missing';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_class
    where oid = pg_catalog.to_regclass('public.cc_mcp_project_settings') and relrowsecurity
  ) then
    raise exception 'Cozy Commons MCP: project settings table missing or RLS is disabled';
  end if;
  foreach role_name in array array['anon', 'authenticated'] loop
    if pg_catalog.has_any_column_privilege(role_name, 'public.cc_mcp_project_settings', 'SELECT')
       or pg_catalog.has_table_privilege(role_name, 'public.cc_mcp_project_settings', 'INSERT,UPDATE,DELETE,TRUNCATE') then
      raise exception 'Cozy Commons MCP: unsafe browser grants on project settings';
    end if;
  end loop;
  if not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_project_settings', 'SELECT')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_project_settings', 'INSERT')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_project_settings', 'UPDATE')
     or not pg_catalog.has_table_privilege('service_role', 'public.cc_mcp_project_settings', 'DELETE') then
    raise exception 'Cozy Commons MCP: project settings service_role grants changed';
  end if;
  return true;
end;
$$;
revoke all on function public.cc_mcp_project_settings_readiness() from public, anon, authenticated;
grant execute on function public.cc_mcp_project_settings_readiness() to service_role;

-- Preserve the public readiness entry point while extending its attestation.
alter function public.cc_mcp_release_readiness() rename to cc_mcp_oauth_readiness;
create function public.cc_mcp_release_readiness() returns boolean
language plpgsql stable set search_path = '' as $$
begin
  perform public.cc_mcp_oauth_readiness();
  perform public.cc_mcp_project_settings_readiness();
  return true;
end;
$$;
revoke all on function public.cc_mcp_release_readiness() from public, anon, authenticated;
grant execute on function public.cc_mcp_release_readiness() to service_role;
