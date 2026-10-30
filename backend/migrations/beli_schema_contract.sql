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
    'fantasy_leagues'
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
end
$$;
