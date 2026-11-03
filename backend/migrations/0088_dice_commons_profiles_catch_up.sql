-- Catch up commons_profiles before the API starts writing it (M4 PR 2).
-- Between 0087 and this release the old code still wrote names and avatars to
-- dice_profiles and Venmo handles to Auth metadata, and new accounts got no
-- row. Re-running the 0087 backfill as an upsert keeps those edits. Nothing
-- wrote commons_profiles in that window, so no newer value is overwritten.
-- The mirror is paused so dice_profiles is left exactly as it is.
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';

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
CROSS JOIN LATERAL (SELECT CASE WHEN jsonb_typeof(u.raw_user_meta_data->'venmo_username') = 'string'
 THEN btrim(regexp_replace(btrim(split_part(regexp_replace(
  btrim(u.raw_user_meta_data->>'venmo_username', E' \t\r\n'),
  '^(https?://)?(www\.|account\.)?venmo\.com/(u/)?', '', 'i'), '?', 1), '/'), '^@', ''), E' \t\r\n')
 END AS candidate) n
CROSS JOIN LATERAL (SELECT CASE WHEN n.candidate ~ '^[A-Za-z0-9_-]{5,30}$' THEN n.candidate END AS username,
 u.raw_user_meta_data->'venmo_username_provenance' AS provenance) v
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
