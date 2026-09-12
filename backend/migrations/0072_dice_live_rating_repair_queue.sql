create table if not exists public.dice_live_rating_repairs (
  match_id uuid primary key references public.dice_live_matches(id) on delete cascade,
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.dice_live_rating_repairs enable row level security;
revoke all on table public.dice_live_rating_repairs from public, anon, authenticated;
grant select, insert, update, delete on table public.dice_live_rating_repairs to service_role;

create or replace function public.dice_live_track_rating_repair()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.source_live_match_id is not null then
      delete from public.dice_live_rating_repairs
      where match_id = old.source_live_match_id;
    end if;
    return old;
  end if;
  if new.source_live_match_id is null then
    return new;
  end if;
  if current_setting('dice.rating_mutation', true) = 'on' then
    delete from public.dice_live_rating_repairs
    where match_id = new.source_live_match_id;
  elsif current_setting('dice.live_materialization', true) = 'on' then
    if new.ranked and new.live_result_state in ('official', 'reopened') then
      insert into public.dice_live_rating_repairs (match_id)
      values (new.source_live_match_id)
      on conflict (match_id) do update set updated_at = now();
    else
      delete from public.dice_live_rating_repairs
      where match_id = new.source_live_match_id;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists dice_live_track_rating_repair on public.dice_games;
create trigger dice_live_track_rating_repair
after insert or update or delete
on public.dice_games
for each row execute function public.dice_live_track_rating_repair();

insert into public.dice_live_rating_repairs (match_id)
select live.id
from public.dice_live_matches live
join public.dice_games game on game.id = live.official_result_id
where live.deleted_at is null
  and game.ranked
  and game.live_result_state in ('official', 'reopened')
on conflict (match_id) do nothing;

revoke all on function public.dice_live_track_rating_repair()
  from public, anon, authenticated, service_role;

comment on table public.dice_live_rating_repairs
  is 'Durable work queue for ranked live results awaiting canonical rating replay.';
