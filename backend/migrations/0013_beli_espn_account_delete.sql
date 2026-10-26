-- ESPN Fantasy app: self-service account deletion (DELETE /espn/account).
-- Deleting the caller's espn_accounts row removes their stored cookies
-- and token; the account's history goes with it because espn_snapshots
-- (migration 0007) and espn_lineup_runs (migration 0008) both declare
-- account_id references espn_accounts(id) on delete cascade.
-- Migration 0006 granted service_role only select/insert/update on
-- espn_accounts, so the delete privilege is added here.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

grant delete on public.espn_accounts to service_role;
