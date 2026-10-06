-- Aegis Fleet multi-tenant schema (Supabase PostgreSQL)
-- Run in Supabase Dashboard → SQL Editor.

-- 1. profiles: one row per Discord user (id = auth.users.id)
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  discord_id text,
  username text,
  avatar_url text,
  created_at timestamptz not null default now()
);

-- 2. bot_instances: purchased bots (Your Bots section)
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
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

-- 3. game_accounts: farm accounts inside an instance
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
  settings jsonb not null default '{}'::jsonb,
  last_run timestamptz,
  created_at timestamptz not null default now(),
  unique(instance_id, email)
);

-- 4. Row Level Security: users touch ONLY their own rows
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

-- 5. Auto-create profile on signup
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
