-- Add the first authored ambient score without moving existing furniture or
-- changing the meaning of the existing command history.

do $$
declare
  current_state jsonb;
  next_state jsonb;
  host_appearance jsonb := '{
    "rig":"resident-v1","body":"body-default","skin":"skin-warm",
    "hair":"hair-host","outfit":"outfit-ochre","shoes":"shoes-boots",
    "accessory":"accessory-watch","recipe":"host-evening-v1"
  }'::jsonb;
  maker_appearance jsonb := '{
    "rig":"resident-v1","body":"body-default","skin":"skin-medium",
    "hair":"hair-maker","outfit":"outfit-blue","shoes":"shoes-boots",
    "accessory":"accessory-apron","recipe":"maker-evening-v1"
  }'::jsonb;
  neighbor_appearance jsonb := '{
    "rig":"resident-v1","body":"body-default","skin":"skin-deep",
    "hair":"hair-neighbor","outfit":"outfit-moss","shoes":"shoes-loafers",
    "accessory":"accessory-scarf","recipe":"neighbor-evening-v1"
  }'::jsonb;
  ambient_score jsonb := '{
    "enabled":true,
    "revision":1,
    "epoch_ms":1800000000000,
    "cycle_ms":180000,
    "seed":42,
    "max_walkers":1,
    "actors":{
      "host":[
        {"kind":"hold","duration_ms":58000,"tile":[7,5],"facing":"front_right"},
        {"kind":"walk","waypoints":[[7,5],[8,5]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[8,5],"facing":"front_right"},
        {"kind":"walk","waypoints":[[8,5],[7,5]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":110000,"tile":[7,5],"facing":"front_right"}
      ],
      "maker":[
        {"kind":"hold","duration_ms":60000,"tile":[4,7],"facing":"front_left"},
        {"kind":"walk","waypoints":[[4,7],[4,8]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[4,8],"facing":"front_left"},
        {"kind":"walk","waypoints":[[4,8],[4,7]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":108000,"tile":[4,7],"facing":"front_left"}
      ],
      "neighbor":[
        {"kind":"hold","duration_ms":120000,"tile":[11,4],"facing":"back_right"},
        {"kind":"walk","waypoints":[[11,4],[12,4]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":10000,"tile":[12,4],"facing":"back_right"},
        {"kind":"walk","waypoints":[[12,4],[11,4]],"edge_durations_ms":[1000]},
        {"kind":"hold","duration_ms":48000,"tile":[11,4],"facing":"back_right"}
      ]
    }
  }'::jsonb;
begin
  select state into current_state
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the ambient score migration';
  end if;

  next_state := current_state
    || jsonb_build_object(
      'schema_version', 7,
      'contract_version', 1,
      'catalog_version', 'commons-v2',
      'ambient', ambient_score
    );

  next_state := jsonb_set(
    next_state,
    '{actors,host,appearance}',
    host_appearance,
    true
  );
  next_state := jsonb_set(
    next_state,
    '{actors,maker,appearance}',
    maker_appearance,
    true
  );
  next_state := jsonb_set(
    next_state,
    '{actors,neighbor,appearance}',
    neighbor_appearance,
    true
  );

  update public.commons_scenes
     set version = version + 1,
         state = next_state,
         updated_at = pg_catalog.now()
   where id = 'commons-home'
     and coalesce((state->>'schema_version')::integer, 0) < 7;
end;
$$;
