alter table bot_app.users
  add column if not exists portfolio_file_id text,
  add column if not exists portfolio_file_name text,
  add column if not exists portfolio_file_mime text;
