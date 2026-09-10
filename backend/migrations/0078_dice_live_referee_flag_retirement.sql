-- The live referee rollout is complete. Normalize historical opt-outs and
-- prevent stale services or scripts from recreating the retired false state.

lock table public.dice_feature_access in share row exclusive mode;

update public.dice_feature_access
set enabled = true
where feature = 'dice_live_referee'
  and enabled is false;

alter table public.dice_feature_access
  alter column enabled set default true;

alter table public.dice_feature_access
  add constraint dice_feature_access_released_check check (enabled);
