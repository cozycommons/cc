-- Reconcile production environments whose attested 0042 baseline did not
-- actually contain the private live-referee feature access table.
create table if not exists public.dice_feature_access (
  user_id uuid not null references public.dice_profiles(user_id) on delete cascade,
  feature text not null,
  enabled boolean not null default false,
  primary key (user_id, feature)
);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.dice_feature_access'::regclass
      and conname = 'dice_feature_access_known_feature_check'
  ) then
    alter table public.dice_feature_access
      add constraint dice_feature_access_known_feature_check
      check (feature in ('dice_live_referee'));
  end if;
end
$$;

alter table public.dice_feature_access enable row level security;
revoke all on table public.dice_feature_access from public, anon, authenticated;
grant select, insert, update on table public.dice_feature_access to service_role;
