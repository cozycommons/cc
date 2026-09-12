-- Replace the authored Commons seed with an original, orthographic cozy room.
-- Customized rooms keep their authored state and are not relocated.

do $$
declare
  current_state jsonb;
  current_layout integer;
  next_state jsonb;
  next_blocked jsonb;
begin
  select state, layout_version
    into current_state, current_layout
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the cozy room layout migration';
  end if;

  -- Commands do not change layout_version, so match the known 0011 seed as
  -- well as its schema/catalog and a representative set of authored anchors.
  if coalesce(current_layout, -1) <> 9
     or coalesce(current_state->>'schema_version', '') <> '7'
     or coalesce(current_state->>'catalog_version', '') <> 'commons-v2'
     or coalesce(current_state #>> '{objects,orange-sofa,tile_x}', '') <> '3'
     or coalesce(current_state #>> '{objects,orange-sofa,tile_y}', '') <> '8'
     or coalesce(current_state #>> '{objects,green-loveseat,tile_x}', '') <> '11'
     or coalesce(current_state #>> '{objects,green-loveseat,tile_y}', '') <> '6'
     or coalesce(current_state #>> '{actors,host,tile_x}', '') <> '4'
     or coalesce(current_state #>> '{actors,host,tile_y}', '') <> '11'
     or coalesce(current_state #>> '{actors,maker,tile_x}', '') <> '8'
     or coalesce(current_state #>> '{actors,maker,tile_y}', '') <> '12'
     or coalesce(current_state #>> '{actors,neighbor,tile_x}', '') <> '14'
     or coalesce(current_state #>> '{actors,neighbor,tile_y}', '') <> '6' then
    return;
  end if;

  select jsonb_agg(jsonb_build_array(tile_x, tile_y) order by tile_y, tile_x)
    into next_blocked
    from (
      select x as tile_x, 0 as tile_y from generate_series(0, 15) as x
      union
      select x as tile_x, 15 as tile_y from generate_series(0, 15) as x where x not in (7, 8)
      union
      select 0 as tile_x, y as tile_y from generate_series(1, 14) as y
      union
      select 15 as tile_x, y as tile_y from generate_series(1, 14) as y
    ) as boundary;

  next_state := current_state
    || jsonb_build_object(
      'schema_version', 8,
      'contract_version', 1,
      'catalog_version', 'commons-room-v1',
      'grid', jsonb_build_object('blocked', next_blocked),
      'objects', jsonb_build_object(
        'bed', jsonb_build_object(
          'id', 'bed', 'kind', 'furniture', 'asset', 'cozy-bed',
          'tile_x', 2, 'tile_y', 3,
          'x', (16 + 2 * 32) / 512.0, 'y', (16 + 3 * 32) / 512.0,
          'orientation', 'south', 'movable', true, 'visible', true
        ),
        'work-table', jsonb_build_object(
          'id', 'work-table', 'kind', 'furniture', 'asset', 'cozy-table',
          'tile_x', 8, 'tile_y', 4,
          'x', (16 + 8 * 32) / 512.0, 'y', (16 + 4 * 32) / 512.0,
          'orientation', 'south', 'movable', true, 'visible', true
        ),
        'chair', jsonb_build_object(
          'id', 'chair', 'kind', 'furniture', 'asset', 'cozy-chair',
          'tile_x', 9, 'tile_y', 6,
          'x', (16 + 9 * 32) / 512.0, 'y', (16 + 6 * 32) / 512.0,
          'orientation', 'south', 'movable', true, 'visible', true
        ),
        'bookcase', jsonb_build_object(
          'id', 'bookcase', 'kind', 'furniture', 'asset', 'cozy-bookcase',
          'tile_x', 12, 'tile_y', 2,
          'x', (16 + 12 * 32) / 512.0, 'y', (16 + 2 * 32) / 512.0,
          'orientation', 'south', 'movable', false, 'visible', true
        ),
        'fireplace', jsonb_build_object(
          'id', 'fireplace', 'kind', 'furniture', 'asset', 'cozy-fireplace',
          'tile_x', 7, 'tile_y', 1,
          'x', (16 + 7 * 32) / 512.0, 'y', (16 + 1 * 32) / 512.0,
          'orientation', 'south', 'movable', false, 'visible', true,
          'state', jsonb_build_object('on', true)
        ),
        'chest', jsonb_build_object(
          'id', 'chest', 'kind', 'furniture', 'asset', 'cozy-chest',
          'tile_x', 2, 'tile_y', 11,
          'x', (16 + 2 * 32) / 512.0, 'y', (16 + 11 * 32) / 512.0,
          'orientation', 'south', 'movable', true, 'visible', true
        ),
        'plant', jsonb_build_object(
          'id', 'plant', 'kind', 'decoration', 'asset', 'cozy-plant',
          'tile_x', 13, 'tile_y', 11,
          'x', (16 + 13 * 32) / 512.0, 'y', (16 + 11 * 32) / 512.0,
          'orientation', 'south', 'movable', true, 'visible', true
        )
      ),
      'actors', jsonb_build_object(
        'host', jsonb_build_object(
          'id', 'host', 'kind', 'actor', 'asset', 'host',
          'tile_x', 7, 'tile_y', 12,
          'x', (16 + 7 * 32) / 512.0, 'y', (16 + 12 * 32) / 512.0,
          'facing', 'south', 'view', 'front'
        ),
        'maker', jsonb_build_object(
          'id', 'maker', 'kind', 'actor', 'asset', 'maker',
          'tile_x', 5, 'tile_y', 8,
          'x', (16 + 5 * 32) / 512.0, 'y', (16 + 8 * 32) / 512.0,
          'facing', 'east', 'view', 'right'
        ),
        'neighbor', jsonb_build_object(
          'id', 'neighbor', 'kind', 'actor', 'asset', 'neighbor',
          'tile_x', 10, 'tile_y', 10,
          'x', (16 + 10 * 32) / 512.0, 'y', (16 + 10 * 32) / 512.0,
          'facing', 'north', 'view', 'back'
        )
      ),
      'ambient', jsonb_build_object('enabled', false, 'revision', 4, 'reason', 'resting_only')
    );

  update public.commons_scenes
     set layout_version = 10,
         version = version + 1,
         state = next_state,
         updated_at = pg_catalog.now()
   where id = 'commons-home';
end;
$$;
