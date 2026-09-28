-- Production Beli schema attestation. Keep this contract synchronized with
-- BELI_SCHEMA_CONTRACT_VERSION whenever a Beli migration is added.
do $$
declare
  object_name text;
  column_spec text;
begin
  foreach object_name in array array[
    'beli_accounts',
    'eats_scan_jobs',
    'partiful_accounts',
    'resy_accounts'
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
    'eats_scan_jobs.status',
    'eats_scan_jobs.scope',
    'eats_scan_jobs.digest'
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
end
$$;
