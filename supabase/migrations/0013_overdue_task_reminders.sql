alter table bot_app.task_users
    add column if not exists reminded_overdue boolean not null default false;
