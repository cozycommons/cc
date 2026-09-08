-- Reconcile the starting arrangement with the persisted room-shell and
-- furniture-footprint collision rules introduced by the previous migrations.

update public.commons_scenes
   set layout_version = 7,
       version = version + 1,
       state = state || jsonb_build_object(
         'schema_version', 6,
         'objects', coalesce(state->'objects', '{}'::jsonb) || jsonb_build_object(
           'record-console',
             (state #> '{objects,record-console}') || jsonb_build_object(
               'tile_x', 2,
               'tile_y', 6,
               'x', 0.375,
               'y', 0.5078125
             ),
           'palm',
             (state #> '{objects,palm}') || jsonb_build_object(
               'tile_x', 14,
               'tile_y', 8,
               'x', 0.6875,
               'y', 0.78125
             )
         )
       ),
       updated_at = pg_catalog.now()
 where id = 'commons-home';
