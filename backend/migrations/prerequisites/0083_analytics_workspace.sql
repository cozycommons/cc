-- Adopted Dice baselines may omit the old cross-project analytics table.
-- Prepare only the legacy shape required by 0083, in its transaction.
CREATE TABLE IF NOT EXISTS public.analytics_events (
 id bigserial PRIMARY KEY,
 created_at timestamptz NOT NULL DEFAULT now(),
 app text NOT NULL,
 event_type text NOT NULL CHECK (event_type IN ('pageview', 'search')),
 label text,
 path text NOT NULL,
 metadata jsonb
);
ALTER TABLE public.analytics_events
 ADD COLUMN IF NOT EXISTS user_id uuid,
 ADD COLUMN IF NOT EXISTS email text,
 ADD COLUMN IF NOT EXISTS session_id text,
 ADD COLUMN IF NOT EXISTS ip_address text;
CREATE INDEX IF NOT EXISTS analytics_events_app_type_created_at_idx
 ON public.analytics_events (app, event_type, created_at);
CREATE INDEX IF NOT EXISTS analytics_events_user_id_idx
 ON public.analytics_events (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS analytics_events_session_id_idx
 ON public.analytics_events (session_id) WHERE session_id IS NOT NULL;
ALTER TABLE public.analytics_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.analytics_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.analytics_events TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.analytics_events_id_seq TO service_role;
