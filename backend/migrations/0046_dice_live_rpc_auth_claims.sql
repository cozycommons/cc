-- PostgREST exposes modern JWTs through request.jwt.claims. Keep the original
-- append transaction unchanged, but bridge its legacy defensive role check
-- only after independently verifying the signed request claim.
create or replace function public.dice_live_append_command(
  p_match_id uuid, p_recorded_by uuid, p_client_command_id text,
  p_expected_version integer, p_canonical_payload jsonb, p_events jsonb,
  p_projection jsonb, p_score smallint[], p_status text, p_detail_coverage text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_receipt jsonb;
  official jsonb;
  already_exists boolean;
begin
  if coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
    ''
  ) <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;

  -- 0043's private transactional implementation checks the legacy per-claim
  -- GUC. Normalize it only within this verified request transaction.
  perform set_config('request.jwt.claim.role', 'service_role', true);

  select true into already_exists from public.dice_live_commands
   where match_id = p_match_id and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  v_receipt := public.dice_live_append_command_v1(
    p_match_id, p_recorded_by, p_client_command_id, p_expected_version,
    p_canonical_payload, p_events, p_projection, p_score, p_status, p_detail_coverage);
  if already_exists then return v_receipt; end if;
  official := public.dice_live_materialize_result(p_match_id, p_projection, p_status);
  v_receipt := jsonb_set(v_receipt, '{official_result}', coalesce(official, 'null'::jsonb), true);
  update public.dice_live_commands set receipt = v_receipt
   where match_id = p_match_id and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  return v_receipt;
end;
$$;

revoke all on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) from public, anon, authenticated;
grant execute on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) to service_role;
