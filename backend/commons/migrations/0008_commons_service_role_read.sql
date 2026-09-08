-- The API reads the canonical scene directly before applying commands. Keep
-- that read limited to the service role; browser roles remain denied.
grant select on table public.commons_scenes to service_role;
