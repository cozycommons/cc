-- Production Beli schema attestation. Keep this contract synchronized with
-- BELI_SCHEMA_CONTRACT_VERSION whenever a Beli migration is added.
do $$
declare
  object_name text;
  column_spec text;
begin
  foreach object_name in array array[
    'beli_accounts',
    'ig_sources',
    'ig_scan_jobs',
    'partiful_accounts',
    'resy_accounts',
    'espn_accounts',
    'espn_snapshots',
    'espn_public_predictions',
    'espn_team_claims',
    'espn_roster_edits',
    'espn_trade_proposals',
    'fantasy_leagues',
    'beli_agent_receipts'
  ] loop
    if to_regclass('public.' || object_name) is null then
      raise exception 'Beli schema contract: missing table public.%', object_name;
    end if;
  end loop;

  foreach column_spec in array array[
    'beli_accounts.beli_id_enc',
    'beli_accounts.password_enc',
    'beli_accounts.token_hash',
    'beli_accounts.watcher_opt_in',
    'beli_accounts.last_eats_scan',
    'beli_accounts.owner_user_id',
    'beli_agent_receipts.user_id',
    'beli_agent_receipts.idempotency_key',
    'beli_agent_receipts.payload',
    'beli_agent_receipts.result',
    'partiful_accounts.refresh_token_enc',
    'partiful_accounts.uid_enc',
    'partiful_accounts.token_hash',
    'resy_accounts.email_enc',
    'resy_accounts.password_enc',
    'resy_accounts.token_hash',
    'espn_accounts.espn_s2_enc',
    'espn_accounts.swid_enc',
    'espn_accounts.token_hash',
    'espn_public_predictions.id',
    'espn_public_predictions.matchup_id',
    'espn_public_predictions.generated_at',
    'espn_public_predictions.received_at',
    'espn_public_predictions.payload',
    'fantasy_leagues.season',
    'fantasy_leagues.espn_league_id',
    'fantasy_leagues.updated_at',
    'fantasy_leagues.updated_by',
    'espn_team_claims.id',
    'espn_team_claims.season',
    'espn_team_claims.team_id',
    'espn_team_claims.user_id',
    'espn_team_claims.created_at',
    'espn_roster_edits.id',
    'espn_roster_edits.account_id',
    'espn_roster_edits.league_id',
    'espn_roster_edits.season',
    'espn_roster_edits.team_id',
    'espn_roster_edits.add_player_id',
    'espn_roster_edits.drop_player_id',
    'espn_roster_edits.status',
    'espn_roster_edits.expires_at',
    'espn_roster_edits.executed_at',
    'espn_roster_edits.created_at',
    'espn_trade_proposals.id',
    'espn_trade_proposals.account_id',
    'espn_trade_proposals.league_id',
    'espn_trade_proposals.season',
    'espn_trade_proposals.team_id',
    'espn_trade_proposals.counterparty_team_id',
    'espn_trade_proposals.give_player_ids',
    'espn_trade_proposals.receive_player_ids',
    'espn_trade_proposals.status',
    'espn_trade_proposals.expires_at',
    'espn_trade_proposals.executed_at',
    'espn_trade_proposals.created_at',
    'ig_sources.handle',
    'ig_sources.last_seen_ts',
    'ig_scan_jobs.source_handle',
    'ig_scan_jobs.status',
    'ig_scan_jobs.scope',
    'ig_scan_jobs.digest'
  ] loop
    if to_regclass('public.' || split_part(column_spec, '.', 1)) is null then
      raise exception 'Beli schema contract: missing table for %', column_spec;
    end if;
    perform from information_schema.columns
      where table_schema = 'public'
        and table_name = split_part(column_spec, '.', 1)
        and column_name = split_part(column_spec, '.', 2);
    if not found then
      raise exception 'Beli schema contract: missing column %', column_spec;
    end if;
  end loop;
  if to_regprocedure('public.espn_claim_team(integer,integer,uuid)') is null then
    raise exception 'Beli schema contract: missing function public.espn_claim_team';
  end if;

  -- The invoker guard must see every competing row, including RLS-protected
  -- rows. Only the backend's BYPASSRLS role may claim writes through the API.
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'service_role' and rolbypassrls) then
    raise exception 'Beli schema contract: service_role must have BYPASSRLS';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_proc
    where oid = to_regprocedure('public.espn_write_claim_guard()')
      and not prosecdef and provolatile = 'v' and prorettype = 'pg_catalog.trigger'::regtype
      and proconfig @> array['search_path=""']
  ) then
    raise exception 'Beli schema contract: missing or unsafe public.espn_write_claim_guard';
  end if;
  if not pg_catalog.has_function_privilege('service_role', 'public.espn_write_claim_guard()', 'EXECUTE')
      or pg_catalog.has_function_privilege('anon', 'public.espn_write_claim_guard()', 'EXECUTE')
      or pg_catalog.has_function_privilege('authenticated', 'public.espn_write_claim_guard()', 'EXECUTE') then
    raise exception 'Beli schema contract: unsafe ESPN write guard function privileges';
  end if;
  foreach object_name in array array['espn_roster_edits', 'espn_trade_proposals'] loop
    if not exists (
      select 1 from pg_catalog.pg_trigger t
      join pg_catalog.pg_attribute a on a.attrelid = t.tgrelid and a.attname = 'status'
      where t.tgrelid = to_regclass('public.' || object_name)
        and t.tgname = 'espn_write_claim_guard' and not t.tgisinternal
        and t.tgenabled in ('O', 'A') and t.tgtype = 19
        and t.tgfoid = to_regprocedure('public.espn_write_claim_guard()')
        and t.tgattr::text = a.attnum::text
    ) then
      raise exception 'Beli schema contract: missing or disabled ESPN write claim trigger on %', object_name;
    end if;
    if not exists (select 1 from pg_catalog.pg_class
                   where oid = to_regclass('public.' || object_name) and relrowsecurity)
        or not pg_catalog.has_table_privilege('service_role', 'public.' || object_name, 'SELECT')
        or not pg_catalog.has_table_privilege('service_role', 'public.' || object_name, 'UPDATE')
        or pg_catalog.has_any_column_privilege('anon', 'public.' || object_name, 'UPDATE')
        or pg_catalog.has_any_column_privilege('authenticated', 'public.' || object_name, 'UPDATE') then
      raise exception 'Beli schema contract: unsafe ESPN write claim table privileges on %', object_name;
    end if;
  end loop;

  -- Connector account links and receipts are service-role only (0017).
  if not exists (
    select 1 from pg_catalog.pg_index i
    join pg_catalog.pg_attribute a on a.attrelid = i.indrelid and a.attnum = i.indkey[0]
    where i.indrelid = to_regclass('public.beli_accounts') and i.indisunique
      and i.indnatts = 1 and a.attname = 'owner_user_id' and i.indpred is not null
  ) then
    raise exception 'Beli schema contract: missing unique owner link index on beli_accounts';
  end if;
  foreach object_name in array array['beli_accounts', 'beli_agent_receipts'] loop
    if not exists (select 1 from pg_catalog.pg_class
                   where oid = to_regclass('public.' || object_name) and relrowsecurity)
        or pg_catalog.has_any_column_privilege('anon', 'public.' || object_name, 'SELECT,INSERT,UPDATE,REFERENCES')
        or pg_catalog.has_any_column_privilege('authenticated', 'public.' || object_name, 'SELECT,INSERT,UPDATE,REFERENCES')
        or pg_catalog.has_table_privilege('anon', 'public.' || object_name, 'DELETE,TRUNCATE,TRIGGER')
        or pg_catalog.has_table_privilege('authenticated', 'public.' || object_name, 'DELETE,TRUNCATE,TRIGGER') then
      raise exception 'Beli schema contract: unsafe browser access to public.%', object_name;
    end if;
  end loop;
  -- A privilege list means "any of", so check each grant on its own.
  foreach column_spec in array array[
    'beli_agent_receipts.SELECT', 'beli_agent_receipts.INSERT', 'beli_agent_receipts.UPDATE',
    'beli_agent_receipts.DELETE', 'beli_accounts.SELECT', 'beli_accounts.UPDATE'
  ] loop
    if not pg_catalog.has_table_privilege('service_role', 'public.' || split_part(column_spec, '.', 1),
                                          split_part(column_spec, '.', 2)) then
      raise exception 'Beli schema contract: connector service_role grants changed (%)', column_spec;
    end if;
  end loop;
  if not exists (
    select 1 from pg_catalog.pg_proc
    where oid = to_regprocedure('public.beli_link_account(uuid,uuid)')
      and not prosecdef and proconfig @> array['search_path=""']
  ) then
    raise exception 'Beli schema contract: missing or unsafe public.beli_link_account';
  end if;
  if not pg_catalog.has_function_privilege('service_role', 'public.beli_link_account(uuid,uuid)', 'EXECUTE')
      or pg_catalog.has_function_privilege('anon', 'public.beli_link_account(uuid,uuid)', 'EXECUTE')
      or pg_catalog.has_function_privilege('authenticated', 'public.beli_link_account(uuid,uuid)', 'EXECUTE') then
    raise exception 'Beli schema contract: unsafe beli_link_account privileges';
  end if;
end
$$;
