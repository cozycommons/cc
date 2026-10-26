do $$ begin
 if to_regclass('public.venmo_profiles') is null then
 raise exception 'Venmo profile cache missing';
 end if;
 if to_regclass('public.venmo_photos') is null then
 raise exception 'Venmo photo cache missing';
 end if;
end $$;
