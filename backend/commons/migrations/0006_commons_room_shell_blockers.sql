-- Persist the two upper grid edges as the Commons room's back-wall collision.
-- The front of the room remains open; movable furniture supplies its own
-- footprint collisions on top of this static shell.

update public.commons_scenes
   set layout_version = 6,
       version = version + 1,
       state = jsonb_set(
         jsonb_set(state, '{schema_version}', '5'::jsonb, true),
         '{grid,blocked}',
         '[[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0],[7,0],[8,0],[9,0],[10,0],[11,0],[12,0],[13,0],[14,0],[15,0],[0,1],[0,2],[0,3],[0,4],[0,5],[0,6],[0,7],[0,8],[0,9],[0,10],[0,11],[0,12],[0,13],[0,14],[0,15]]'::jsonb,
         true
       ),
       updated_at = pg_catalog.now()
 where id = 'commons-home';
