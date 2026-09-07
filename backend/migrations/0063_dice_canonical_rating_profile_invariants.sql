-- Canonical profiles must already carry complete rating identity and confidence.
-- Never invent state here: an incomplete cutover must be repaired by exact replay.
do $$
begin
  if exists (
    select 1
    from public.dice_profiles
    where rating_deviation is null
       or rating_deviation not between 50 and 350
       or elo_model_version is distinct from '1.1.0'
  ) then
    raise exception using
      errcode = '55000',
      message = 'dice_rating.canonical_profile_state_required';
  end if;
end
$$;

alter table public.dice_profiles
  alter column rating_deviation set default 350,
  alter column rating_deviation set not null,
  alter column elo_model_version set default '1.1.0';

alter table public.dice_profiles
  drop constraint if exists dice_profiles_rating_deviation_check;
alter table public.dice_profiles
  add constraint dice_profiles_rating_deviation_check
  check (rating_deviation between 50 and 350);

alter table public.dice_profiles
  drop constraint if exists dice_profiles_canonical_model_version_check;
alter table public.dice_profiles
  add constraint dice_profiles_canonical_model_version_check
  check (elo_model_version = '1.1.0');

comment on column public.dice_profiles.rating_deviation is
  'Canonical rating uncertainty immediately after the player''s last ranked game.';
comment on column public.dice_profiles.elo_model_version is
  'Canonical rating-model semantic version.';
