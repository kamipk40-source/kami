-- Hazri Hisab (attendance + salary): secure storage. Run once in Supabase > SQL Editor.
-- BEFORE running: replace ADMIN_EMAIL_HERE below with the admin email(s) you created in Supabase > Authentication > Users.
-- Example for two admins:  in ('first@example.com', 'second@example.com')

create table if not exists public.hr_kv (
  k text primary key,
  v jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.hr_kv enable row level security;

drop policy if exists "hr admins only" on public.hr_kv;
create policy "hr admins only" on public.hr_kv
  for all to authenticated
  using ((auth.jwt() ->> 'email') in ('ADMIN_EMAIL_HERE'))
  with check ((auth.jwt() ->> 'email') in ('ADMIN_EMAIL_HERE'));

-- the public (not signed in) key gets no access at all
revoke all on public.hr_kv from anon;
grant select, insert, update, delete on public.hr_kv to authenticated;
