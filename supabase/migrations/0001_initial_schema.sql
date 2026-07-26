create schema if not exists bot_app;
revoke all on schema bot_app from public, anon, authenticated;
grant usage on schema bot_app to postgres, service_role;

create table if not exists bot_app.users (
  tg_id bigint primary key,
  username text,
  full_name text not null,
  phone text,
  portfolio text,
  about text,
  role text not null default 'user' check (role in ('user','manager','admin','superadmin')),
  status text not null default 'draft' check (status in ('draft','pending','accepted','rejected','blocked')),
  active_mode text not null default 'user' check (active_mode in ('user','admin','superadmin')),
  specialty text check (specialty is null or specialty in ('backend','frontend','fullstack','vibecoder')),
  created_at timestamptz not null default now()
);

create table if not exists bot_app.groups (
  chat_id bigint primary key,
  title text not null,
  added_by bigint references bot_app.users(tg_id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists bot_app.tasks (
  id bigint generated always as identity primary key,
  name text not null,
  description text not null,
  deadline text not null,
  group_id bigint references bot_app.groups(chat_id) on delete set null,
  created_by bigint not null references bot_app.users(tg_id),
  created_at timestamptz not null default now()
);

create table if not exists bot_app.task_users (
  task_id bigint not null references bot_app.tasks(id) on delete cascade,
  user_id bigint not null references bot_app.users(tg_id) on delete cascade,
  status text not null default 'assigned' check (status in ('assigned','completed')),
  completed_at timestamptz,
  primary key(task_id,user_id)
);

create table if not exists bot_app.settings (
  key text primary key,
  value text not null
);

create index if not exists users_status_role_idx on bot_app.users(status,role);
create index if not exists tasks_created_at_idx on bot_app.tasks(created_at desc);
create index if not exists task_users_user_status_idx on bot_app.task_users(user_id,status);

alter table bot_app.users enable row level security;
alter table bot_app.groups enable row level security;
alter table bot_app.tasks enable row level security;
alter table bot_app.task_users enable row level security;
alter table bot_app.settings enable row level security;

revoke all on all tables in schema bot_app from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema bot_app to service_role;
grant usage, select on all sequences in schema bot_app to service_role;
