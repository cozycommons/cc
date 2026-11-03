-- Serialize all ESPN approval gates for an account before checking overlaps.
-- Keep the lock and lookup separate: VOLATILE PL/pgSQL obtains a fresh snapshot
-- for the lookup after a waiting READ COMMITTED transaction acquires the lock.
-- No row locks in the lookup: another claimant may already hold its own row.
create function public.espn_write_claim_guard()
returns trigger
language plpgsql
security invoker
volatile
set search_path = ''
as $$
declare
  players bigint[];
begin
  if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'ESPN write claims require READ COMMITTED isolation';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'espn:write-claim:' || new.account_id::text, 0));

  if tg_table_name = 'espn_roster_edits' then
    players := pg_catalog.array_remove(array[new.add_player_id::bigint, new.drop_player_id::bigint], null);
  else
    select pg_catalog.array_agg(p.id::bigint) into players
    from pg_catalog.jsonb_array_elements_text(
      coalesce(new.give_player_ids, '[]'::jsonb) || coalesce(new.receive_player_ids, '[]'::jsonb)
    ) as p(id);
  end if;

  if exists (
    select 1 from public.espn_roster_edits e
    where e.account_id = new.account_id and e.league_id = new.league_id and e.season = new.season
      and e.status in ('executing', 'unknown', 'uncertain')
      and not (tg_table_name = 'espn_roster_edits' and e.id = new.id)
      and array[e.add_player_id::bigint, e.drop_player_id::bigint] && players
  ) or exists (
    select 1 from public.espn_trade_proposals t
    where t.account_id = new.account_id and t.league_id = new.league_id and t.season = new.season
      and t.status in ('executing', 'unknown', 'uncertain')
      and not (tg_table_name = 'espn_trade_proposals' and t.id = new.id)
      and array(
        select p.id::bigint from pg_catalog.jsonb_array_elements_text(
          coalesce(t.give_player_ids, '[]'::jsonb) || coalesce(t.receive_player_ids, '[]'::jsonb)
        ) as p(id)
      ) && players
  ) then
    -- UPDATE RETURNING yields no row, so the existing claim fails with HTTP 409.
    return null;
  end if;
  return new;
end;
$$;

revoke all on function public.espn_write_claim_guard() from public, anon, authenticated;
grant execute on function public.espn_write_claim_guard() to service_role;

create trigger espn_write_claim_guard
before update of status on public.espn_roster_edits
for each row when (new.status = 'executing' and old.status is distinct from 'executing')
execute function public.espn_write_claim_guard();

create trigger espn_write_claim_guard
before update of status on public.espn_trade_proposals
for each row when (new.status = 'executing' and old.status is distinct from 'executing')
execute function public.espn_write_claim_guard();
