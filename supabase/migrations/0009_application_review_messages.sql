create table if not exists bot_app.application_review_messages (
  application_user_id bigint not null references bot_app.users(tg_id) on delete cascade,
  staff_id bigint not null references bot_app.users(tg_id) on delete cascade,
  message_id bigint not null,
  sent_at timestamptz not null default now(),
  primary key (application_user_id, staff_id)
);

create index if not exists application_review_messages_user_idx
  on bot_app.application_review_messages(application_user_id);

alter table bot_app.application_review_messages enable row level security;
revoke all on bot_app.application_review_messages from public, anon, authenticated;
grant select, insert, update, delete on bot_app.application_review_messages to service_role;

