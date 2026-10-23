-- Attest the actual Trips schema before a release receives traffic.
create function public.trips_release_readiness()
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  column_name text;
  role_name text;
begin
  if not exists (select 1 from public.trips_schema_migrations where version = 2) then
    raise exception 'Trips schema contract: migration receipt missing';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_class
    where oid = pg_catalog.to_regclass('public.trips_groups') and relrowsecurity
  ) then
    raise exception 'Trips schema contract: trips_groups is missing or RLS is disabled';
  end if;
  foreach column_name in array array[
    'id', 'owner_id', 'member_user_ids', 'data', 'revision', 'created_at', 'updated_at'
  ] loop
    if not exists (
      select 1 from pg_catalog.pg_attribute a
      where a.attrelid = 'public.trips_groups'::regclass
        and a.attname = column_name and not a.attisdropped and a.attnotnull
    ) then
      raise exception 'Trips schema contract: missing or nullable column %', column_name;
    end if;
  end loop;
  foreach role_name in array array['anon', 'authenticated'] loop
    if pg_catalog.has_table_privilege(role_name, 'public.trips_groups', 'INSERT')
       or pg_catalog.has_table_privilege(role_name, 'public.trips_groups', 'UPDATE')
       or pg_catalog.has_table_privilege(role_name, 'public.trips_groups', 'DELETE')
       or pg_catalog.has_table_privilege(role_name, 'public.trips_groups', 'TRUNCATE') then
      raise exception 'Trips schema contract: unsafe ledger grants';
    end if;
  end loop;
  if pg_catalog.has_table_privilege('anon', 'public.trips_groups', 'SELECT')
     or not pg_catalog.has_table_privilege('authenticated', 'public.trips_groups', 'SELECT')
     or not pg_catalog.has_table_privilege('service_role', 'public.trips_groups', 'SELECT,INSERT,UPDATE,DELETE') then
    raise exception 'Trips schema contract: required ledger grants changed';
  end if;
  if (select count(*) from pg_catalog.pg_policy where polrelid = 'public.trips_groups'::regclass) <> 1
     or not exists (
       select 1 from pg_catalog.pg_policy
       where polrelid = 'public.trips_groups'::regclass and polname = 'trips_member_read'
         and polcmd = 'r' and polpermissive
         and polroles = array['authenticated'::regrole::oid]
         and pg_catalog.pg_get_expr(polqual, polrelid) =
           '(member_user_ids @> ARRAY[( SELECT auth.uid() AS uid)])'
     ) then
    raise exception 'Trips schema contract: member read policy changed';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_index
    where indexrelid = pg_catalog.to_regclass('public.trips_groups_members')
      and indisvalid and indisready
  ) then
    raise exception 'Trips schema contract: membership index missing';
  end if;
  return true;
end;
$$;
revoke all on function public.trips_release_readiness() from public, anon, authenticated;
grant execute on function public.trips_release_readiness() to service_role;
