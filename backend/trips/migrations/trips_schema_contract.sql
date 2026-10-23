do $$
begin
  if not exists (select 1 from pg_class where oid = to_regclass('public.trips_groups') and relrowsecurity) then
    raise exception 'Trips schema contract: trips_groups is missing or RLS is disabled';
  end if;
  if has_table_privilege('anon', 'public.trips_groups', 'SELECT')
     or has_table_privilege('authenticated', 'public.trips_groups', 'UPDATE') then
    raise exception 'Trips schema contract: unsafe ledger grants';
  end if;
end $$;
