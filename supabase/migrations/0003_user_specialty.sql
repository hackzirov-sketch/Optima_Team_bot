alter table bot_app.users add column if not exists specialty text;
alter table bot_app.users drop constraint if exists users_specialty_check;
alter table bot_app.users add constraint users_specialty_check
  check (specialty is null or specialty in ('backend','frontend','fullstack','vibecoder'));
create index if not exists users_specialty_status_idx
  on bot_app.users(specialty,status);
