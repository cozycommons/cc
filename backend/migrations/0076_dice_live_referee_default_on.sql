-- Live referee is released by default. Existing rows remain explicit profile
-- overrides, so a stored false continues to opt that profile out.

alter table public.dice_feature_access
  alter column enabled set default true;
