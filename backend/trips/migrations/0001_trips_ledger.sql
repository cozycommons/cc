create table public.trips_groups (
  id uuid primary key,
  owner_id uuid not null references auth.users(id),
  member_user_ids uuid[] not null,
  data jsonb not null check (jsonb_typeof(data) = 'object'),
  revision integer not null default 1 check (revision > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (owner_id = any(member_user_ids)),
  check (cardinality(member_user_ids) between 1 and 30)
);
create index trips_groups_members on public.trips_groups using gin(member_user_ids);
alter table public.trips_groups enable row level security;
revoke all on public.trips_groups from public, anon, authenticated;
grant select on public.trips_groups to authenticated;
grant all on public.trips_groups to service_role;
create policy trips_member_read on public.trips_groups for select to authenticated
  using (member_user_ids @> array[(select auth.uid())]);
