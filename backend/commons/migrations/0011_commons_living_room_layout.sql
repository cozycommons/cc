-- Recompose the untouched evening seed into distinct living and dining zones.
-- Customized rooms keep their authored coordinates and ambient state.

do $$
declare
  current_state jsonb;
  next_state jsonb;
  next_objects jsonb;
  next_actors jsonb;
  ambient_score jsonb := '{
    "enabled":true,
    "revision":3,
    "epoch_ms":1800000000000,
    "cycle_ms":180000,
    "seed":42,
    "max_walkers":1,
    "actors":{
      "host":[
        {"kind":"hold","duration_ms":40000,"tile":[4,11],"facing":"front_right"},
        {"kind":"walk","waypoints":[[4,11],[5,11]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[5,11],"facing":"front_right"},
        {"kind":"walk","waypoints":[[5,11],[4,11]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":128000,"tile":[4,11],"facing":"front_right"}
      ],
      "maker":[
        {"kind":"hold","duration_ms":80000,"tile":[8,12],"facing":"front_left"},
        {"kind":"walk","waypoints":[[8,12],[7,12]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[7,12],"facing":"front_left"},
        {"kind":"walk","waypoints":[[7,12],[8,12]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":88000,"tile":[8,12],"facing":"front_left"}
      ],
      "neighbor":[
        {"kind":"hold","duration_ms":140000,"tile":[14,6],"facing":"back_right"},
        {"kind":"walk","waypoints":[[14,6],[14,7]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[14,7],"facing":"back_right"},
        {"kind":"walk","waypoints":[[14,7],[14,6]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":28000,"tile":[14,6],"facing":"back_right"}
      ]
    }
  }'::jsonb;
begin
  select state into current_state
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the living room layout migration';
  end if;

  -- Apply only to the exact seed produced by 0010. A moved object or actor is
  -- a customized room and must retain its user's composition.
  if coalesce((current_state->>'schema_version')::integer, 0) <> 7
     or current_state->>'catalog_version' <> 'commons-v2'
     or coalesce((current_state #>> '{ambient,revision}')::integer, 0) <> 2
     or (current_state #>> '{objects,orange-sofa,tile_x}')::integer <> 4
     or (current_state #>> '{objects,orange-sofa,tile_y}')::integer <> 9
     or (current_state #>> '{objects,green-loveseat,tile_x}')::integer <> 11
     or (current_state #>> '{objects,green-loveseat,tile_y}')::integer <> 6
     or (current_state #>> '{objects,dining-table,tile_x}')::integer <> 8
     or (current_state #>> '{objects,dining-table,tile_y}')::integer <> 11
     or (current_state #>> '{objects,dining-chair,tile_x}')::integer <> 7
     or (current_state #>> '{objects,dining-chair,tile_y}')::integer <> 10
     or (current_state #>> '{objects,dining-chair-right,tile_x}')::integer <> 9
     or (current_state #>> '{objects,dining-chair-right,tile_y}')::integer <> 10
     or (current_state #>> '{objects,record-console,tile_x}')::integer <> 3
     or (current_state #>> '{objects,record-console,tile_y}')::integer <> 7
     or (current_state #>> '{objects,coffee-table,tile_x}')::integer <> 6
     or (current_state #>> '{objects,coffee-table,tile_y}')::integer <> 10
     or (current_state #>> '{objects,floor-lamp,tile_x}')::integer <> 7
     or (current_state #>> '{objects,floor-lamp,tile_y}')::integer <> 9
     or (current_state #>> '{objects,area-rug,tile_x}')::integer <> 5
     or (current_state #>> '{objects,area-rug,tile_y}')::integer <> 9
     or (current_state #>> '{objects,topiary,tile_x}')::integer <> 2
     or (current_state #>> '{objects,topiary,tile_y}')::integer <> 5
     or (current_state #>> '{objects,palm,tile_x}')::integer <> 13
     or (current_state #>> '{objects,palm,tile_y}')::integer <> 5
     or (current_state #>> '{objects,red-armchair,visible}')::boolean is distinct from false
     or (current_state #>> '{objects,bar-stool,visible}')::boolean is distinct from false
     or (current_state #>> '{objects,record-console,state,playing}')::boolean is distinct from true
     or (current_state #>> '{objects,floor-lamp,state,on}')::boolean is distinct from true
     or (current_state #>> '{actors,host,tile_x}')::integer <> 5
     or (current_state #>> '{actors,host,tile_y}')::integer <> 8
     or (current_state #>> '{actors,maker,tile_x}')::integer <> 8
     or (current_state #>> '{actors,maker,tile_y}')::integer <> 10
     or (current_state #>> '{actors,neighbor,tile_x}')::integer <> 12
     or (current_state #>> '{actors,neighbor,tile_y}')::integer <> 5 then
    return;
  end if;

  next_objects := jsonb_build_object(
    'orange-sofa', (current_state #> '{objects,orange-sofa}') || jsonb_build_object(
      'tile_x', 3, 'tile_y', 8, 'x', (256 + (3 - 8) * 16) / 512.0, 'y', (180 + (3 + 8) * 10) / 512.0
    ),
    'green-loveseat', (current_state #> '{objects,green-loveseat}') || jsonb_build_object(
      'tile_x', 11, 'tile_y', 6, 'x', (256 + (11 - 6) * 16) / 512.0, 'y', (180 + (11 + 6) * 10) / 512.0
    ),
    'dining-table', (current_state #> '{objects,dining-table}') || jsonb_build_object(
      'tile_x', 12, 'tile_y', 9, 'x', (256 + (12 - 9) * 16) / 512.0, 'y', (180 + (12 + 9) * 10) / 512.0
    ),
    'dining-chair', (current_state #> '{objects,dining-chair}') || jsonb_build_object(
      'tile_x', 11, 'tile_y', 8, 'x', (256 + (11 - 8) * 16) / 512.0, 'y', (180 + (11 + 8) * 10) / 512.0
    ),
    'dining-chair-right', (current_state #> '{objects,dining-chair}') || jsonb_build_object(
      'id', 'dining-chair-right', 'tile_x', 13, 'tile_y', 10, 'x', (256 + (13 - 10) * 16) / 512.0, 'y', (180 + (13 + 10) * 10) / 512.0
    ),
    'record-console', (current_state #> '{objects,record-console}') || jsonb_build_object(
      'tile_x', 3, 'tile_y', 5, 'x', (256 + (3 - 5) * 16) / 512.0, 'y', (180 + (3 + 5) * 10) / 512.0
    ),
    'coffee-table', (current_state #> '{objects,coffee-table}') || jsonb_build_object(
      'tile_x', 7, 'tile_y', 10, 'x', (256 + (7 - 10) * 16) / 512.0, 'y', (180 + (7 + 10) * 10) / 512.0
    ),
    'floor-lamp', (current_state #> '{objects,floor-lamp}') || jsonb_build_object(
      'tile_x', 5, 'tile_y', 7, 'x', (256 + (5 - 7) * 16) / 512.0, 'y', (180 + (5 + 7) * 10) / 512.0
    ),
    'area-rug', (current_state #> '{objects,area-rug}') || jsonb_build_object(
      'tile_x', 5, 'tile_y', 9, 'x', (256 + (5 - 9) * 16) / 512.0, 'y', (180 + (5 + 9) * 10) / 512.0
    ),
    'topiary', (current_state #> '{objects,topiary}') || jsonb_build_object(
      'tile_x', 2, 'tile_y', 3, 'x', (256 + (2 - 3) * 16) / 512.0, 'y', (180 + (2 + 3) * 10) / 512.0
    ),
    'palm', (current_state #> '{objects,palm}') || jsonb_build_object(
      'tile_x', 14, 'tile_y', 5, 'x', (256 + (14 - 5) * 16) / 512.0, 'y', (180 + (14 + 5) * 10) / 512.0
    ),
    'red-armchair', (current_state #> '{objects,red-armchair}') || jsonb_build_object('visible', false, 'legacy_only', true),
    'bar-stool', (current_state #> '{objects,bar-stool}') || jsonb_build_object('visible', false, 'legacy_only', true)
  );

  next_actors := jsonb_build_object(
    'host', (current_state #> '{actors,host}') || jsonb_build_object(
      'tile_x', 4, 'tile_y', 11, 'x', (256 + (4 - 11) * 16) / 512.0, 'y', (180 + (4 + 11) * 10) / 512.0,
      'facing', 'south', 'view', 'front_right'
    ),
    'maker', (current_state #> '{actors,maker}') || jsonb_build_object(
      'tile_x', 8, 'tile_y', 12, 'x', (256 + (8 - 12) * 16) / 512.0, 'y', (180 + (8 + 12) * 10) / 512.0,
      'facing', 'east', 'view', 'front_left'
    ),
    'neighbor', (current_state #> '{actors,neighbor}') || jsonb_build_object(
      'tile_x', 14, 'tile_y', 6, 'x', (256 + (14 - 6) * 16) / 512.0, 'y', (180 + (14 + 6) * 10) / 512.0,
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
     set layout_version = 9,
         version = version + 1,
         state = next_state,
         updated_at = pg_catalog.now()
   where id = 'commons-home';
end;
$$;
