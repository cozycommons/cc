-- Make the Commons room a discrete 16 x 16 isometric tile world.
-- Existing screen-space positions are projected onto the nearest canonical tile.

do $$
declare
  current_state jsonb;
  next_objects jsonb;
  next_actors jsonb;
begin
  select state into current_state
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the tile world migration';
  end if;

  with pixels as (
    select key, value,
           coalesce((value->>'x')::numeric, 0.5) * 512 as pixel_x,
           coalesce((value->>'y')::numeric, 0.5) * 512 as pixel_y
      from jsonb_each(coalesce(current_state->'objects', '{}'::jsonb))
  ), continuous as (
    select key, value,
           (pixel_x - 256) / 16 as u,
           (pixel_y - 180) / 10 as v
      from pixels
  ), tiles as (
    select key, value,
           greatest(0, least(15, round((u + v) / 2)::int)) as tile_x,
           greatest(0, least(15, round((v - u) / 2)::int)) as tile_y
      from continuous
  )
  select coalesce(jsonb_object_agg(
    key,
    value || jsonb_build_object(
      'tile_x', tile_x,
      'tile_y', tile_y,
      'x', (256 + (tile_x - tile_y) * 16) / 512.0,
      'y', (180 + (tile_x + tile_y) * 10) / 512.0
    )
  ), '{}'::jsonb)
    into next_objects
    from tiles;

  with pixels as (
    select key, value,
           coalesce((value->>'x')::numeric, 0.5) * 512 as pixel_x,
           coalesce((value->>'y')::numeric, 0.5) * 512 as pixel_y
      from jsonb_each(coalesce(current_state->'actors', '{}'::jsonb))
  ), continuous as (
    select key, value,
           (pixel_x - 256) / 16 as u,
           (pixel_y - 180) / 10 as v
      from pixels
  ), tiles as (
    select key, value,
           greatest(0, least(15, round((u + v) / 2)::int)) as tile_x,
           greatest(0, least(15, round((v - u) / 2)::int)) as tile_y
      from continuous
  )
  select coalesce(jsonb_object_agg(
    key,
    value || jsonb_build_object(
      'tile_x', tile_x,
      'tile_y', tile_y,
      'x', (256 + (tile_x - tile_y) * 16) / 512.0,
      'y', (180 + (tile_x + tile_y) * 10) / 512.0
    )
  ), '{}'::jsonb)
    into next_actors
    from tiles;

  update public.commons_scenes
     set layout_version = 3,
         version = version + 1,
         state = jsonb_build_object(
           'schema_version', 2,
           'grid', jsonb_build_object(
             'columns', 16,
             'rows', 16,
             'tile_width', 32,
             'tile_height', 20,
             'origin_x', 256,
             'origin_y', 180
           ),
           'objects', next_objects,
           'actors', next_actors
         ),
         updated_at = pg_catalog.now()
   where id = 'commons-home';
end;
$$;
