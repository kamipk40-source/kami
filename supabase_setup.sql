-- KK IT Asset Management: shared data table
create table if not exists public.kv (
  k text primary key,
  v text not null,
  updated_at timestamptz not null default now()
);

alter table public.kv enable row level security;

drop policy if exists "kv anon all" on public.kv;
create policy "kv anon all" on public.kv
  for all to anon
  using (true) with check (true);

grant select, insert, update, delete on public.kv to anon;
