-- Synthetic local-only users. Password for every account: local-dice-password
-- These UUIDs and emails must never be used as production fixtures.
create extension if not exists pgcrypto;

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, email_change, email_change_token_new, recovery_token
) values
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000001', 'authenticated', 'authenticated', 'referee@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Local Referee"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000002', 'authenticated', 'authenticated', 'alpha@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Alpha Toss"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000003', 'authenticated', 'authenticated', 'bravo@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Bravo Catch"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000004', 'authenticated', 'authenticated', 'charlie@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Charlie Sink"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000005', 'authenticated', 'authenticated', 'delta@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Delta Dink"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000006', 'authenticated', 'authenticated', 'echo@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Echo Arc"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000007', 'authenticated', 'authenticated', 'foxtrot@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Foxtrot Flick"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000008', 'authenticated', 'authenticated', 'golf@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Golf Guard"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000009', 'authenticated', 'authenticated', 'hotel@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Hotel Hop"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000010', 'authenticated', 'authenticated', 'india@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"India In"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000011', 'authenticated', 'authenticated', 'juliet@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Juliet Jump"}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', '10000000-0000-0000-0000-000000000012', 'authenticated', 'authenticated', 'kilo@dice.local', crypt('local-dice-password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"full_name":"Kilo Keep"}', now(), now(), '', '', '', '');

insert into auth.identities (
  id, provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at
) select
  gen_random_uuid(), id::text, id,
  jsonb_build_object('sub', id::text, 'email', email),
  'email', now(), now(), now()
from auth.users
where email like '%@dice.local';

insert into public.dice_profiles (
  user_id, display_name, avatar_url, elo_rating, games_played,
  ranked_games_played, wins, losses, ranked_wins, ranked_losses,
  self_sinks, sinks, rating_deviation
) values
  ('10000000-0000-0000-0000-000000000001', 'Local Referee', null, 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000002', 'Alpha Toss', '/dice/demo-avatars/alpha.webp', 1523, 3, 3, 2, 1, 2, 1, 0, 1, 217.56),
  ('10000000-0000-0000-0000-000000000003', 'Bravo Catch', '/dice/demo-avatars/bravo.webp', 1523, 3, 3, 2, 1, 2, 1, 0, 0, 217.56),
  ('10000000-0000-0000-0000-000000000004', 'Charlie Sink', '/dice/demo-avatars/charlie.webp', 1477, 3, 3, 1, 2, 1, 2, 0, 1, 217.56),
  ('10000000-0000-0000-0000-000000000005', 'Delta Dink', '/dice/demo-avatars/delta.webp', 1477, 3, 3, 1, 2, 1, 2, 1, 0, 217.56),
  ('10000000-0000-0000-0000-000000000006', 'Echo Arc', '/dice/demo-avatars/alpha.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000007', 'Foxtrot Flick', '/dice/demo-avatars/bravo.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000008', 'Golf Guard', '/dice/demo-avatars/charlie.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000009', 'Hotel Hop', '/dice/demo-avatars/delta.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000010', 'India In', '/dice/demo-avatars/alpha.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000011', 'Juliet Jump', '/dice/demo-avatars/bravo.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350),
  ('10000000-0000-0000-0000-000000000012', 'Kilo Keep', '/dice/demo-avatars/charlie.webp', 1500, 0, 0, 0, 0, 0, 0, 0, 0, 350);

insert into public.dice_games (
  id, created_by, ranked, team1_score, team2_score, winner_team, played_at
) values
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000001', true, 11, 7, 1, now() - interval '4 days'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', true, 9, 11, 2, now() - interval '3 days'),
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', true, 11, 8, 1, now() - interval '2 days');

insert into public.dice_game_players (
  game_id, user_id, team, self_sinks, sinks, elo_before, elo_after,
  rating_deviation_before, rating_deviation_after
) values
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', 1, 0, 0, 1500, 1527, 350, 297.5),
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000003', 1, 0, 0, 1500, 1527, 350, 297.5),
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000004', 2, 0, 0, 1500, 1473, 350, 297.5),
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000005', 2, 0, 0, 1500, 1473, 350, 297.5),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 1, 0, 0, 1527, 1502, 299.17, 254.29),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000003', 1, 0, 0, 1527, 1502, 299.17, 254.29),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000004', 2, 0, 0, 1473, 1498, 299.17, 254.29),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000005', 2, 0, 0, 1473, 1498, 299.17, 254.29),
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002', 1, 0, 1, 1502, 1523, 255.96, 217.56),
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003', 1, 0, 0, 1502, 1523, 255.96, 217.56),
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000004', 2, 0, 1, 1498, 1477, 255.96, 217.56),
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000005', 2, 1, 0, 1498, 1477, 255.96, 217.56);

-- Duo ladder fixtures: Alpha Toss + Bravo Catch have five completed ranked
-- games together, which makes the pair visible in the homepage preview. The
-- opposing pair is seeded as well so the detail page has a real record and
-- head-to-head history to link back to.
insert into public.dice_games (
  id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at
) values
  ('20000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000001', true, true, 11, 6, 1, now() - interval '1 day'),
  ('20000000-0000-0000-0000-000000000005', '10000000-0000-0000-0000-000000000001', true, true, 11, 10, 1, now() - interval '12 hours');

insert into public.dice_game_players (game_id, user_id, team)
select game_id, user_id, team
from (values
  ('20000000-0000-0000-0000-000000000004'::uuid, '10000000-0000-0000-0000-000000000002'::uuid, 1::smallint),
  ('20000000-0000-0000-0000-000000000004'::uuid, '10000000-0000-0000-0000-000000000003'::uuid, 1::smallint),
  ('20000000-0000-0000-0000-000000000004'::uuid, '10000000-0000-0000-0000-000000000004'::uuid, 2::smallint),
  ('20000000-0000-0000-0000-000000000004'::uuid, '10000000-0000-0000-0000-000000000005'::uuid, 2::smallint),
  ('20000000-0000-0000-0000-000000000005'::uuid, '10000000-0000-0000-0000-000000000002'::uuid, 1::smallint),
  ('20000000-0000-0000-0000-000000000005'::uuid, '10000000-0000-0000-0000-000000000003'::uuid, 1::smallint),
  ('20000000-0000-0000-0000-000000000005'::uuid, '10000000-0000-0000-0000-000000000004'::uuid, 2::smallint),
  ('20000000-0000-0000-0000-000000000005'::uuid, '10000000-0000-0000-0000-000000000005'::uuid, 2::smallint)
) as fixture(game_id, user_id, team);

-- Longer synthetic runs make confidence-aware ordering reviewable: Echo Arc +
-- Foxtrot Flick are 20-1, while Golf Guard + Hotel Hop are 8-0. Deterministic
-- IDs and timestamps keep reset/replay output stable.
do $$
declare
  game_id uuid;
  winner smallint;
begin
  for i in 1..21 loop
    game_id := md5('dice-duo-long-' || i)::uuid;
    winner := case when i = 21 then 2 else 1 end;
    insert into public.dice_games (
      id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at
    ) values (
      game_id, '10000000-0000-0000-0000-000000000001', true, true,
      case when winner = 1 then 11 else 8 end,
      case when winner = 1 then 6 else 11 end,
      winner,
      timestamptz '2026-01-01 00:00:00+00' + (i - 1) * interval '1 hour'
    );
    insert into public.dice_game_players (game_id, user_id, team) values
      (game_id, '10000000-0000-0000-0000-000000000006', 1),
      (game_id, '10000000-0000-0000-0000-000000000007', 1),
      (game_id, '10000000-0000-0000-0000-000000000002', 2),
      (game_id, '10000000-0000-0000-0000-000000000003', 2);
  end loop;

  for i in 1..8 loop
    game_id := md5('dice-duo-short-' || i)::uuid;
    insert into public.dice_games (
      id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at
    ) values (
      game_id, '10000000-0000-0000-0000-000000000001', true, true, 11, 8, 1,
      timestamptz '2026-02-01 00:00:00+00' + (i - 1) * interval '1 hour'
    );
    insert into public.dice_game_players (game_id, user_id, team) values
      (game_id, '10000000-0000-0000-0000-000000000008', 1),
      (game_id, '10000000-0000-0000-0000-000000000009', 1),
      (game_id, '10000000-0000-0000-0000-000000000004', 2),
      (game_id, '10000000-0000-0000-0000-000000000005', 2);
  end loop;

  for i in 1..2 loop
    game_id := md5('dice-duo-provisional-a-' || i)::uuid;
    insert into public.dice_games (id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at)
    values (game_id, '10000000-0000-0000-0000-000000000001', true, true, 11, 9, 1,
      timestamptz '2026-03-01 00:00:00+00' + (i - 1) * interval '1 hour');
    insert into public.dice_game_players (game_id, user_id, team) values
      (game_id, '10000000-0000-0000-0000-000000000002', 1),
      (game_id, '10000000-0000-0000-0000-000000000004', 1),
      (game_id, '10000000-0000-0000-0000-000000000006', 2),
      (game_id, '10000000-0000-0000-0000-000000000008', 2);
  end loop;

  for i in 1..2 loop
    game_id := md5('dice-duo-provisional-b-' || i)::uuid;
    insert into public.dice_games (id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at)
    values (game_id, '10000000-0000-0000-0000-000000000001', true, true, 8, 11, 2,
      timestamptz '2026-04-01 00:00:00+00' + (i - 1) * interval '1 hour');
    insert into public.dice_game_players (game_id, user_id, team) values
      (game_id, '10000000-0000-0000-0000-000000000003', 1),
      (game_id, '10000000-0000-0000-0000-000000000005', 1),
      (game_id, '10000000-0000-0000-0000-000000000007', 2),
      (game_id, '10000000-0000-0000-0000-000000000009', 2);
  end loop;

  for i in 1..2 loop
    game_id := md5('dice-duo-provisional-c-' || i)::uuid;
    insert into public.dice_games (id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at)
    values (game_id, '10000000-0000-0000-0000-000000000001', true, true, 11, 10, 1,
      timestamptz '2026-05-01 00:00:00+00' + (i - 1) * interval '1 hour');
    insert into public.dice_game_players (game_id, user_id, team) values
      (game_id, '10000000-0000-0000-0000-000000000010', 1),
      (game_id, '10000000-0000-0000-0000-000000000012', 1),
      (game_id, '10000000-0000-0000-0000-000000000002', 2),
      (game_id, '10000000-0000-0000-0000-000000000006', 2);
  end loop;
end
$$;

insert into public.dice_game_comments (game_id, user_id, body, image_url, created_at) values
  (
    '20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000004',
    'Synthetic gallery fixture: table setup.',
    '/dice-dev/gallery-table.svg',
    now() - interval '1 day'
  ),
  (
    '20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000003',
    'Synthetic gallery fixture: winning toss.',
    '/dice-dev/gallery-toss.svg',
    now() - interval '12 hours'
  ),
  (
    '20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    'Synthetic gallery fixture: compact variants.',
    '/dice-dev/gallery-compact/display.webp',
    now() - interval '6 hours'
  );

insert into public.dice_tournaments (
  id, name, starts_at, host_user_ids, created_by, data
) values (
  '30000000-0000-0000-0000-000000000001',
  'Local Summer Open',
  date_trunc('day', now()) + interval '7 days 19 hours',
  array['10000000-0000-0000-0000-000000000001']::uuid[],
  '10000000-0000-0000-0000-000000000001',
  '{"description":"Synthetic upcoming tournament for local development."}'::jsonb
);

insert into public.dice_tournament_enrollments (tournament_id, user_id) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001'),
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002'),
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003'),
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000004'),
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000005');
