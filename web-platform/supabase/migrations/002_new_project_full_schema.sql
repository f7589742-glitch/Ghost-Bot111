-- ============================================================
-- ZeroBot — Full schema for the NEW Supabase project
-- (gvkgqvwasupnepnidnnk)
-- Run ONCE: Supabase Dashboard → SQL Editor → New query → paste
-- this whole file → Run. Safe to re-run (idempotent).
-- ============================================================

-- ------------------------------------------------------------
-- 1. Core multi-tenant tables
-- ------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  discord_id text,
  username text,
  avatar_url text,
  created_at timestamptz not null default now()
);

create table if not exists public.bot_instances (
  id text primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  product text not null default 'farm-bot',
  name text not null,
  slots integer not null default 5,
  tier text not null default 'basic',
  room text not null default '',
  ref text not null default '',
  total text not null default '',
  status text not null default 'stopped',
  runtime_status text,
  server_worker_id text,
  server_node text,
  last_heartbeat timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.game_accounts (
  id bigserial primary key,
  instance_id text not null references public.bot_instances(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  email text not null,
  game_token text,
  device_udid text,
  role_id text,
  kingdom_id integer,
  is_enabled boolean not null default true,
  proxy_url text,
  device_profile jsonb,
  last_login_ip text,
  assigned_slot integer not null default 0,
  settings jsonb not null default '{}'::jsonb,
  last_run timestamptz,
  created_at timestamptz not null default now(),
  unique(instance_id, email)
);

-- ------------------------------------------------------------
-- 2. Broadcasts / announcements
-- ------------------------------------------------------------
create table if not exists public.announcements (
  id bigserial primary key,
  title text not null default '',
  body text not null default '',
  image_url text,
  created_at timestamptz not null default now()
);

alter table public.announcements enable row level security;

drop policy if exists "announcements read" on public.announcements;
create policy "announcements read" on public.announcements
  for select to authenticated using (true);

drop policy if exists "announcements write" on public.announcements;
create policy "announcements write" on public.announcements
  for all to authenticated using (true) with check (true);

-- Storage bucket for broadcast images (public read)
insert into storage.buckets (id, name, public)
values ('broadcasts', 'broadcasts', true)
on conflict (id) do nothing;

drop policy if exists "broadcasts public read" on storage.objects;
create policy "broadcasts public read" on storage.objects
  for select using (bucket_id = 'broadcasts');

drop policy if exists "broadcasts authed write" on storage.objects;
create policy "broadcasts authed write" on storage.objects
  for insert to authenticated with check (bucket_id = 'broadcasts');

-- ------------------------------------------------------------
-- 3. Row Level Security: users touch ONLY their own rows
-- ------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.bot_instances enable row level security;
alter table public.game_accounts enable row level security;

drop policy if exists "own profile" on public.profiles;
create policy "own profile" on public.profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists "own instances" on public.bot_instances;
create policy "own instances" on public.bot_instances
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own accounts" on public.game_accounts;
create policy "own accounts" on public.game_accounts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ------------------------------------------------------------
-- 4. Auto-create profile on signup (Discord login)
-- ------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, discord_id, username, avatar_url)
  values (
    new.id,
    new.raw_user_meta_data ->> 'provider_id',
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name', new.email),
    new.raw_user_meta_data ->> 'avatar_url'
  )
  on conflict (id) do update set
    discord_id = excluded.discord_id,
    username = excluded.username,
    avatar_url = excluded.avatar_url;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
