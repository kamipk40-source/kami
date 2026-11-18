-- Hazri Hisab: camera attendance tables. Run in Supabase > SQL Editor AFTER hr_setup.sql.
-- BEFORE running: replace ADMIN_EMAIL_HERE (same as in hr_setup.sql) and CAMERA_EMAIL_HERE
-- with the camera user's email (create it in Authentication > Users; it must be a different user).

create table if not exists public.hr_events (
  id bigint generated always as identity primary key,
  day date not null,
  emp_id text not null,
  t text not null,
  camera text,
  score real,
  created_at timestamptz not null default now(),
  unique (day, emp_id)          -- only the first sighting of a person each day is kept
);
alter table public.hr_events enable row level security;

create table if not exists public.hr_cameras (
  name text primary key,
  last_seen timestamptz not null default now()
);
alter table public.hr_cameras enable row level security;

drop policy if exists "events admins" on public.hr_events;
create policy "events admins" on public.hr_events for all to authenticated
  using ((auth.jwt() ->> 'email') in ('ADMIN_EMAIL_HERE'))
  with check ((auth.jwt() ->> 'email') in ('ADMIN_EMAIL_HERE'));

drop policy if exists "events camera adds" on public.hr_events;
create policy "events camera adds" on public.hr_events for insert to authenticated
  with check ((auth.jwt() ->> 'email') in ('CAMERA_EMAIL_HERE'));

drop policy if exists "cameras admins read" on public.hr_cameras;
create policy "cameras admins read" on public.hr_cameras for select to authenticated
  using ((auth.jwt() ->> 'email') in ('ADMIN_EMAIL_HERE'));

drop policy if exists "cameras camera writes" on public.hr_cameras;
create policy "cameras camera writes" on public.hr_cameras for all to authenticated
  using ((auth.jwt() ->> 'email') in ('CAMERA_EMAIL_HERE'))
  with check ((auth.jwt() ->> 'email') in ('CAMERA_EMAIL_HERE'));

revoke all on public.hr_events, public.hr_cameras from anon;
grant select, insert, update, delete on public.hr_events, public.hr_cameras to authenticated;
-- the camera user cannot read hr_events or hr_kv (salaries): no policy gives it select there.
