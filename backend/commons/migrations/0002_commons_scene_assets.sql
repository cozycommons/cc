-- Promote the original room state into the first game-ready art layout.
-- Preserve the positions and interactive state that existed in 0001.

do $$
declare
  current_state jsonb;
begin
  select state into current_state
    from public.commons_scenes
   where id = 'commons-home'
   for update;

  if current_state is null then
    raise exception 'Commons scene commons-home must exist before the art layout migration';
  end if;

  update public.commons_scenes
     set layout_version = 2,
         version = version + 1,
         state = jsonb_build_object(
           'schema_version', 1,
           'objects', jsonb_build_object(
             'orange-sofa', jsonb_build_object(
               'id', 'orange-sofa', 'label', 'orange sofa', 'asset', 'orange-sofa',
               'kind', 'furniture', 'x', 0.555, 'y', 0.505, 'movable', true,
               'state', '{}'::jsonb
             ),
             'green-loveseat', jsonb_build_object(
               'id', 'green-loveseat', 'label', 'green loveseat', 'asset', 'green-loveseat',
               'kind', 'furniture', 'x', 0.735, 'y', 0.745, 'movable', true,
               'state', '{}'::jsonb
             ),
             'red-armchair', jsonb_build_object(
               'id', 'red-armchair', 'label', 'red armchair', 'asset', 'red-armchair',
               'kind', 'furniture', 'x', 0.835, 'y', 0.815, 'movable', true,
               'state', '{}'::jsonb
             ),
             'dining-table', jsonb_build_object(
               'id', 'dining-table', 'label', 'dining table', 'asset', 'dining-table',
               'kind', 'furniture', 'x', 0.405, 'y', 0.735, 'movable', true,
               'state', '{}'::jsonb
             ),
             'dining-chair', jsonb_build_object(
               'id', 'dining-chair', 'label', 'dining chair', 'asset', 'dining-chair',
               'kind', 'furniture', 'x', 0.305, 'y', 0.805, 'movable', true,
               'state', '{}'::jsonb
             ),
             'record-console', jsonb_build_object(
               'id', 'record-console', 'label', 'record console', 'asset', 'record-console',
               'kind', 'furniture',
               'x', coalesce(current_state #> '{objects,record-console,x}', current_state #> '{objects,record-player,x}', to_jsonb(0.275::numeric)),
               'y', coalesce(current_state #> '{objects,record-console,y}', current_state #> '{objects,record-player,y}', to_jsonb(0.495::numeric)),
               'movable', true,
               'state', jsonb_build_object(
                 'playing', coalesce(current_state #> '{objects,record-console,state,playing}', current_state #> '{objects,record-player,state,playing}', 'false'::jsonb)
               )
             ),
             'coffee-table', jsonb_build_object(
               'id', 'coffee-table', 'label', 'coffee table', 'asset', 'coffee-table',
               'kind', 'furniture', 'x', 0.535, 'y', 0.605, 'movable', true,
               'state', '{}'::jsonb
             ),
             'floor-lamp', jsonb_build_object(
               'id', 'floor-lamp', 'label', 'floor lamp', 'asset', 'floor-lamp',
               'kind', 'prop',
               'x', coalesce(current_state #> '{objects,floor-lamp,x}', to_jsonb(0.545::numeric)),
               'y', coalesce(current_state #> '{objects,floor-lamp,y}', to_jsonb(0.855::numeric)),
               'movable', true,
               'state', jsonb_build_object(
                 'on', coalesce(current_state #> '{objects,floor-lamp,state,on}', 'true'::jsonb)
               )
             ),
             'area-rug', jsonb_build_object(
               'id', 'area-rug', 'label', 'area rug', 'asset', 'area-rug',
               'kind', 'furniture', 'x', 0.535, 'y', 0.64, 'movable', true,
               'state', '{}'::jsonb
             ),
             'topiary', jsonb_build_object(
               'id', 'topiary', 'label', 'topiary plant', 'asset', 'topiary',
               'kind', 'prop', 'x', 0.14, 'y', 0.61, 'movable', true,
               'state', '{}'::jsonb
             ),
             'palm', jsonb_build_object(
               'id', 'palm', 'label', 'palm plant', 'asset', 'palm',
               'kind', 'prop', 'x', 0.805, 'y', 0.825, 'movable', true,
               'state', '{}'::jsonb
             ),
             'bar-stool', jsonb_build_object(
               'id', 'bar-stool', 'label', 'bar stool', 'asset', 'bar-stool',
               'kind', 'furniture', 'x', 0.79, 'y', 0.56, 'movable', true,
               'state', '{}'::jsonb
             )
           ),
           'actors', jsonb_build_object(
             'host', jsonb_build_object(
               'id', 'host', 'kind', 'actor', 'label', 'Commons host', 'asset', 'host',
               'x', coalesce(current_state #> '{actors,host,x}', to_jsonb(0.555::numeric)),
               'y', coalesce(current_state #> '{actors,host,y}', to_jsonb(0.595::numeric)),
               'facing', coalesce(current_state #>> '{actors,host,facing}', 'south')
             ),
             'maker', jsonb_build_object(
               'id', 'maker', 'kind', 'actor', 'label', 'maker', 'asset', 'maker',
               'x', 0.39, 'y', 0.56, 'facing', 'east'
             ),
             'neighbor', jsonb_build_object(
               'id', 'neighbor', 'kind', 'actor', 'label', 'neighbor', 'asset', 'neighbor',
               'x', 0.7, 'y', 0.65, 'facing', 'west'
             )
           )
         ),
         updated_at = pg_catalog.now()
   where id = 'commons-home';
end;
$$;
