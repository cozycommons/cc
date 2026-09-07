-- Capture who/where an analytics event came from, best-effort: user_id/email
-- when the request carried a valid Supabase access token, session_id when
-- the frontend sent one, and the resolved client IP. All nullable since most
-- tracked traffic today (anonymous ticket browsing) has no user_id.

ALTER TABLE public.analytics_events
  ADD COLUMN user_id uuid,
  ADD COLUMN email text,
  ADD COLUMN session_id text,
  ADD COLUMN ip_address text;

CREATE INDEX analytics_events_user_id_idx
  ON public.analytics_events (user_id)
  WHERE user_id IS NOT NULL;

CREATE INDEX analytics_events_session_id_idx
  ON public.analytics_events (session_id)
  WHERE session_id IS NOT NULL;

-- Rollback block (run manually via Supabase SQL editor if needed):
-- DROP INDEX IF EXISTS public.analytics_events_session_id_idx;
-- DROP INDEX IF EXISTS public.analytics_events_user_id_idx;
-- ALTER TABLE public.analytics_events
--   DROP COLUMN IF EXISTS ip_address,
--   DROP COLUMN IF EXISTS session_id,
--   DROP COLUMN IF EXISTS email,
--   DROP COLUMN IF EXISTS user_id;
