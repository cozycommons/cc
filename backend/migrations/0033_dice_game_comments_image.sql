-- Lets a Dice match comment optionally attach a single image.

alter table public.dice_game_comments
  add column if not exists image_url text;
