alter table bot_app.users drop constraint if exists users_role_check;
alter table bot_app.users add constraint users_role_check
  check (role in ('user','manager','admin','superadmin'));
alter table bot_app.users add column if not exists active_mode text not null default 'user';
alter table bot_app.users drop constraint if exists users_active_mode_check;
alter table bot_app.users add constraint users_active_mode_check
  check (active_mode in ('user','admin','superadmin'));

create table if not exists bot_app.settings (
  key text primary key,
  value text not null
);
alter table bot_app.settings enable row level security;
revoke all on bot_app.settings from public, anon, authenticated;
grant select, insert, update, delete on bot_app.settings to service_role;
