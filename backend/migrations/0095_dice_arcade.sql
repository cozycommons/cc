-- Arcade uses the same hosted database and release family as Commons profiles.
-- Existing local-only SQLite test files were never installed on the hosted API.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.arcade_profiles (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 settings jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
 legacy_settings text NOT NULL DEFAULT '<UserSettings><CurDas>9001</CurDas><CurArr>9007</CurArr></UserSettings>'
);
CREATE TABLE public.arcade_sessions (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 token_hash text NOT NULL UNIQUE CHECK (length(token_hash) = 64),
 expires_at bigint NOT NULL,
 current_run uuid
);
CREATE TABLE public.arcade_runs (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 session_id uuid NOT NULL REFERENCES public.arcade_sessions(id) ON DELETE CASCADE,
 started_at bigint NOT NULL DEFAULT extract(epoch FROM now())::bigint,
 metrics jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
 record text
);
ALTER TABLE public.arcade_sessions ADD CONSTRAINT arcade_current_run_fk
 FOREIGN KEY(current_run) REFERENCES public.arcade_runs(id) ON DELETE SET NULL;
CREATE INDEX arcade_runs_owner ON public.arcade_runs(user_id, started_at DESC, id);
CREATE INDEX arcade_sessions_owner ON public.arcade_sessions(user_id);

ALTER TABLE public.arcade_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.arcade_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.arcade_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.arcade_profiles, public.arcade_sessions, public.arcade_runs
 FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.arcade_profiles, public.arcade_sessions, public.arcade_runs TO service_role;

-- Start and save are atomic because a movie's callbacks may overlap.
CREATE FUNCTION public.arcade_start_run(p_session_id uuid, p_user_id uuid) RETURNS uuid
 LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE run_id uuid := pg_catalog.gen_random_uuid();
BEGIN
 PERFORM 1 FROM public.arcade_sessions
 WHERE id=p_session_id AND user_id=p_user_id AND expires_at > extract(epoch FROM now())::bigint
 FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Arcade session unavailable'; END IF;
 INSERT INTO public.arcade_runs(id,user_id,session_id) VALUES(run_id,p_user_id,p_session_id);
 UPDATE public.arcade_sessions SET current_run=run_id WHERE id=p_session_id AND user_id=p_user_id;
 RETURN run_id;
END $$;

CREATE FUNCTION public.arcade_save_run(p_session_id uuid, p_user_id uuid, p_metrics jsonb, p_record text)
 RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE run_id uuid;
BEGIN
 SELECT current_run INTO run_id FROM public.arcade_sessions
 WHERE id=p_session_id AND user_id=p_user_id AND expires_at > extract(epoch FROM now())::bigint
 FOR UPDATE;
 IF NOT FOUND OR run_id IS NULL THEN RAISE EXCEPTION 'Arcade run unavailable'; END IF;
 UPDATE public.arcade_runs SET metrics=metrics || coalesce(p_metrics,'{}'::jsonb),
  record=coalesce(p_record,record)
 WHERE id=run_id AND user_id=p_user_id AND session_id=p_session_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Arcade run unavailable'; END IF;
 RETURN true;
END $$;

REVOKE ALL ON FUNCTION public.arcade_start_run(uuid,uuid),
 public.arcade_save_run(uuid,uuid,jsonb,text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.arcade_start_run(uuid,uuid),
 public.arcade_save_run(uuid,uuid,jsonb,text) TO service_role;

CREATE FUNCTION public.arcade_readiness() RETURNS boolean
 LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE table_name text; signature text; role_name text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['arcade_profiles','arcade_sessions','arcade_runs'] LOOP
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname=table_name AND c.relrowsecurity)
   OR NOT pg_catalog.has_table_privilege('service_role','public.'||table_name,'SELECT')
   OR NOT pg_catalog.has_table_privilege('service_role','public.'||table_name,'INSERT')
   OR NOT pg_catalog.has_table_privilege('service_role','public.'||table_name,'UPDATE') THEN
   RAISE EXCEPTION 'Arcade schema contract: missing storage or service grants';
  END IF;
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
   IF pg_catalog.has_table_privilege(role_name,'public.'||table_name,'SELECT,INSERT,UPDATE,DELETE')
    OR pg_catalog.has_any_column_privilege(role_name,'public.'||table_name,'SELECT,INSERT,UPDATE') THEN
    RAISE EXCEPTION 'Arcade schema contract: exposed player state';
   END IF;
  END LOOP;
 END LOOP;
 FOREACH signature IN ARRAY ARRAY['public.arcade_start_run(uuid,uuid)','public.arcade_save_run(uuid,uuid,jsonb,text)'] LOOP
  IF NOT pg_catalog.has_function_privilege('service_role',signature,'EXECUTE')
   OR pg_catalog.has_function_privilege('anon',signature,'EXECUTE')
   OR pg_catalog.has_function_privilege('authenticated',signature,'EXECUTE') THEN
   RAISE EXCEPTION 'Arcade schema contract: unsafe function grants';
  END IF;
 END LOOP;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.arcade_readiness() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.arcade_readiness() TO service_role;

ALTER FUNCTION public.dice_release_readiness() RENAME TO dice_0088_release_readiness;
CREATE FUNCTION public.dice_release_readiness() RETURNS boolean
 LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
 PERFORM public.dice_0088_release_readiness();
 IF NOT EXISTS (SELECT FROM public.dice_schema_migrations WHERE version=95) THEN
  RAISE EXCEPTION 'Arcade schema contract: migration receipt missing';
 END IF;
 RETURN public.arcade_readiness();
END $$;
REVOKE ALL ON FUNCTION public.dice_release_readiness() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dice_release_readiness() TO service_role;
