-- Atomic ledger CAS + durable agent receipts. Browser roles cannot read or write receipts.
create table public.trips_agent_receipts (
  user_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 1 and 200),
  payload jsonb not null,
  result jsonb not null,
  created_at timestamptz not null default now(),
  primary key (user_id, idempotency_key)
);
alter table public.trips_agent_receipts enable row level security;
revoke all on public.trips_agent_receipts from public, anon, authenticated;
grant select, insert on public.trips_agent_receipts to service_role;

create function public.trips_agent_commit(
  p_user_id uuid, p_key text, p_payload jsonb, p_trip_id uuid,
  p_revision integer, p_after jsonb, p_result jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  receipt public.trips_agent_receipts;
  trip public.trips_groups;
begin
  -- Serialize even requests reusing a key across different trips.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_user_id::text || ':' || p_key, 0));
  select * into trip from public.trips_groups where id = p_trip_id for update;
  if not found or not (trip.member_user_ids @> array[p_user_id]) then
    return jsonb_build_object('error', 'membership');
  end if;
  select * into receipt from public.trips_agent_receipts
    where user_id = p_user_id and idempotency_key = p_key;
  if found then
    if receipt.payload <> p_payload then
      return jsonb_build_object('error', 'idempotency');
    end if;
    return jsonb_build_object('result', receipt.result);
  end if;
  if trip.revision <> p_revision then
    return jsonb_build_object('error', 'revision');
  end if;
  update public.trips_groups set data = p_after->'data',
    member_user_ids = array(select jsonb_array_elements_text(p_after->'member_user_ids')::uuid),
    revision = (p_after->>'revision')::integer, updated_at = (p_after->>'updated_at')::timestamptz
    where id = p_trip_id and revision = p_revision;
  insert into public.trips_agent_receipts(user_id, idempotency_key, payload, result)
    values (p_user_id, p_key, p_payload, p_result);
  return jsonb_build_object('result', p_result);
end;
$$;
revoke all on function public.trips_agent_commit(uuid,text,jsonb,uuid,integer,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.trips_agent_commit(uuid,text,jsonb,uuid,integer,jsonb,jsonb) to service_role;

create function public.trips_agent_readiness()
returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  if not exists (select 1 from public.trips_schema_migrations where version = 3)
     or not exists (select 1 from pg_catalog.pg_class
       where oid = pg_catalog.to_regclass('public.trips_agent_receipts') and relrowsecurity)
     or not pg_catalog.has_table_privilege('service_role', 'public.trips_agent_receipts', 'SELECT,INSERT')
     or pg_catalog.has_table_privilege('anon', 'public.trips_agent_receipts', 'SELECT,INSERT,UPDATE,DELETE')
     or pg_catalog.has_table_privilege('authenticated', 'public.trips_agent_receipts', 'SELECT,INSERT,UPDATE,DELETE')
     or not pg_catalog.has_function_privilege('service_role',
       'public.trips_agent_commit(uuid,text,jsonb,uuid,integer,jsonb,jsonb)', 'EXECUTE')
     or pg_catalog.has_function_privilege('anon',
       'public.trips_agent_commit(uuid,text,jsonb,uuid,integer,jsonb,jsonb)', 'EXECUTE')
     or pg_catalog.has_function_privilege('authenticated',
       'public.trips_agent_commit(uuid,text,jsonb,uuid,integer,jsonb,jsonb)', 'EXECUTE') then
    raise exception 'Trips agent schema contract: receipt storage or grants changed';
  end if;
  return true;
end;
$$;
revoke all on function public.trips_agent_readiness() from public, anon, authenticated;
grant execute on function public.trips_agent_readiness() to service_role;

-- Preserve the public readiness entry point while extending its attestation.
alter function public.trips_release_readiness() rename to trips_ledger_readiness;
create function public.trips_release_readiness()
returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  perform public.trips_ledger_readiness();
  perform public.trips_agent_readiness();
  return true;
end;
$$;
revoke all on function public.trips_release_readiness() from public, anon, authenticated;
grant execute on function public.trips_release_readiness() to service_role;
