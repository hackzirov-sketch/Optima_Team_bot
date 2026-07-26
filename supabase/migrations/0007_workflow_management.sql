alter table bot_app.users add column if not exists last_seen_at timestamptz;
alter table bot_app.groups add column if not exists is_active boolean not null default true;
alter table bot_app.tasks add column if not exists deadline_at timestamptz;
alter table bot_app.tasks add column if not exists group_message_id bigint;
alter table bot_app.tasks add column if not exists is_pinned boolean not null default false;

alter table bot_app.task_users drop constraint if exists task_users_status_check;
alter table bot_app.task_users add constraint task_users_status_check
  check (status in ('assigned','in_progress','submitted','rework','approved','completed'));
alter table bot_app.task_users add column if not exists result_text text;
alter table bot_app.task_users add column if not exists result_file_id text;
alter table bot_app.task_users add column if not exists result_file_name text;
alter table bot_app.task_users add column if not exists submitted_at timestamptz;
alter table bot_app.task_users add column if not exists review_note text;
alter table bot_app.task_users add column if not exists opened_at timestamptz;
alter table bot_app.task_users add column if not exists reminded_24 boolean not null default false;
alter table bot_app.task_users add column if not exists reminded_3 boolean not null default false;
alter table bot_app.task_users add column if not exists reminded_1 boolean not null default false;

create table if not exists bot_app.task_templates (
  id bigint generated always as identity primary key,
  name text not null, description text not null,
  created_by bigint references bot_app.users(tg_id) on delete set null,
  created_at timestamptz not null default now()
);
create table if not exists bot_app.audit_logs (
  id bigint generated always as identity primary key,
  actor_id bigint references bot_app.users(tg_id) on delete set null,
  action text not null, target_type text, target_id text, details text,
  created_at timestamptz not null default now()
);
create index if not exists task_users_review_idx on bot_app.task_users(status,submitted_at desc);
create index if not exists users_last_seen_idx on bot_app.users(last_seen_at desc);
alter table bot_app.task_templates enable row level security;
alter table bot_app.audit_logs enable row level security;
revoke all on bot_app.task_templates, bot_app.audit_logs from public, anon, authenticated;
grant select,insert,update,delete on bot_app.task_templates, bot_app.audit_logs to service_role;
grant usage,select on all sequences in schema bot_app to service_role;
