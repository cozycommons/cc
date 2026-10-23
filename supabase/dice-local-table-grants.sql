-- Local Supabase uses explicit grants while the production project predates
-- that default. Grant only the backend service role access to Dice relations;
-- do not broaden browser roles or unrelated application tables.
grant usage on schema public to service_role;
grant all on table
  public.dice_profiles,
  public.dice_games,
  public.dice_game_players,
  public.dice_game_comments,
  public.dice_tournaments,
  public.dice_tournament_enrollments,
  public.dice_feature_access
to service_role;
