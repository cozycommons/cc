-- Backend-only durable thumbnails, versioned by the normalized upstream URL.
create table if not exists public.venmo_photos (
    handle text not null references public.venmo_profiles(handle) on delete cascade,
    photo_url text not null,
    body text not null check (length(body) <= 699052),
    content_type text not null check (content_type in ('image/jpeg', 'image/png', 'image/webp')),
    primary key (handle, photo_url)
);
alter table public.venmo_photos enable row level security;
revoke all on public.venmo_photos from public, anon, authenticated;
grant select, insert, update, delete on public.venmo_photos to service_role;
