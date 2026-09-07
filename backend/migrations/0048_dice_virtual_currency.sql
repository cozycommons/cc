-- Virtual Dice V2 foundation: private, tournament-scoped sportsbook ledger.
-- All mutations run through service-role-only RPCs. Ledger rows and locked
-- pick terms are immutable; corrections append compensating entries.

create table public.dice_virtual_markets (
  id bigint generated always as identity primary key,
  tournament_id uuid not null references public.dice_tournaments(id) on delete cascade,
  live_match_id uuid not null references public.dice_live_matches(id) on delete cascade,
  kind text not null default 'match_winner',
  status text not null default 'open',
  model_id text not null,
  model_version text not null,
  match_version integer not null,
  selections jsonb not null,
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  settled_selection text,
  settlement_revision integer not null default 0,
  constraint dice_virtual_markets_kind_check check (kind = 'match_winner'),
  constraint dice_virtual_markets_status_check check (status in ('open', 'closed', 'settled')),
  constraint dice_virtual_markets_version_check check (match_version >= 0),
  constraint dice_virtual_markets_selections_check check (
    jsonb_typeof(selections) = 'object'
    and jsonb_array_length(jsonb_path_query_array(selections, '$.keyvalue()')) = 2
  ),
  unique (live_match_id, kind)
);
create index dice_virtual_markets_tournament_idx
  on public.dice_virtual_markets (tournament_id, status, created_at desc);

create table public.dice_virtual_picks (
  id bigint generated always as identity primary key,
  tournament_id uuid not null references public.dice_tournaments(id) on delete cascade,
  market_id bigint not null references public.dice_virtual_markets(id) on delete restrict,
  user_id uuid not null references public.dice_profiles(user_id) on delete restrict,
  client_pick_id text not null,
  selection text not null,
  stake integer not null check (stake > 0),
  potential_return integer not null check (potential_return >= stake),
  locked_probability_millionths integer not null check (locked_probability_millionths between 1 and 999999),
  quote_model_id text not null,
  quote_model_version text not null,
  quote_match_version integer not null check (quote_match_version >= 0),
  status text not null default 'open',
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  constraint dice_virtual_picks_status_check check (status in ('open', 'won', 'lost', 'void')),
  unique (tournament_id, user_id, client_pick_id),
  unique (id, tournament_id)
);
create index dice_virtual_picks_market_idx on public.dice_virtual_picks (market_id, status);
create index dice_virtual_picks_user_idx on public.dice_virtual_picks (tournament_id, user_id, created_at desc);

create table public.dice_virtual_ledger (
  id bigint generated always as identity primary key,
  tournament_id uuid not null references public.dice_tournaments(id) on delete cascade,
  user_id uuid not null references public.dice_profiles(user_id) on delete restrict,
  pick_id bigint,
  kind text not null,
  amount integer not null check (amount <> 0),
  operation_key text not null,
  created_at timestamptz not null default now(),
  constraint dice_virtual_ledger_kind_check check (
    kind in ('opening_grant', 'stake_debit', 'payout_credit', 'refund_credit', 'settlement_reversal', 'adjustment')
  ),
  constraint dice_virtual_ledger_pick_fk foreign key (pick_id, tournament_id)
    references public.dice_virtual_picks(id, tournament_id) on delete restrict,
  unique (tournament_id, user_id, operation_key)
);
create index dice_virtual_ledger_balance_idx on public.dice_virtual_ledger (tournament_id, user_id);
create index dice_virtual_ledger_pick_idx on public.dice_virtual_ledger (pick_id) where pick_id is not null;

alter table public.dice_virtual_markets enable row level security;
alter table public.dice_virtual_picks enable row level security;
alter table public.dice_virtual_ledger enable row level security;
revoke all on table public.dice_virtual_markets, public.dice_virtual_picks,
  public.dice_virtual_ledger from public, anon, authenticated;
grant all on table public.dice_virtual_markets, public.dice_virtual_picks,
  public.dice_virtual_ledger to service_role;
grant usage, select on sequence public.dice_virtual_markets_id_seq,
  public.dice_virtual_picks_id_seq, public.dice_virtual_ledger_id_seq to service_role;

create or replace function public.dice_virtual_immutable_guard()
returns trigger language plpgsql set search_path = public
as $$
begin
  raise exception using errcode = '55000', message = 'dice_virtual.ledger_append_only';
end;
$$;
create trigger dice_virtual_ledger_no_update
before update or delete on public.dice_virtual_ledger
for each row execute function public.dice_virtual_immutable_guard();

create or replace function public.dice_virtual_locked_terms_guard()
returns trigger language plpgsql set search_path = public
as $$
begin
  if new.tournament_id <> old.tournament_id or new.market_id <> old.market_id
     or new.user_id <> old.user_id or new.client_pick_id <> old.client_pick_id
     or new.selection <> old.selection or new.stake <> old.stake
     or new.potential_return <> old.potential_return
     or new.locked_probability_millionths <> old.locked_probability_millionths
     or new.quote_model_id <> old.quote_model_id
     or new.quote_model_version <> old.quote_model_version
     or new.quote_match_version <> old.quote_match_version then
    raise exception using errcode = '55000', message = 'dice_virtual.quote_terms_immutable';
  end if;
  return new;
end;
$$;
create trigger dice_virtual_picks_locked_terms
before update on public.dice_virtual_picks
for each row execute function public.dice_virtual_locked_terms_guard();
revoke all on function public.dice_virtual_immutable_guard(),
  public.dice_virtual_locked_terms_guard() from public, anon, authenticated;

create or replace function public.dice_virtual_place_pick(
  p_tournament_id uuid, p_market_id bigint, p_user_id uuid,
  p_client_pick_id text, p_selection text, p_stake integer
) returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
  m public.dice_virtual_markets%rowtype;
  existing public.dice_virtual_picks%rowtype;
  probability integer;
  return_amount integer;
  balance integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_virtual.service_role_required';
  end if;
  if p_stake <= 0 then
    raise exception using errcode = '22023', message = 'dice_virtual.invalid_stake';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_tournament_id::text || ':' || p_user_id::text, 0));
  select * into existing from public.dice_virtual_picks
   where tournament_id = p_tournament_id and user_id = p_user_id and client_pick_id = p_client_pick_id;
  if found then
    if existing.market_id = p_market_id and existing.selection = p_selection and existing.stake = p_stake then
      return to_jsonb(existing);
    end if;
    raise exception using errcode = 'P0001', message = 'dice_virtual.pick_id_conflict';
  end if;
  select * into m from public.dice_virtual_markets where id = p_market_id and tournament_id = p_tournament_id for update;
  if not found then raise exception using errcode = 'P0001', message = 'dice_virtual.market_not_found'; end if;
  if m.status <> 'open' then raise exception using errcode = 'P0001', message = 'dice_virtual.market_closed'; end if;
  probability := (m.selections->p_selection->>'probability_millionths')::integer;
  if probability is null or probability not between 1 and 999999 then
    raise exception using errcode = '22023', message = 'dice_virtual.invalid_selection';
  end if;
  select coalesce(sum(amount), 0) into balance from public.dice_virtual_ledger
   where tournament_id = p_tournament_id and user_id = p_user_id;
  if balance < p_stake then raise exception using errcode = 'P0001', message = 'dice_virtual.insufficient_balance'; end if;
  return_amount := floor((p_stake::numeric * 1000000) / probability)::integer;
  insert into public.dice_virtual_picks (
    tournament_id, market_id, user_id, client_pick_id, selection, stake,
    potential_return, locked_probability_millionths, quote_model_id,
    quote_model_version, quote_match_version
  ) values (
    p_tournament_id, p_market_id, p_user_id, p_client_pick_id, p_selection, p_stake,
    return_amount, probability, m.model_id, m.model_version, m.match_version
  ) returning * into existing;
  insert into public.dice_virtual_ledger (tournament_id, user_id, pick_id, kind, amount, operation_key)
    values (p_tournament_id, p_user_id, existing.id, 'stake_debit', -p_stake, 'pick:' || existing.id || ':stake');
  return to_jsonb(existing);
end;
$$;

revoke all on function public.dice_virtual_place_pick(uuid, bigint, uuid, text, text, integer)
  from public, anon, authenticated;
grant execute on function public.dice_virtual_place_pick(uuid, bigint, uuid, text, text, integer)
  to service_role;

create or replace function public.dice_virtual_open_bankroll(
  p_tournament_id uuid, p_user_id uuid, p_amount integer default 1000
) returns integer
language plpgsql security definer set search_path = public
as $$
declare balance integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_virtual.service_role_required';
  end if;
  if p_amount <= 0 then raise exception using errcode = '22023', message = 'dice_virtual.invalid_grant'; end if;
  if not exists (select 1 from public.dice_tournament_enrollments where tournament_id = p_tournament_id and user_id = p_user_id) then
    raise exception using errcode = '42501', message = 'dice_virtual.not_enrolled';
  end if;
  insert into public.dice_virtual_ledger (tournament_id, user_id, kind, amount, operation_key)
    values (p_tournament_id, p_user_id, 'opening_grant', p_amount, 'opening_grant')
    on conflict (tournament_id, user_id, operation_key) do nothing;
  select coalesce(sum(amount), 0)::integer into balance from public.dice_virtual_ledger
   where tournament_id = p_tournament_id and user_id = p_user_id;
  return balance;
end;
$$;

create or replace function public.dice_virtual_settle_market(
  p_market_id bigint, p_winner_selection text
) returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
  m public.dice_virtual_markets%rowtype;
  p public.dice_virtual_picks%rowtype;
  prior_credit integer;
  credit integer;
  revision integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_virtual.service_role_required';
  end if;
  select * into m from public.dice_virtual_markets where id = p_market_id for update;
  if not found then raise exception using errcode = 'P0001', message = 'dice_virtual.market_not_found'; end if;
  if m.status = 'settled' and m.settled_selection is not distinct from p_winner_selection then
    return jsonb_build_object('market_id', m.id, 'settlement_revision', m.settlement_revision);
  end if;
  if p_winner_selection is not null and not (m.selections ? p_winner_selection) then
    raise exception using errcode = '22023', message = 'dice_virtual.invalid_selection';
  end if;
  revision := m.settlement_revision + 1;
  for p in select * from public.dice_virtual_picks where market_id = m.id for update loop
    select coalesce(sum(amount), 0)::integer into prior_credit
      from public.dice_virtual_ledger where pick_id = p.id and kind in ('payout_credit', 'refund_credit', 'settlement_reversal');
    if prior_credit <> 0 then
      insert into public.dice_virtual_ledger (tournament_id, user_id, pick_id, kind, amount, operation_key)
        values (p.tournament_id, p.user_id, p.id, 'settlement_reversal', -prior_credit,
          'pick:' || p.id || ':settlement:' || revision || ':reversal');
    end if;
    credit := case when p_winner_selection is null then p.stake when p.selection = p_winner_selection then p.potential_return else 0 end;
    if credit > 0 then
      insert into public.dice_virtual_ledger (tournament_id, user_id, pick_id, kind, amount, operation_key)
        values (p.tournament_id, p.user_id, p.id,
          case when p_winner_selection is null then 'refund_credit' else 'payout_credit' end,
          credit, 'pick:' || p.id || ':settlement:' || revision || ':credit');
    end if;
    update public.dice_virtual_picks set
      status = case when p_winner_selection is null then 'void' when p.selection = p_winner_selection then 'won' else 'lost' end,
      settled_at = now() where id = p.id;
  end loop;
  update public.dice_virtual_markets set status = 'settled', settled_at = now(),
    settled_selection = p_winner_selection, settlement_revision = revision where id = m.id;
  return jsonb_build_object('market_id', m.id, 'settlement_revision', revision, 'winner_selection', p_winner_selection);
end;
$$;

revoke all on function public.dice_virtual_open_bankroll(uuid, uuid, integer),
  public.dice_virtual_settle_market(bigint, text) from public, anon, authenticated;
grant execute on function public.dice_virtual_open_bankroll(uuid, uuid, integer),
  public.dice_virtual_settle_market(bigint, text) to service_role;
