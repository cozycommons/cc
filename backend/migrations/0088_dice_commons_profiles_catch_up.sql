-- Catch up commons_profiles before the API starts writing it (M4 PR 2).
-- Between 0087 and this release the old code still wrote names and avatars to
-- dice_profiles and Venmo handles to Auth metadata, and new accounts got no
-- row. Re-running the 0087 backfill as an upsert keeps those edits. Nothing
-- wrote commons_profiles in that window, so no newer value is overwritten.
-- The mirror is paused so dice_profiles is left exactly as it is.
--
-- Migrations run before the new API starts (release.py), so old workers keep
-- accepting edits after this commits. A temporary reverse sync copies them
-- into commons_profiles. A later migration removes it once the deploy has
-- settled (docs/handoff/commons-account.md).
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

-- Venmo from Auth metadata, as in the 0087 backfill. venmo.usernames.stored_username:
-- strip a venmo.com URL, query, slashes and @; trips.venmo.account_venmo for provenance.
CREATE FUNCTION public.commons_profiles_auth_venmo(metadata jsonb,
 OUT venmo_username text, OUT venmo_owner_confirmed boolean, OUT venmo_confirmed_name text)
 LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
SELECT lower(v.username),
 coalesce(v.username IS NOT NULL
  AND jsonb_typeof(v.provenance) = 'object'
  AND v.provenance->'owner_confirmed' = 'true'::jsonb
  AND (coalesce(v.provenance->'handle', 'null'::jsonb) IN ('null', '""', 'false', '0', '[]', '{}')
   OR v.provenance->'handle' = to_jsonb(lower(v.username))), false),
 CASE WHEN jsonb_typeof(v.provenance) = 'object' AND jsonb_typeof(v.provenance->'display_name') = 'string'
  THEN nullif(v.provenance->>'display_name', '') END
FROM (SELECT CASE WHEN jsonb_typeof(metadata->'venmo_username') = 'string'
 THEN btrim(regexp_replace(btrim(split_part(regexp_replace(
  btrim(metadata->>'venmo_username', E' \t\r\n'),
  '^(https?://)?(www\.|account\.)?venmo\.com/(u/)?', '', 'i'), '?', 1), '/'), '^@', ''), E' \t\r\n')
 END AS candidate) n
CROSS JOIN LATERAL (SELECT CASE WHEN n.candidate ~ '^[A-Za-z0-9_-]{5,30}$' THEN n.candidate END AS username,
 metadata->'venmo_username_provenance' AS provenance) v
$$;

-- Recursion guard: each direction sets commons.profile_sync for its own write
-- and skips while the other direction holds it, so a synced edit never echoes.
CREATE OR REPLACE FUNCTION public.commons_profiles_mirror_dice() RETURNS trigger
 LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
 IF current_setting('commons.profile_sync', true) = 'on' THEN
  RETURN NULL;
 END IF;
 PERFORM set_config('commons.profile_sync', 'on', true);
 UPDATE public.dice_profiles d SET
  display_name = CASE WHEN OLD.display_name IS DISTINCT FROM NEW.display_name THEN NEW.display_name ELSE d.display_name END,
  avatar_url = CASE WHEN OLD.avatar_url IS DISTINCT FROM NEW.avatar_url THEN NEW.avatar_url ELSE d.avatar_url END,
  updated_at = now()
 WHERE d.user_id = NEW.user_id;
 PERFORM set_config('commons.profile_sync', '', true);
 RETURN NULL;
END $$;

-- Old workers' Dice name or avatar edit. Values the Commons checks would
-- reject (a blank name, an avatar over 2048 characters) are skipped rather
-- than failing the old worker's write. Without a Commons row this is a no-op;
-- own_profile later builds the row from the Dice row. SECURITY DEFINER keeps
-- the trigger independent of the writer's grants.
CREATE FUNCTION public.commons_profiles_sync_from_dice() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE name text := btrim(left(btrim(NEW.display_name), 80));
BEGIN
 IF current_setting('commons.profile_sync', true) = 'on' THEN
  RETURN NULL;
 END IF;
 PERFORM set_config('commons.profile_sync', 'on', true);
 UPDATE public.commons_profiles c SET
  display_name = CASE WHEN OLD.display_name IS DISTINCT FROM NEW.display_name AND name <> ''
   THEN name ELSE c.display_name END,
  avatar_url = CASE WHEN OLD.avatar_url IS DISTINCT FROM NEW.avatar_url
   AND (NEW.avatar_url IS NULL OR length(NEW.avatar_url) <= 2048) THEN NEW.avatar_url ELSE c.avatar_url END,
  updated_at = now()
 WHERE c.user_id = NEW.user_id;
 PERFORM set_config('commons.profile_sync', '', true);
 RETURN NULL;
END $$;

-- Old Trips' Venmo save (Auth admin API). Nothing writes Auth metadata from
-- Commons, so this direction cannot loop. Runs as the Auth service's role,
-- which has no Commons grants, hence SECURITY DEFINER.
CREATE FUNCTION public.commons_profiles_sync_from_auth() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
 UPDATE public.commons_profiles c SET
  venmo_username = v.venmo_username,
  venmo_owner_confirmed = v.venmo_owner_confirmed,
  venmo_confirmed_name = v.venmo_confirmed_name,
  updated_at = now()
 FROM public.commons_profiles_auth_venmo(NEW.raw_user_meta_data) v
 WHERE c.user_id = NEW.id;
 RETURN NULL;
END $$;

REVOKE ALL ON FUNCTION public.commons_profiles_auth_venmo(jsonb), public.commons_profiles_sync_from_dice(),
 public.commons_profiles_sync_from_auth() FROM PUBLIC, anon, authenticated, service_role;

-- Created before the catch-up: each CREATE TRIGGER holds a lock that blocks
-- writes to its table until this migration commits. An edit committed before
-- that is read by the catch-up; one after it fires the trigger.
CREATE TRIGGER commons_profiles_sync_from_dice
 AFTER UPDATE OF display_name, avatar_url ON public.dice_profiles
 FOR EACH ROW
 WHEN (OLD.display_name IS DISTINCT FROM NEW.display_name OR OLD.avatar_url IS DISTINCT FROM NEW.avatar_url)
 EXECUTE FUNCTION public.commons_profiles_sync_from_dice();
CREATE TRIGGER commons_profiles_sync_from_auth
 AFTER UPDATE OF raw_user_meta_data ON auth.users
 FOR EACH ROW
 WHEN (OLD.raw_user_meta_data->'venmo_username' IS DISTINCT FROM NEW.raw_user_meta_data->'venmo_username'
  OR OLD.raw_user_meta_data->'venmo_username_provenance' IS DISTINCT FROM NEW.raw_user_meta_data->'venmo_username_provenance')
 EXECUTE FUNCTION public.commons_profiles_sync_from_auth();

ALTER TABLE public.commons_profiles DISABLE TRIGGER commons_profiles_mirror_dice;

INSERT INTO public.commons_profiles(user_id, display_name, avatar_url,
 venmo_username, venmo_owner_confirmed, venmo_confirmed_name)
SELECT u.id,
 btrim(left(coalesce(
  nullif(btrim(d.display_name), ''),
  nullif(btrim(u.raw_user_meta_data->>'full_name'), ''),
  nullif(btrim(u.raw_user_meta_data->>'name'), ''),
  nullif(btrim(split_part(u.email, '@', 1)), ''),
  'Friend'), 80)),
 coalesce(
  CASE WHEN length(d.avatar_url) <= 2048 THEN d.avatar_url END,
  CASE WHEN jsonb_typeof(u.raw_user_meta_data->'avatar_url') = 'string'
   AND length(u.raw_user_meta_data->>'avatar_url') <= 2048 THEN u.raw_user_meta_data->>'avatar_url' END),
 v.venmo_username, v.venmo_owner_confirmed, v.venmo_confirmed_name
FROM auth.users u
LEFT JOIN public.dice_profiles d ON d.user_id = u.id
CROSS JOIN LATERAL public.commons_profiles_auth_venmo(u.raw_user_meta_data) v
WHERE u.is_anonymous IS NOT TRUE
ON CONFLICT (user_id) DO UPDATE SET
 display_name = excluded.display_name,
 avatar_url = excluded.avatar_url,
 venmo_username = excluded.venmo_username,
 venmo_owner_confirmed = excluded.venmo_owner_confirmed,
 venmo_confirmed_name = excluded.venmo_confirmed_name,
 updated_at = now()
WHERE (commons_profiles.display_name, commons_profiles.avatar_url, commons_profiles.venmo_username,
  commons_profiles.venmo_owner_confirmed, commons_profiles.venmo_confirmed_name)
 IS DISTINCT FROM (excluded.display_name, excluded.avatar_url, excluded.venmo_username,
  excluded.venmo_owner_confirmed, excluded.venmo_confirmed_name);

ALTER TABLE public.commons_profiles ENABLE TRIGGER commons_profiles_mirror_dice;

-- Extend the Commons attestation with the reverse sync and its guard. The
-- removal migration restores commons_profiles_readiness to the 0087 checks.
ALTER FUNCTION public.commons_profiles_readiness() RENAME TO commons_profiles_0087_readiness;
CREATE FUNCTION public.commons_profiles_readiness() RETURNS boolean
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE role_name text;
BEGIN
 PERFORM public.commons_profiles_0087_readiness();
 IF NOT EXISTS (SELECT FROM public.dice_schema_migrations WHERE version = 88) THEN
  RAISE EXCEPTION 'Commons profiles: migration receipt missing';
 END IF;
 IF NOT EXISTS (SELECT FROM pg_catalog.pg_trigger
  WHERE tgrelid = 'public.dice_profiles'::regclass AND tgname = 'commons_profiles_sync_from_dice'
  AND tgenabled = 'O' AND NOT tgisinternal
  AND tgfoid = 'public.commons_profiles_sync_from_dice()'::regprocedure)
  -- A catalog join, not 'auth.users'::regclass, which needs USAGE on schema auth.
  OR NOT EXISTS (SELECT FROM pg_catalog.pg_trigger t
  JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'auth'
  WHERE c.relname = 'users' AND tgname = 'commons_profiles_sync_from_auth'
  AND tgenabled = 'O' AND NOT tgisinternal
  AND tgfoid = 'public.commons_profiles_sync_from_auth()'::regprocedure) THEN
  RAISE EXCEPTION 'Commons profiles: reverse sync trigger missing or disabled';
 END IF;
 IF EXISTS (SELECT FROM pg_catalog.pg_proc
  WHERE oid IN ('public.commons_profiles_mirror_dice()'::regprocedure,
   'public.commons_profiles_sync_from_dice()'::regprocedure)
  AND position('commons.profile_sync' IN prosrc) = 0) THEN
  RAISE EXCEPTION 'Commons profiles: sync recursion guard missing';
 END IF;
 FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
  IF pg_catalog.has_function_privilege(role_name, 'public.commons_profiles_auth_venmo(jsonb)', 'EXECUTE')
   OR pg_catalog.has_function_privilege(role_name, 'public.commons_profiles_sync_from_dice()', 'EXECUTE')
   OR pg_catalog.has_function_privilege(role_name, 'public.commons_profiles_sync_from_auth()', 'EXECUTE') THEN
   RAISE EXCEPTION 'Commons profiles: unsafe sync function grants';
  END IF;
 END LOOP;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.commons_profiles_readiness() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commons_profiles_readiness() TO service_role;
