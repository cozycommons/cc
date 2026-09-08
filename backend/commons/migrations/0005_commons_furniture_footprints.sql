-- Persist the tiles occupied by furniture so clients cannot walk through a
-- large sprite simply because its anchor is one tile wide.

do $$
declare
  current_state jsonb;
  next_objects jsonb;
begin
  select state into current_state
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the footprint migration';
  end if;

  select coalesce(jsonb_object_agg(
    key,
    value || jsonb_build_object(
      'footprint',
      case value->>'asset'
        when 'orange-sofa' then '{"cells":[[-1,0],[0,0],[1,0]]}'::jsonb
        when 'green-loveseat' then '{"cells":[[0,0],[1,0]]}'::jsonb
        when 'dining-table' then '{"cells":[[-1,0],[0,0],[1,0]]}'::jsonb
        when 'record-console' then '{"cells":[[-1,0],[0,0],[1,0]]}'::jsonb
        when 'coffee-table' then '{"cells":[[-1,0],[0,0]]}'::jsonb
        when 'area-rug' then '{"cells":[[-1,-1],[0,-1],[1,-1],[-1,0],[0,0],[1,0]],"blocks_movement":false}'::jsonb
        else '{"cells":[[0,0]]}'::jsonb
      end
    )
  ), '{}'::jsonb)
    into next_objects
    from jsonb_each(coalesce(current_state->'objects', '{}'::jsonb));

  update public.commons_scenes
     set layout_version = 5,
         version = version + 1,
         state = jsonb_set(
           jsonb_set(current_state, '{schema_version}', '4'::jsonb, true),
           '{objects}',
           next_objects,
           true
         ),
         updated_at = pg_catalog.now()
   where id = 'commons-home';
end;
$$;
