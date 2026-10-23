\ir dice-local-table-grants.sql

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  (
    'dice-comment-photos',
    'dice-comment-photos',
    true,
    10485760,
    array['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/svg+xml']
  ),
  (
    'dice-profile-photos',
    'dice-profile-photos',
    true,
    10485760,
    array['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/svg+xml']
  )
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists dice_local_user_image_upload on storage.objects;
create policy dice_local_user_image_upload on storage.objects
  for insert to authenticated
  with check (
    bucket_id in ('dice-comment-photos', 'dice-profile-photos')
    and (storage.foldername(name))[1] = auth.uid()::text
  );
