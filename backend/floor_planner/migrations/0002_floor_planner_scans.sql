create table public.floor_plan_scans (
  id uuid primary key,
  document_id uuid not null unique references public.floor_plan_documents(id) on delete cascade,
  object_key text not null unique,
  filename text not null check (char_length(filename) between 1 and 200),
  byte_size bigint not null check (byte_size between 1 and 52428800),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now()
);
create table public.floor_plan_scan_cleanup (
  object_key text primary key,
  created_at timestamptz not null default now()
);
alter table public.floor_plan_scans enable row level security;
alter table public.floor_plan_scan_cleanup enable row level security;
revoke all on public.floor_plan_scans, public.floor_plan_scan_cleanup from public, anon, authenticated;
grant select, insert, update, delete on public.floor_plan_scans, public.floor_plan_scan_cleanup to service_role;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('floor-plan-scans', 'floor-plan-scans', false, 52428800, array['model/vnd.usdz+zip'])
on conflict (id) do update set public = false, file_size_limit = 52428800,
  allowed_mime_types = array['model/vnd.usdz+zip'];
create policy floor_plan_scans_browser_deny on storage.objects as restrictive
for all to anon, authenticated
using (bucket_id <> 'floor-plan-scans') with check (bucket_id <> 'floor-plan-scans');

create function public.floor_planner_queue_scan_cleanup() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' or old.object_key is distinct from new.object_key then
    insert into public.floor_plan_scan_cleanup(object_key) values (old.object_key)
      on conflict do nothing;
  end if;
  return null;
end;
$$;
revoke all on function public.floor_planner_queue_scan_cleanup() from public, anon, authenticated;
create trigger floor_plan_scan_cleanup_after_change after update or delete on public.floor_plan_scans
for each row execute function public.floor_planner_queue_scan_cleanup();

create function public.floor_planner_set_scan(
  p_document_id uuid, p_user_id uuid, p_email text, p_expected_id uuid, p_scan jsonb
) returns jsonb language plpgsql set search_path = '' as $$
declare
  document public.floor_plan_documents%rowtype;
  existing public.floor_plan_scans%rowtype;
  saved public.floor_plan_scans%rowtype;
begin
  select * into document from public.floor_plan_documents where id = p_document_id for update;
  if not found or p_user_id is null or p_email is null then
    return jsonb_build_object('status', 'denied');
  end if;
  if document.owner_id <> p_user_id and not exists (
    select 1 from public.floor_plan_invitations
    where document_id = p_document_id and revoked_at is null
      and (accepted_user_id = p_user_id or email = lower(p_email))
  ) then
    return jsonb_build_object('status', 'denied');
  end if;
  select * into existing from public.floor_plan_scans where document_id = p_document_id;
  if existing.id is distinct from p_expected_id then
    return jsonb_build_object('status', 'conflict');
  end if;
  if p_scan is null then
    delete from public.floor_plan_scans where document_id = p_document_id;
  else
    insert into public.floor_plan_scans(id, document_id, object_key, filename, byte_size, sha256)
      values ((p_scan->>'id')::uuid, p_document_id, p_scan->>'object_key', p_scan->>'filename',
              (p_scan->>'byte_size')::bigint, p_scan->>'sha256')
      on conflict (document_id) do update set id = excluded.id, object_key = excluded.object_key,
        filename = excluded.filename, byte_size = excluded.byte_size, sha256 = excluded.sha256,
        created_at = now()
      returning * into saved;
    delete from public.floor_plan_scan_cleanup where object_key = saved.object_key;
  end if;
  return jsonb_build_object('status', 'ok', 'scan', to_jsonb(saved), 'old_key', existing.object_key);
end;
$$;
revoke all on function public.floor_planner_set_scan(uuid,uuid,text,uuid,jsonb) from public, anon, authenticated;
grant execute on function public.floor_planner_set_scan(uuid,uuid,text,uuid,jsonb) to service_role;

alter function public.floor_planner_release_readiness() rename to floor_planner_documents_readiness;
create function public.floor_planner_release_readiness() returns boolean
language plpgsql stable set search_path = '' as $$
declare
  table_name text;
  role_name text;
begin
  perform public.floor_planner_documents_readiness();
  if not exists (select 1 from public.floor_planner_schema_migrations where version = 2) then
    raise exception 'Floor Planner scans: migration receipt missing';
  end if;
  foreach table_name in array array['floor_plan_scans', 'floor_plan_scan_cleanup'] loop
    if not exists (select 1 from pg_catalog.pg_class
      where oid = pg_catalog.to_regclass('public.' || table_name) and relrowsecurity) then
      raise exception 'Floor Planner scans: table missing or RLS disabled';
    end if;
    foreach role_name in array array['anon', 'authenticated'] loop
      if pg_catalog.has_any_column_privilege(role_name, 'public.' || table_name, 'SELECT')
         or pg_catalog.has_table_privilege(role_name, 'public.' || table_name, 'INSERT,UPDATE,DELETE,TRUNCATE') then
        raise exception 'Floor Planner scans: unsafe browser grants';
      end if;
    end loop;
  end loop;
  if not exists (select 1 from storage.buckets where id = 'floor-plan-scans' and public = false
    and file_size_limit = 52428800) then
    raise exception 'Floor Planner scans: private bucket missing or limit changed';
  end if;
  if not exists (select 1 from pg_catalog.pg_policy where polrelid = 'storage.objects'::regclass
    and polname = 'floor_plan_scans_browser_deny' and polpermissive = false) then
    raise exception 'Floor Planner scans: Storage browser deny policy missing';
  end if;
  if pg_catalog.has_function_privilege('anon', 'public.floor_planner_set_scan(uuid,uuid,text,uuid,jsonb)', 'EXECUTE')
     or pg_catalog.has_function_privilege('authenticated', 'public.floor_planner_set_scan(uuid,uuid,text,uuid,jsonb)', 'EXECUTE') then
    raise exception 'Floor Planner scans: unsafe RPC grants';
  end if;
  return true;
end;
$$;
revoke all on function public.floor_planner_release_readiness() from public, anon, authenticated;
grant execute on function public.floor_planner_release_readiness() to service_role;
