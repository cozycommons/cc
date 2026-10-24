-- Link the 2026-27 league managers who already have Dice profiles. Each pair
-- was matched on the ESPN owner's full name and the Dice display name. Rows
-- are skipped when the user doesn't exist (other environments) or when the
-- team or user is already linked, so manual links always win. Users can unlink.
insert into public.espn_team_claims (season, team_id, user_id)
select 2027, seed.team_id, seed.user_id
from (values
  (1,  '1fb0c188-f1f9-47dc-ac2a-c7a3a9112761'::uuid),  -- Warner Tsang
  (2,  'c52ebf83-2310-42f6-94e0-618eb57fdd7a'::uuid),  -- Oscar Hu
  (3,  '8f475254-66dc-4d6a-8f75-8905712493a2'::uuid),  -- Matt Ho
  (4,  '706f9e88-e0ea-47e6-a3c8-ddf3e0c4e3d7'::uuid),  -- Aaron Lee
  (5,  'fc989a93-31ea-45e4-86b7-31c9a42e9a35'::uuid),  -- Andre Wang
  (6,  '7149b62c-737b-4f70-84df-9285a1063276'::uuid),  -- Ben Kim
  (7,  'de9f3af9-d944-4181-8a31-98c123927640'::uuid),  -- Alan Liu
  (9,  '05e8097f-52cd-4e5d-9741-04c813a78649'::uuid),  -- Drew Sohn
  (11, 'b23c81fb-d466-4a23-8c6e-2b67b35b6c4e'::uuid),  -- Shrey Shah
  (12, 'b4469908-04a0-4620-9c9e-42f20e5c5bee'::uuid)   -- Alan Li
) as seed (team_id, user_id)
where exists (select 1 from auth.users where id = seed.user_id)
on conflict do nothing;
