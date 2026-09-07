-- Read the canonical source and persisted state from one PostgreSQL statement
-- snapshot. This makes ambiguous-transport reconciliation generation-safe.

create or replace function public.dice_rating_generation_snapshot()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  return jsonb_build_object(
    'source', public.dice_rating_source_snapshot(),
    'state', public.dice_rating_state_snapshot()
  );
end;
$$;

revoke all on function public.dice_rating_generation_snapshot() from public, anon, authenticated;
grant execute on function public.dice_rating_generation_snapshot() to service_role;
