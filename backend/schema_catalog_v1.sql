-- Catalog format v1 is used by immutable migration 0084. Add a new version to extend it.
CREATE OR REPLACE FUNCTION pg_temp.cozy_schema_catalog_v1()
RETURNS TABLE(kind text, key text, definition jsonb)
LANGUAGE sql STABLE SET search_path=pg_catalog,public
AS $catalog$
WITH relations AS (
 SELECT c.*,n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('public','analytics') AND c.relkind IN ('r','p','v','m','S')
), objects AS (
 SELECT 'relation' AS kind,nspname||'.'||relname AS key,
 jsonb_build_object('kind',relkind,'rls',relrowsecurity,'force_rls',relforcerowsecurity,'options',reloptions) AS definition
 FROM relations
 UNION ALL
 SELECT 'column',r.nspname||'.'||r.relname||'.'||a.attname,
 jsonb_build_object('type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,
 'default',pg_get_expr(d.adbin,d.adrelid),'identity',a.attidentity,'generated',a.attgenerated,
 'collation',CASE WHEN a.attcollation=0 THEN NULL ELSE a.attcollation::regcollation::text END)
 FROM relations r JOIN pg_attribute a ON a.attrelid=r.oid AND a.attnum>0 AND NOT a.attisdropped
 LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
 WHERE r.relkind IN ('r','p','v','m')
 UNION ALL
 SELECT 'constraint',r.nspname||'.'||r.relname||'.'||c.conname,
 jsonb_build_object('type',c.contype,'definition',pg_get_constraintdef(c.oid),'validated',c.convalidated)
 FROM relations r JOIN pg_constraint c ON c.conrelid=r.oid
 UNION ALL
 SELECT 'index',n.nspname||'.'||c.relname,
 jsonb_build_object('definition',pg_get_indexdef(c.oid),'valid',i.indisvalid,'ready',i.indisready)
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_index i ON i.indexrelid=c.oid
 WHERE n.nspname IN ('public','analytics')
 UNION ALL
 SELECT 'policy',r.nspname||'.'||r.relname||'.'||p.polname,
 jsonb_build_object('command',p.polcmd,'permissive',p.polpermissive,
 'roles',(SELECT jsonb_agg(role_name ORDER BY role_name COLLATE "C") FROM (SELECT CASE WHEN role_id=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role_id)::text END AS role_name FROM unnest(p.polroles) role_id) roles),
 'using',pg_get_expr(p.polqual,p.polrelid),'check',pg_get_expr(p.polwithcheck,p.polrelid))
 FROM relations r JOIN pg_policy p ON p.polrelid=r.oid
 UNION ALL
 SELECT 'trigger',r.nspname||'.'||r.relname||'.'||t.tgname,
 jsonb_build_object('definition',pg_get_triggerdef(t.oid),'enabled',t.tgenabled)
 FROM relations r JOIN pg_trigger t ON t.tgrelid=r.oid WHERE NOT t.tgisinternal
 UNION ALL
 SELECT 'view',r.nspname||'.'||r.relname,jsonb_build_object('definition',pg_get_viewdef(r.oid,true))
 FROM relations r WHERE r.relkind IN ('v','m')
 UNION ALL
 SELECT 'function',n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')',
 jsonb_build_object('definition_hash',md5(pg_get_functiondef(p.oid)),
 'security_definer',p.prosecdef,'config',p.proconfig)
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN ('public','analytics') AND p.prokind IN ('f','p')
 AND p.prorettype <> 'event_trigger'::regtype
 AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')
 UNION ALL
 SELECT 'enum',n.nspname||'.'||t.typname,jsonb_build_object('values',jsonb_agg(e.enumlabel ORDER BY e.enumsortorder))
 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace JOIN pg_enum e ON e.enumtypid=t.oid
 WHERE n.nspname IN ('public','analytics') GROUP BY n.nspname,t.typname
 UNION ALL
 SELECT 'type_acl',n.nspname||'.'||t.typname||':'||CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee)::text END||':'||a.privilege_type,jsonb_build_object('grantable',a.is_grantable)
 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
 CROSS JOIN LATERAL aclexplode(coalesce(t.typacl,acldefault('T',t.typowner))) a
 WHERE n.nspname IN ('public','analytics') AND t.typtype IN ('e','d','r','m')
 AND NOT EXISTS(SELECT FROM pg_depend d WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e')
 AND (a.grantee=0 OR pg_get_userbyid(a.grantee) IN ('anon','authenticated','service_role','commons_analytics_reader'))
 UNION ALL
 SELECT 'sequence',r.nspname||'.'||r.relname,
 jsonb_build_object('type',format_type(s.seqtypid,NULL),'start',s.seqstart::text,'increment',s.seqincrement::text,'min',s.seqmin::text,'max',s.seqmax::text,'cache',s.seqcache::text,'cycle',s.seqcycle,
 'owned_by',(SELECT min(cn.nspname||'.'||c.relname||'.'||a.attname) FROM pg_depend d JOIN pg_class c ON c.oid=d.refobjid JOIN pg_namespace cn ON cn.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=d.refobjsubid WHERE d.classid='pg_class'::regclass AND d.objid=s.seqrelid AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')))
 FROM relations r JOIN pg_sequence s ON s.seqrelid=r.oid
 UNION ALL
 SELECT 'relation_acl',r.nspname||'.'||r.relname||':'||CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee)::text END||':'||a.privilege_type,
 jsonb_build_object('grantable',a.is_grantable)
 FROM relations r CROSS JOIN LATERAL aclexplode(coalesce(r.relacl,acldefault(CASE WHEN r.relkind='S' THEN 's'::"char" ELSE 'r'::"char" END,r.relowner))) a
 WHERE a.grantee=0 OR pg_get_userbyid(a.grantee) IN ('anon','authenticated','service_role','commons_analytics_reader')
 UNION ALL
 SELECT 'column_acl',r.nspname||'.'||r.relname||'.'||c.attname||':'||CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee)::text END||':'||a.privilege_type,
 jsonb_build_object('grantable',a.is_grantable)
 FROM relations r JOIN pg_attribute c ON c.attrelid=r.oid AND c.attnum>0 AND NOT c.attisdropped
 CROSS JOIN LATERAL aclexplode(c.attacl) a
 WHERE a.grantee=0 OR pg_get_userbyid(a.grantee) IN ('anon','authenticated','service_role','commons_analytics_reader')
 UNION ALL
 SELECT 'function_acl',n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||'):'||CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee)::text END||':'||a.privilege_type,
 jsonb_build_object('grantable',a.is_grantable)
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
 WHERE n.nspname IN ('public','analytics') AND p.prokind IN ('f','p') AND p.prorettype <> 'event_trigger'::regtype
 AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')
 AND (a.grantee=0 OR pg_get_userbyid(a.grantee) IN ('anon','authenticated','service_role','commons_analytics_reader'))
 UNION ALL
 SELECT 'schema_acl',n.nspname||':'||CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee)::text END||':'||a.privilege_type,jsonb_build_object('grantable',a.is_grantable)
 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a
 WHERE n.nspname IN ('public','analytics') AND (a.grantee=0 OR pg_get_userbyid(a.grantee) IN ('anon','authenticated','service_role','commons_analytics_reader'))
 UNION ALL
 SELECT 'default_acl',coalesce(n.nspname,'*')||':'||d.defaclobjtype::text||':'||CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee)::text END||':'||a.privilege_type,jsonb_build_object('grantable',a.is_grantable)
 FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace CROSS JOIN LATERAL aclexplode(d.defaclacl) a
 WHERE pg_get_userbyid(d.defaclrole)='postgres' AND (n.nspname IN ('public','analytics') OR d.defaclnamespace=0)
 AND (a.grantee=0 OR pg_get_userbyid(a.grantee) IN ('anon','authenticated','service_role','commons_analytics_reader'))
)
SELECT kind,key,definition FROM objects ORDER BY kind,key;
$catalog$;
