-- Commons profile: cross-project identity shared by every project. Dice keeps
-- its own state in dice_profiles; name and avatar there become a one-way copy
-- of this table (commons_profiles_mirror_dice). See docs/handoff/commons-account.md.
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.commons_profiles (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 80),
 avatar_url text CHECK (avatar_url IS NULL OR length(avatar_url) <= 2048),
 -- The canonical form produced by venmo.usernames.normalize_username, lowercased.
 venmo_username text CHECK (venmo_username IS NULL OR venmo_username ~ '^[a-z0-9_-]{5,30}$'),
 venmo_owner_confirmed boolean NOT NULL DEFAULT false,
 venmo_confirmed_name text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.commons_profiles ENABLE ROW LEVEL SECURITY;
-- Every read goes through the API, which applies per-field visibility.
REVOKE ALL ON public.commons_profiles FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.commons_profiles TO service_role;

-- Backfill one row per non-anonymous account. Name precedence matches
-- trips/profiles.py:current_profile (Dice first); Venmo follows
-- trips/venmo.py:account_venmo. Neither auth.users nor dice_profiles changes.
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
 lower(v.username),
 coalesce(v.username IS NOT NULL
  AND jsonb_typeof(v.provenance) = 'object'
  AND v.provenance->'owner_confirmed' = 'true'::jsonb
  AND (coalesce(v.provenance->'handle', 'null'::jsonb) IN ('null', '""', 'false', '0', '[]', '{}')
   OR v.provenance->'handle' = to_jsonb(lower(v.username))), false),
 CASE WHEN jsonb_typeof(v.provenance) = 'object' AND jsonb_typeof(v.provenance->'display_name') = 'string'
  THEN nullif(v.provenance->>'display_name', '') END
FROM auth.users u
LEFT JOIN public.dice_profiles d ON d.user_id = u.id
-- venmo.usernames.stored_username: strip a venmo.com URL, query, slashes and @.
CROSS JOIN LATERAL (SELECT CASE WHEN jsonb_typeof(u.raw_user_meta_data->'venmo_username') = 'string'
 THEN btrim(regexp_replace(btrim(split_part(regexp_replace(
  btrim(u.raw_user_meta_data->>'venmo_username', E' \t\r\n'),
  '^(https?://)?(www\.|account\.)?venmo\.com/(u/)?', '', 'i'), '?', 1), '/'), '^@', ''), E' \t\r\n')
 END AS candidate) n
CROSS JOIN LATERAL (SELECT CASE WHEN n.candidate ~ '^[A-Za-z0-9_-]{5,30}$' THEN n.candidate END AS username,
 u.raw_user_meta_data->'venmo_username_provenance' AS provenance) v
WHERE u.is_anonymous IS NOT TRUE;

-- One-way mirror: a name or avatar change reaches the existing Dice row, so
-- Dice readers, RPCs and SQL snapshots keep reading dice_profiles unchanged.
-- Only the changed column is copied. Without a Dice row this is a no-op.
CREATE FUNCTION public.commons_profiles_mirror_dice() RETURNS trigger
 LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
 UPDATE public.dice_profiles d SET
  display_name = CASE WHEN OLD.display_name IS DISTINCT FROM NEW.display_name THEN NEW.display_name ELSE d.display_name END,
  avatar_url = CASE WHEN OLD.avatar_url IS DISTINCT FROM NEW.avatar_url THEN NEW.avatar_url ELSE d.avatar_url END,
  updated_at = now()
 WHERE d.user_id = NEW.user_id;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.commons_profiles_mirror_dice() FROM PUBLIC, anon, authenticated, service_role;
CREATE TRIGGER commons_profiles_mirror_dice
 AFTER UPDATE OF display_name, avatar_url ON public.commons_profiles
 FOR EACH ROW
 WHEN (OLD.display_name IS DISTINCT FROM NEW.display_name OR OLD.avatar_url IS DISTINCT FROM NEW.avatar_url)
 EXECUTE FUNCTION public.commons_profiles_mirror_dice();

CREATE FUNCTION public.commons_profiles_readiness() RETURNS boolean
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE role_name text;
BEGIN
 IF NOT EXISTS (SELECT FROM public.dice_schema_migrations WHERE version = 87) THEN
  RAISE EXCEPTION 'Commons profiles: migration receipt missing';
 END IF;
 IF NOT EXISTS (SELECT FROM pg_catalog.pg_class
  WHERE oid = pg_catalog.to_regclass('public.commons_profiles') AND relrowsecurity) THEN
  RAISE EXCEPTION 'Commons profiles: table missing or RLS is disabled';
 END IF;
 FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
  IF pg_catalog.has_any_column_privilege(role_name, 'public.commons_profiles', 'SELECT,INSERT,UPDATE')
   OR pg_catalog.has_table_privilege(role_name, 'public.commons_profiles', 'DELETE,TRUNCATE')
   OR pg_catalog.has_function_privilege(role_name, 'public.commons_profiles_mirror_dice()', 'EXECUTE') THEN
   RAISE EXCEPTION 'Commons profiles: unsafe browser grants';
  END IF;
 END LOOP;
 IF NOT pg_catalog.has_table_privilege('service_role', 'public.commons_profiles', 'SELECT')
  OR NOT pg_catalog.has_table_privilege('service_role', 'public.commons_profiles', 'INSERT')
  OR NOT pg_catalog.has_table_privilege('service_role', 'public.commons_profiles', 'UPDATE')
  OR NOT pg_catalog.has_table_privilege('service_role', 'public.commons_profiles', 'DELETE') THEN
  RAISE EXCEPTION 'Commons profiles: service_role grants changed';
 END IF;
 IF NOT EXISTS (SELECT FROM pg_catalog.pg_trigger
  WHERE tgrelid = 'public.commons_profiles'::regclass AND tgname = 'commons_profiles_mirror_dice'
  AND tgenabled = 'O' AND NOT tgisinternal
  AND tgfoid = 'public.commons_profiles_mirror_dice()'::regprocedure) THEN
  RAISE EXCEPTION 'Commons profiles: Dice mirror trigger missing or disabled';
 END IF;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.commons_profiles_readiness() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commons_profiles_readiness() TO service_role;

-- Preserve the public readiness entry point while extending its attestation.
ALTER FUNCTION public.dice_release_readiness() RENAME TO dice_schema_0084_readiness;
CREATE FUNCTION public.dice_release_readiness() RETURNS boolean
 LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
 PERFORM public.dice_schema_0084_readiness();
 PERFORM public.commons_profiles_readiness();
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.dice_release_readiness() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dice_release_readiness() TO service_role;
