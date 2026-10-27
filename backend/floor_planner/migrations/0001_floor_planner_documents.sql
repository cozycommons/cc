create table public.floor_plan_documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (length(btrim(title)) between 1 and 80),
  visibility text not null default 'private' check (visibility in ('private', 'public')),
  template_key text not null check (template_key in ('blank', 'apartment')),
  scene jsonb not null check (jsonb_typeof(scene) = 'object'),
  viewport jsonb not null default '{}'::jsonb check (jsonb_typeof(viewport) = 'object'),
  revision integer not null default 1 check (revision > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index floor_plan_documents_owner_updated
  on public.floor_plan_documents(owner_id, updated_at desc);
create index floor_plan_documents_public_updated
  on public.floor_plan_documents(updated_at desc)
  where visibility = 'public';

create table public.floor_plan_invitations (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.floor_plan_documents(id) on delete cascade,
  email text not null check (
    length(email) between 3 and 254
    and email = lower(btrim(email))
    and position('@' in email) between 2 and length(email) - 1
  ),
  accepted_user_id uuid references auth.users(id) on delete set null,
  invited_by uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  unique(document_id, email)
);

create index floor_plan_invitations_active_email
  on public.floor_plan_invitations(email, document_id)
  where revoked_at is null;
create index floor_plan_invitations_active_user
  on public.floor_plan_invitations(accepted_user_id, document_id)
  where revoked_at is null and accepted_user_id is not null;

alter table public.floor_plan_documents enable row level security;
alter table public.floor_plan_invitations enable row level security;

revoke all on public.floor_plan_documents from public, anon, authenticated;
revoke all on public.floor_plan_invitations from public, anon, authenticated;
grant select (id, title, visibility, template_key, scene, viewport, revision, updated_at)
  on public.floor_plan_documents to anon, authenticated;
grant select (document_id, accepted_user_id, revoked_at)
  on public.floor_plan_invitations to authenticated;
grant all on public.floor_plan_documents to service_role;
grant all on public.floor_plan_invitations to service_role;

create policy floor_plan_documents_public_read
  on public.floor_plan_documents for select to anon
  using (visibility = 'public');

create policy floor_plan_documents_member_read
  on public.floor_plan_documents for select to authenticated
  using (
    visibility = 'public'
    or owner_id = (select auth.uid())
    or exists (
      select 1 from public.floor_plan_invitations invitation
      where invitation.document_id = floor_plan_documents.id
        and invitation.accepted_user_id = (select auth.uid())
        and invitation.revoked_at is null
    )
  );

create policy floor_plan_invitations_self_read
  on public.floor_plan_invitations for select to authenticated
  using (accepted_user_id = (select auth.uid()));

create function public.floor_planner_update_document(
  p_document_id uuid,
  p_actor_id uuid,
  p_actor_email text,
  p_expected_revision integer,
  p_changes jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  current_document public.floor_plan_documents%rowtype;
  updated_document public.floor_plan_documents%rowtype;
  is_owner boolean;
  is_editor boolean;
begin
  select * into current_document
  from public.floor_plan_documents
  where id = p_document_id;

  if not found then
    return jsonb_build_object('status', 'missing');
  end if;

  is_owner := current_document.owner_id = p_actor_id;
  is_editor := is_owner or exists (
    select 1 from public.floor_plan_invitations invitation
    where invitation.document_id = p_document_id
      and invitation.revoked_at is null
      and (
        invitation.accepted_user_id = p_actor_id
        or invitation.email = lower(btrim(p_actor_email))
      )
  );

  if not is_editor then
    return jsonb_build_object('status', 'forbidden');
  end if;
  if (p_changes ? 'title' or p_changes ? 'visibility') and not is_owner then
    return jsonb_build_object('status', 'forbidden');
  end if;
  if current_document.revision <> p_expected_revision then
    return jsonb_build_object('status', 'conflict', 'revision', current_document.revision);
  end if;

  update public.floor_plan_documents document
  set title = coalesce(p_changes->>'title', document.title),
      visibility = coalesce(p_changes->>'visibility', document.visibility),
      scene = coalesce(p_changes->'scene', document.scene),
      viewport = coalesce(p_changes->'viewport', document.viewport),
      revision = document.revision + 1,
      updated_at = now()
  where document.id = p_document_id
    and document.revision = p_expected_revision
    and (
      document.owner_id = p_actor_id
      or exists (
        select 1 from public.floor_plan_invitations invitation
        where invitation.document_id = document.id
          and invitation.revoked_at is null
          and (
            invitation.accepted_user_id = p_actor_id
            or invitation.email = lower(btrim(p_actor_email))
          )
      )
    )
  returning document.* into updated_document;

  if not found then
    return jsonb_build_object('status', 'conflict');
  end if;

  return jsonb_build_object('status', 'saved', 'document', to_jsonb(updated_document));
end;
$$;

revoke all on function public.floor_planner_update_document(uuid, uuid, text, integer, jsonb)
  from public, anon, authenticated;
grant execute on function public.floor_planner_update_document(uuid, uuid, text, integer, jsonb)
  to service_role;

create function public.floor_planner_release_readiness()
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  role_name text;
  table_name text;
begin
  if not exists (select 1 from public.floor_planner_schema_migrations where version = 1) then
    raise exception 'Floor Planner schema contract: migration receipt missing';
  end if;

  foreach table_name in array array['floor_plan_documents', 'floor_plan_invitations'] loop
    if not exists (
      select 1 from pg_catalog.pg_class
      where oid = pg_catalog.to_regclass('public.' || table_name) and relrowsecurity
    ) then
      raise exception 'Floor Planner schema contract: % is missing or RLS is disabled', table_name;
    end if;
    foreach role_name in array array['anon', 'authenticated'] loop
      if pg_catalog.has_table_privilege(role_name, 'public.' || table_name, 'INSERT')
         or pg_catalog.has_table_privilege(role_name, 'public.' || table_name, 'UPDATE')
         or pg_catalog.has_table_privilege(role_name, 'public.' || table_name, 'DELETE')
         or pg_catalog.has_table_privilege(role_name, 'public.' || table_name, 'TRUNCATE') then
        raise exception 'Floor Planner schema contract: unsafe browser write grant on %', table_name;
      end if;
    end loop;
    if not pg_catalog.has_table_privilege('service_role', 'public.' || table_name, 'SELECT,INSERT,UPDATE,DELETE') then
      raise exception 'Floor Planner schema contract: service_role grants changed on %', table_name;
    end if;
  end loop;

  if not pg_catalog.has_column_privilege('anon', 'public.floor_plan_documents', 'id', 'SELECT')
     or not pg_catalog.has_column_privilege('authenticated', 'public.floor_plan_documents', 'scene', 'SELECT')
     or pg_catalog.has_any_column_privilege('anon', 'public.floor_plan_invitations', 'SELECT')
     or not pg_catalog.has_column_privilege('authenticated', 'public.floor_plan_invitations', 'document_id', 'SELECT')
     or pg_catalog.has_column_privilege('authenticated', 'public.floor_plan_invitations', 'email', 'SELECT') then
    raise exception 'Floor Planner schema contract: browser read grants changed';
  end if;

  if (select count(*) from pg_catalog.pg_policy where polrelid = 'public.floor_plan_documents'::regclass) <> 2
     or (select count(*) from pg_catalog.pg_policy where polrelid = 'public.floor_plan_invitations'::regclass) <> 1
     or not exists (select 1 from pg_catalog.pg_policy where polrelid = 'public.floor_plan_documents'::regclass and polname = 'floor_plan_documents_public_read')
     or not exists (select 1 from pg_catalog.pg_policy where polrelid = 'public.floor_plan_documents'::regclass and polname = 'floor_plan_documents_member_read')
     or not exists (select 1 from pg_catalog.pg_policy where polrelid = 'public.floor_plan_invitations'::regclass and polname = 'floor_plan_invitations_self_read') then
    raise exception 'Floor Planner schema contract: RLS policy set changed';
  end if;

  if not pg_catalog.has_function_privilege('service_role', 'public.floor_planner_update_document(uuid,uuid,text,integer,jsonb)', 'EXECUTE')
     or pg_catalog.has_function_privilege('anon', 'public.floor_planner_update_document(uuid,uuid,text,integer,jsonb)', 'EXECUTE')
     or pg_catalog.has_function_privilege('authenticated', 'public.floor_planner_update_document(uuid,uuid,text,integer,jsonb)', 'EXECUTE') then
    raise exception 'Floor Planner schema contract: update RPC grants changed';
  end if;

  return true;
end;
$$;

revoke all on function public.floor_planner_release_readiness() from public, anon, authenticated;
grant execute on function public.floor_planner_release_readiness() to service_role;
