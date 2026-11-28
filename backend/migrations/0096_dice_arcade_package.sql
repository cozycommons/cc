-- Game packages use existing private Supabase Storage, not a host filesystem.
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
CREATE TABLE public.arcade_package (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 digest text NOT NULL CHECK(digest ~ '^[0-9a-f]{64}$'),
 installed_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
 installed_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.arcade_package ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.arcade_package FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT,INSERT,UPDATE ON public.arcade_package TO service_role;
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
 VALUES('arcade-packages','arcade-packages',false,41943040,ARRAY['application/gzip'])
 ON CONFLICT(id) DO UPDATE SET public=false,file_size_limit=41943040,allowed_mime_types=ARRAY['application/gzip'];
CREATE POLICY arcade_packages_browser_deny ON storage.objects AS RESTRICTIVE
 FOR ALL TO anon,authenticated USING(bucket_id <> 'arcade-packages') WITH CHECK(bucket_id <> 'arcade-packages');

ALTER FUNCTION public.arcade_readiness() RENAME TO arcade_0095_readiness;
CREATE FUNCTION public.arcade_readiness() RETURNS boolean
 LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
BEGIN
 PERFORM public.arcade_0095_readiness();
 IF NOT EXISTS(SELECT FROM public.dice_schema_migrations WHERE version=96)
  OR NOT EXISTS(SELECT FROM storage.buckets WHERE id='arcade-packages' AND public=false AND file_size_limit=41943040)
  OR NOT EXISTS(SELECT FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname='arcade_package' AND c.relrowsecurity)
  OR pg_catalog.has_table_privilege('anon','public.arcade_package','SELECT,INSERT,UPDATE,DELETE')
  OR pg_catalog.has_table_privilege('authenticated','public.arcade_package','SELECT,INSERT,UPDATE,DELETE')
  OR NOT pg_catalog.has_table_privilege('service_role','public.arcade_package','SELECT')
  OR NOT pg_catalog.has_table_privilege('service_role','public.arcade_package','INSERT')
  OR NOT pg_catalog.has_table_privilege('service_role','public.arcade_package','UPDATE')
  OR NOT EXISTS(SELECT FROM pg_catalog.pg_policy WHERE polrelid='storage.objects'::regclass
    AND polname='arcade_packages_browser_deny' AND polpermissive=false) THEN
  RAISE EXCEPTION 'Arcade package schema contract changed';
 END IF;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.arcade_readiness() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.arcade_readiness() TO service_role;
