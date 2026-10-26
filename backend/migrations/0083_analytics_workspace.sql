CREATE TYPE public.analytics_event_type AS ENUM ('pageview', 'search', 'activity', 'action');
ALTER TABLE public.analytics_events DROP CONSTRAINT analytics_events_event_type_check;
ALTER TABLE public.analytics_events ALTER COLUMN event_type TYPE public.analytics_event_type USING event_type::public.analytics_event_type;
ALTER TABLE public.analytics_events
 ADD COLUMN event_id uuid UNIQUE,
 ADD COLUMN schema_version integer NOT NULL DEFAULT 0 CHECK (schema_version IN (0,1)),
 ADD COLUMN event_name text,
 ADD COLUMN identity_status text NOT NULL DEFAULT 'legacy_unverified' CHECK (identity_status IN ('legacy_unverified','verified','anonymous'));
CREATE INDEX analytics_events_project_time_v1 ON public.analytics_events(app, created_at) WHERE schema_version=1;
CREATE TABLE public.analytics_saved_queries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 title text NOT NULL,
 sql text NOT NULL,
 visualization jsonb NOT NULL DEFAULT '{"type":"table"}',
 position integer NOT NULL DEFAULT 0,
 revision integer NOT NULL DEFAULT 1,
 created_by uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.analytics_saved_queries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.analytics_saved_queries FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.analytics_saved_queries TO service_role;
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='commons_analytics_reader') THEN
  CREATE ROLE commons_analytics_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
ALTER ROLE commons_analytics_reader SET default_transaction_read_only=on;
ALTER ROLE commons_analytics_reader SET statement_timeout='5s';
CREATE SCHEMA analytics;
REVOKE ALL ON SCHEMA analytics FROM PUBLIC;
GRANT USAGE ON SCHEMA analytics TO commons_analytics_reader;
CREATE VIEW analytics.events WITH (security_barrier=true) AS
 SELECT event_id, created_at, app AS project, event_type::text, event_name, session_id, user_id, identity_status, path, metadata
 FROM public.analytics_events WHERE schema_version=1;
CREATE VIEW analytics.legacy_events WITH (security_barrier=true) AS
 SELECT id, created_at, app AS project, event_type::text, label, path, metadata
 FROM public.analytics_events WHERE schema_version=0;
CREATE VIEW analytics.users WITH (security_barrier=true) AS
 SELECT id AS user_id, coalesce(raw_user_meta_data->>'full_name', raw_user_meta_data->>'name') AS display_name,
 created_at, last_sign_in_at FROM auth.users WHERE is_anonymous IS NOT TRUE;
REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM PUBLIC, anon, authenticated;
GRANT SELECT ON analytics.events, analytics.legacy_events, analytics.users TO commons_analytics_reader;

INSERT INTO public.analytics_saved_queries(title, sql, visualization, position) VALUES
('Active users', $query$
SELECT project, count(DISTINCT user_id) AS active_users
FROM analytics.events
WHERE created_at >= $1::timestamptz AND created_at < $2::timestamptz
AND ($3::text IS NULL OR project = $3::text) AND identity_status = 'verified'
GROUP BY project ORDER BY project
$query$, '{"type":"bar","x":"project","y":["active_users"]}', 0),
('Visits', $query$
SELECT project, count(DISTINCT session_id) AS visits,
count(DISTINCT session_id) FILTER (WHERE identity_status = 'verified') AS logged_in,
count(DISTINCT session_id) FILTER (WHERE identity_status = 'anonymous') AS logged_out
FROM analytics.events
WHERE created_at >= $1::timestamptz AND created_at < $2::timestamptz
AND ($3::text IS NULL OR project = $3::text)
GROUP BY project ORDER BY project
$query$, '{"type":"bar","x":"project","y":["logged_in","logged_out"]}', 1),
('Daily active users', $query$
WITH days AS (SELECT generate_series($1::timestamptz, $2::timestamptz - '1 day'::interval, '1 day'::interval) AS day),
projects AS (SELECT 'commons' AS project UNION ALL SELECT 'dice' UNION ALL SELECT 'trips' UNION ALL SELECT 'crowdset' UNION ALL SELECT 'fantasy')
SELECT days.day::date AS day, projects.project, count(DISTINCT events.user_id) AS active_users
FROM days CROSS JOIN projects LEFT JOIN analytics.events events
ON events.project = projects.project AND events.created_at >= days.day AND events.created_at < days.day + '1 day'::interval
AND events.identity_status = 'verified'
WHERE ($3::text IS NULL OR projects.project = $3::text)
GROUP BY days.day, projects.project ORDER BY days.day, projects.project
$query$, '{"type":"line","x":"day","y":["active_users"],"series":"project"}', 2),
('Daily visits', $query$
WITH days AS (SELECT generate_series($1::timestamptz, $2::timestamptz - '1 day'::interval, '1 day'::interval) AS day),
projects AS (SELECT 'commons' AS project UNION ALL SELECT 'dice' UNION ALL SELECT 'trips' UNION ALL SELECT 'crowdset' UNION ALL SELECT 'fantasy')
SELECT days.day::date AS day, projects.project,
count(DISTINCT events.session_id) FILTER (WHERE events.identity_status = 'verified') AS logged_in,
count(DISTINCT events.session_id) FILTER (WHERE events.identity_status = 'anonymous') AS logged_out
FROM days CROSS JOIN projects LEFT JOIN analytics.events events
ON events.project = projects.project AND events.created_at >= days.day AND events.created_at < days.day + '1 day'::interval
WHERE ($3::text IS NULL OR projects.project = $3::text)
GROUP BY days.day, projects.project ORDER BY days.day, projects.project
$query$, '{"type":"line","x":"day","y":["logged_in","logged_out"],"series":"project"}', 3);
