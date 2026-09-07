-- Comments on Dice matches. Writes go through the backend (service-role
-- client), which enforces author/admin permissions in Python, matching the
-- dice_games convention; RLS here only grants public read access.

create table if not exists public.dice_game_comments (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.dice_games(id) on delete cascade,
  user_id uuid not null references auth.users(id),
  body text not null,
  created_at timestamptz not null default now(),
  constraint dice_game_comments_body_check check (char_length(body) > 0 and char_length(body) <= 2000)
);

create index if not exists dice_game_comments_game_id_idx on public.dice_game_comments (game_id, created_at);

alter table public.dice_game_comments enable row level security;
create policy dice_game_comments_public_read on public.dice_game_comments
  for select to anon, authenticated
  using (true);
