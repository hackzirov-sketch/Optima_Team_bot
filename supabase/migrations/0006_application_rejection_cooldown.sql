alter table bot_app.users
  add column if not exists rejected_at timestamptz;
