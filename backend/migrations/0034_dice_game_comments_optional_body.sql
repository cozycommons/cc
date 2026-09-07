-- Allow image-only comments (no caption) now that comments can attach a
-- picture: body becomes optional, but a comment must have text, an image,
-- or both.

alter table public.dice_game_comments alter column body drop not null;
alter table public.dice_game_comments drop constraint if exists dice_game_comments_body_check;
alter table public.dice_game_comments
  add constraint dice_game_comments_body_check check (body is null or char_length(body) <= 2000);
alter table public.dice_game_comments
  add constraint dice_game_comments_has_content_check
  check (coalesce(char_length(body), 0) > 0 or image_url is not null);
