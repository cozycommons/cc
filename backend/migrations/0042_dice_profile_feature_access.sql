-- Private, per-profile access gates for unfinished Dice capabilities.
-- These gates control access only; they must never change how stored games or
-- event logs are interpreted.
create table public.dice_feature_access (
  user_id uuid not null references public.dice_profiles(user_id) on delete cascade,
  feature text not null,
  enabled boolean not null default false,
  primary key (user_id, feature),
  constraint dice_feature_access_known_feature_check
    check (feature in ('dice_live_referee'))
);

alter table public.dice_feature_access enable row level security;

revoke all on table public.dice_feature_access from anon, authenticated;
grant all on table public.dice_feature_access to service_role;
