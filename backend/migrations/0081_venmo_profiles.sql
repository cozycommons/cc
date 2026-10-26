-- Optional public profile display data; all reads/writes go through the authenticated backend.
create table if not exists public.venmo_profiles (
    handle text primary key check (handle = lower(handle)),
    display_name text not null,
    photo_url text not null,
    initials text not null,
    active boolean not null,
    source text not null check (source in ('live', 'og')),
    fetched_at timestamptz not null
);
alter table public.venmo_profiles enable row level security;
revoke all on public.venmo_profiles from public, anon, authenticated;
grant select, insert, update, delete on public.venmo_profiles to service_role;
