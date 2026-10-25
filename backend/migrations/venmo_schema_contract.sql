do $$ begin
 if to_regclass('public.venmo_profiles') is null then
 raise exception 'Venmo profile cache missing';
 end if;
end $$;
