alter table bot_app.users add column if not exists application_review_note text;
alter table bot_app.users add column if not exists application_reviewed_by bigint references bot_app.users(tg_id) on delete set null;
alter table bot_app.users add column if not exists application_reviewed_at timestamptz;

alter table bot_app.task_users add column if not exists rating smallint;
alter table bot_app.task_users drop constraint if exists task_users_rating_check;
alter table bot_app.task_users add constraint task_users_rating_check check (rating is null or rating between 1 and 5);

create table if not exists bot_app.task_questions (
  id bigint generated always as identity primary key,
  task_id bigint not null references bot_app.tasks(id) on delete cascade,
  user_id bigint not null references bot_app.users(tg_id) on delete cascade,
  question text not null,
  answer text,
  answered_by bigint references bot_app.users(tg_id) on delete set null,
  created_at timestamptz not null default now(),
  answered_at timestamptz
);
create index if not exists task_questions_task_idx on bot_app.task_questions(task_id, created_at desc);
create index if not exists task_questions_user_idx on bot_app.task_questions(user_id, created_at desc);

alter table bot_app.task_questions enable row level security;
revoke all on bot_app.task_questions from public, anon, authenticated;
grant select, insert, update, delete on bot_app.task_questions to service_role;
grant usage, select on all sequences in schema bot_app to service_role;
