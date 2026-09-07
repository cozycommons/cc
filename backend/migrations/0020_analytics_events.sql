-- Lightweight page view / search query analytics, starting with the tickets app.
-- Backend-only table (service role writes/reads via app.state.analytics_supabase); no RLS needed.

CREATE TABLE public.analytics_events (
  id          bigserial PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  app         text NOT NULL,
  event_type  text NOT NULL CHECK (event_type IN ('pageview', 'search')),
  label       text,
  path        text NOT NULL,
  metadata    jsonb
);

CREATE INDEX analytics_events_app_type_created_at_idx
  ON public.analytics_events (app, event_type, created_at);

-- No policies: only the backend's service-role client reads/writes this table,
-- and service role bypasses RLS entirely (mirrors tickets_landing_snapshot_cache).
ALTER TABLE public.analytics_events ENABLE ROW LEVEL SECURITY;

-- Rollback block (run manually via Supabase SQL editor if needed):
-- DROP TABLE IF EXISTS public.analytics_events;
