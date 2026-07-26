alter table bot_app.users
  add column if not exists age integer;

alter table bot_app.users
  drop constraint if exists users_age_check;

alter table bot_app.users
  add constraint users_age_check check (age is null or age between 14 and 100);
