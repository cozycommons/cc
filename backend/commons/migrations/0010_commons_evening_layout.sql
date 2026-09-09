-- Apply the selected evening composition only to the untouched schema-seven
-- seed. A room changed after 0009 keeps its coordinates and ambient state so
-- this migration never relocates a customized room.

do $$
declare
  current_state jsonb;
  next_state jsonb;
  next_objects jsonb;
  next_actors jsonb;
  ambient_score jsonb := '{
    "enabled":true,
    "revision":2,
    "epoch_ms":1800000000000,
    "cycle_ms":180000,
    "seed":42,
    "max_walkers":1,
    "actors":{
      "host":[
        {"kind":"hold","duration_ms":40000,"tile":[5,8],"facing":"front_right"},
        {"kind":"walk","waypoints":[[5,8],[6,8]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[6,8],"facing":"front_right"},
        {"kind":"walk","waypoints":[[6,8],[5,8]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":128000,"tile":[5,8],"facing":"front_right"}
      ],
      "maker":[
        {"kind":"hold","duration_ms":80000,"tile":[8,10],"facing":"front_left"},
        {"kind":"walk","waypoints":[[8,10],[8,9]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[8,9],"facing":"front_left"},
        {"kind":"walk","waypoints":[[8,9],[8,10]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":88000,"tile":[8,10],"facing":"front_left"}
      ],
      "neighbor":[
        {"kind":"hold","duration_ms":140000,"tile":[12,5],"facing":"back_right"},
        {"kind":"walk","waypoints":[[12,5],[12,4]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[12,4],"facing":"back_right"},
        {"kind":"walk","waypoints":[[12,4],[12,5]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":28000,"tile":[12,5],"facing":"back_right"}
      ]
    }
  }'::jsonb;
begin
  select state into current_state
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the evening layout migration';
  end if;

  if coalesce((current_state->>'schema_version')::integer, 0) <> 7
     or current_state->>'catalog_version' <> 'commons-v2'
     or coalesce((current_state #>> '{ambient,revision}')::integer, 0) <> 1 then
    return;
  end if;

  next_objects := jsonb_build_object(
    'orange-sofa', (current_state #> '{objects,orange-sofa}') || jsonb_build_object(
      'tile_x', 4, 'tile_y', 9, 'x', (256 + (4 - 9) * 16) / 512.0, 'y', (180 + (4 + 9) * 10) / 512.0
    ),
    'green-loveseat', (current_state #> '{objects,green-loveseat}') || jsonb_build_object(
      'tile_x', 11, 'tile_y', 6, 'x', (256 + (11 - 6) * 16) / 512.0, 'y', (180 + (11 + 6) * 10) / 512.0
    ),
    'dining-table', (current_state #> '{objects,dining-table}') || jsonb_build_object(
      'tile_x', 8, 'tile_y', 11, 'x', (256 + (8 - 11) * 16) / 512.0, 'y', (180 + (8 + 11) * 10) / 512.0
    ),
    'dining-chair', (current_state #> '{objects,dining-chair}') || jsonb_build_object(
      'tile_x', 7, 'tile_y', 10, 'x', (256 + (7 - 10) * 16) / 512.0, 'y', (180 + (7 + 10) * 10) / 512.0
    ),
    'dining-chair-right', (current_state #> '{objects,dining-chair}') || jsonb_build_object(
      'id', 'dining-chair-right', 'tile_x', 9, 'tile_y', 10, 'x', (256 + (9 - 10) * 16) / 512.0, 'y', (180 + (9 + 10) * 10) / 512.0
    ),
    'record-console', (current_state #> '{objects,record-console}') || jsonb_build_object(
      'tile_x', 3, 'tile_y', 7, 'x', (256 + (3 - 7) * 16) / 512.0, 'y', (180 + (3 + 7) * 10) / 512.0
    ),
    'coffee-table', (current_state #> '{objects,coffee-table}') || jsonb_build_object(
      'tile_x', 6, 'tile_y', 10, 'x', (256 + (6 - 10) * 16) / 512.0, 'y', (180 + (6 + 10) * 10) / 512.0
    ),
    'floor-lamp', (current_state #> '{objects,floor-lamp}') || jsonb_build_object(
      'tile_x', 7, 'tile_y', 9, 'x', (256 + (7 - 9) * 16) / 512.0, 'y', (180 + (7 + 9) * 10) / 512.0
    ),
    'area-rug', (current_state #> '{objects,area-rug}') || jsonb_build_object(
      'tile_x', 5, 'tile_y', 9, 'x', (256 + (5 - 9) * 16) / 512.0, 'y', (180 + (5 + 9) * 10) / 512.0
    ),
    'topiary', (current_state #> '{objects,topiary}') || jsonb_build_object(
      'tile_x', 2, 'tile_y', 5, 'x', (256 + (2 - 5) * 16) / 512.0, 'y', (180 + (2 + 5) * 10) / 512.0
    ),
    'palm', (current_state #> '{objects,palm}') || jsonb_build_object(
      'tile_x', 13, 'tile_y', 5, 'x', (256 + (13 - 5) * 16) / 512.0, 'y', (180 + (13 + 5) * 10) / 512.0
    ),
    'red-armchair', (current_state #> '{objects,red-armchair}') || jsonb_build_object('visible', false, 'legacy_only', true),
    'bar-stool', (current_state #> '{objects,bar-stool}') || jsonb_build_object('visible', false, 'legacy_only', true)
  );

  next_actors := jsonb_build_object(
    'host', (current_state #> '{actors,host}') || jsonb_build_object(
      'tile_x', 5, 'tile_y', 8, 'x', (256 + (5 - 8) * 16) / 512.0, 'y', (180 + (5 + 8) * 10) / 512.0,
      'facing', 'south', 'view', 'front_right'
    ),
    'maker', (current_state #> '{actors,maker}') || jsonb_build_object(
      'tile_x', 8, 'tile_y', 10, 'x', (256 + (8 - 10) * 16) / 512.0, 'y', (180 + (8 + 10) * 10) / 512.0,
      'facing', 'east', 'view', 'front_left'
    ),
    'neighbor', (current_state #> '{actors,neighbor}') || jsonb_build_object(
      'tile_x', 12, 'tile_y', 5, 'x', (256 + (12 - 5) * 16) / 512.0, 'y', (180 + (12 + 5) * 10) / 512.0,
      'facing', 'north', 'view', 'back_right'
    )
  );

  next_state := current_state
    || jsonb_build_object(
      'schema_version', 7,
      'contract_version', 1,
      'catalog_version', 'commons-v2',
      'objects', next_objects,
      'actors', next_actors,
      'ambient', ambient_score
    );

  update public.commons_scenes
     set layout_version = 8,
         version = version + 1,
         state = next_state,
         updated_at = pg_catalog.now()
   where id = 'commons-home';
end;
$$;
