CREATE TABLE public.commons_user_roles (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 role text NOT NULL CHECK (role IN ('member', 'admin')),
 assigned_by uuid,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.commons_role_history (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id uuid NOT NULL,
 actor_id uuid,
 old_role text NOT NULL CHECK (old_role IN ('member', 'admin')),
 new_role text NOT NULL CHECK (new_role IN ('member', 'admin')),
 source text NOT NULL CHECK (source IN ('migration', 'admin', 'recovery')),
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.commons_user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.commons_role_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.commons_user_roles, public.commons_role_history FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.commons_user_roles TO authenticated;
CREATE POLICY commons_own_role ON public.commons_user_roles FOR SELECT TO authenticated
 USING (user_id = (SELECT auth.uid()));
GRANT ALL ON public.commons_user_roles, public.commons_role_history TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.commons_role_history_id_seq TO service_role;

CREATE VIEW public.commons_accounts WITH (security_barrier=true) AS
 SELECT id AS user_id, email,
 coalesce(raw_user_meta_data->>'full_name', raw_user_meta_data->>'name', email) AS display_name,
 email_confirmed_at IS NOT NULL AS verified
 FROM auth.users WHERE is_anonymous IS NOT TRUE;
REVOKE ALL ON public.commons_accounts FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.commons_accounts TO service_role;

INSERT INTO public.commons_user_roles(user_id, role)
 SELECT id, 'admin' FROM auth.users
 WHERE email_confirmed_at IS NOT NULL AND is_anonymous IS NOT TRUE
 AND (lower(email) IN ('jason.keungg@gmail.com', 'homatt999@gmail.com')
 OR raw_app_meta_data->'commons_admin' = 'true'::jsonb
 OR raw_app_meta_data->'crowdset_admin' = 'true'::jsonb);
INSERT INTO public.commons_role_history(user_id, old_role, new_role, source)
 SELECT user_id, 'member', 'admin', 'migration' FROM public.commons_user_roles;

CREATE FUNCTION public.commons_get_role(p_user_id uuid) RETURNS text
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
 SELECT coalesce((SELECT r.role FROM public.commons_user_roles r
 JOIN public.commons_accounts a USING(user_id)
 WHERE r.user_id=p_user_id AND a.verified), 'member');
$$;

CREATE FUNCTION public.commons_list_users(p_search text DEFAULT '', p_offset integer DEFAULT 0)
 RETURNS TABLE(user_id uuid, email text, display_name text, verified boolean, role text)
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
 SELECT a.user_id, a.email::text, a.display_name, a.verified, coalesce(r.role, 'member')
 FROM public.commons_accounts a LEFT JOIN public.commons_user_roles r USING(user_id)
 WHERE strpos(lower(coalesce(a.email, '')), lower(p_search)) > 0
 OR strpos(lower(coalesce(a.display_name, '')), lower(p_search)) > 0
 ORDER BY lower(coalesce(a.email, '')), a.user_id
 LIMIT 51 OFFSET greatest(0, least(p_offset, 1000000));
$$;

CREATE FUNCTION public.commons_set_role(p_actor_id uuid, p_user_id uuid, p_role text, p_expected_role text)
 RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE previous_role text;
BEGIN
 PERFORM pg_catalog.pg_advisory_xact_lock(873241905);
 IF public.commons_get_role(p_actor_id) <> 'admin' THEN
  RAISE SQLSTATE 'PT403' USING MESSAGE = 'Access denied.';
 END IF;
 IF p_role NOT IN ('member','admin') OR p_expected_role NOT IN ('member','admin')
 OR p_role IS NULL OR p_expected_role IS NULL THEN
  RAISE SQLSTATE 'PT422' USING MESSAGE = 'Invalid role.';
 END IF;
 IF NOT EXISTS (SELECT FROM public.commons_accounts WHERE user_id=p_user_id) THEN
  RAISE SQLSTATE 'PT404' USING MESSAGE = 'Account not found.';
 END IF;
 IF p_role='admin' AND NOT EXISTS (SELECT FROM public.commons_accounts WHERE user_id=p_user_id AND verified) THEN
  RAISE SQLSTATE 'PT422' USING MESSAGE = 'Only verified accounts can become admins.';
 END IF;
 SELECT coalesce((SELECT role FROM public.commons_user_roles WHERE user_id=p_user_id), 'member') INTO previous_role;
 IF previous_role=p_role THEN RETURN p_role; END IF;
 IF previous_role<>p_expected_role THEN
  RAISE SQLSTATE 'PT409' USING MESSAGE = 'Role changed. Refresh before trying again.';
 END IF;
 IF previous_role='admin' AND p_role='member' AND NOT EXISTS (
  SELECT FROM public.commons_user_roles r JOIN public.commons_accounts a USING(user_id)
  WHERE r.role='admin' AND r.user_id<>p_user_id AND a.verified
 ) THEN
  RAISE SQLSTATE 'PT409' USING MESSAGE = 'The last admin cannot be removed.';
 END IF;
 INSERT INTO public.commons_user_roles(user_id, role, assigned_by, updated_at)
 VALUES(p_user_id, p_role, p_actor_id, now())
 ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, assigned_by=excluded.assigned_by, updated_at=excluded.updated_at;
 INSERT INTO public.commons_role_history(user_id, actor_id, old_role, new_role, source)
 VALUES(p_user_id, p_actor_id, previous_role, p_role, 'admin');
 RETURN p_role;
END $$;
REVOKE ALL ON FUNCTION public.commons_get_role(uuid), public.commons_list_users(text,integer), public.commons_set_role(uuid,uuid,text,text)
 FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commons_get_role(uuid), public.commons_list_users(text,integer), public.commons_set_role(uuid,uuid,text,text)
 TO service_role;

CREATE VIEW public.commons_role_audit WITH (security_barrier=true) AS
 SELECT h.*, coalesce(u.email, h.user_id::text) AS user_label,
 a.email AS actor_label
 FROM public.commons_role_history h
 LEFT JOIN public.commons_accounts u ON u.user_id=h.user_id
 LEFT JOIN public.commons_accounts a ON a.user_id=h.actor_id;
REVOKE ALL ON public.commons_role_audit FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.commons_role_audit TO service_role;
