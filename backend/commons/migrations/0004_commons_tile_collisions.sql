-- Reserve the grid collision layer in the canonical Commons scene state.
-- The initial room has no permanent floor blockers; movable entities still
-- reserve their current tile and the API validates every future command.

update public.commons_scenes
   set layout_version = 4,
       version = version + 1,
       state = jsonb_set(
         jsonb_set(state, '{schema_version}', '3'::jsonb, true),
         '{grid,blocked}',
         '[]'::jsonb,
         true
       ),
       updated_at = pg_catalog.now()
 where id = 'commons-home';
