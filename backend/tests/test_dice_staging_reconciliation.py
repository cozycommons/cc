"""Real-database proofs for the staged schema repair; all mutations roll back."""
import os
from pathlib import Path
import subprocess
import pytest
from tests.dice_test_database import is_isolated_dice_test_database

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not is_isolated_dice_test_database(os.environ), reason="isolated database required")

def test_reconciliation_repairs_copied_ledger_drift_without_changing_rows():
    repair = ROOT / "backend/migrations/0079_dice_staging_schema_reconciliation.sql"
    contract = ROOT / "backend/migrations/dice_schema_contract.sql"
    sql = f"""
begin;
create temp table before_rows as
select 'profiles' as name, jsonb_agg(to_jsonb(t) order by user_id) as rows from dice_profiles t
union all select 'games', jsonb_agg(to_jsonb(t) order by id) from dice_games t
union all select 'players', jsonb_agg(to_jsonb(t) order by id) from dice_game_players t
union all select 'commands', jsonb_agg(to_jsonb(t) order by id) from dice_live_commands t
union all select 'events', jsonb_agg(to_jsonb(t) order by id) from dice_live_events t;
drop index dice_games_duo_replay_idx;
drop index dice_game_players_duo_replay_idx;
drop trigger dice_live_sync_ranked_from_result on dice_games;
drop trigger dice_live_track_rating_repair on dice_games;
drop trigger dice_game_reject_stale_update on dice_games;
drop function public.dice_live_sync_ranked_from_result();
drop function public.dice_live_track_rating_repair();
drop function public.dice_game_reject_stale_update();
alter table dice_feature_access drop constraint dice_feature_access_released_check;
alter table dice_feature_access alter column enabled set default false;
drop policy dice_games_public_read on dice_games;
create policy dice_games_public_read on dice_games for select to anon,authenticated using (true);
\\i {repair}
\\i {repair}
\\i {contract}
do $$ begin
if (select count(*) from pg_trigger where not tgisinternal and tgname in ('dice_live_sync_ranked_from_result','dice_live_track_rating_repair','dice_game_reject_stale_update')) <> 3 then
 raise exception 'missing repaired triggers';
end if;
if exists(
 select * from before_rows
 except
 (select 'profiles',jsonb_agg(to_jsonb(t) order by user_id) from dice_profiles t
 union all select 'games',jsonb_agg(to_jsonb(t) order by id) from dice_games t
 union all select 'players',jsonb_agg(to_jsonb(t) order by id) from dice_game_players t
 union all select 'commands',jsonb_agg(to_jsonb(t) order by id) from dice_live_commands t
 union all select 'events',jsonb_agg(to_jsonb(t) order by id) from dice_live_events t)
) then raise exception 'reconciliation changed source rows'; end if;
end $$;
rollback;
"""
    result = subprocess.run(["psql",os.environ["DB_URL"],"-X","-v","ON_ERROR_STOP=1"],input=sql,text=True,capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
