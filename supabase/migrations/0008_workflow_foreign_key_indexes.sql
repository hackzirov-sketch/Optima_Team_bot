create index if not exists groups_added_by_idx on bot_app.groups(added_by);
create index if not exists tasks_group_id_idx on bot_app.tasks(group_id);
create index if not exists tasks_created_by_idx on bot_app.tasks(created_by);
create index if not exists task_templates_created_by_idx on bot_app.task_templates(created_by);
create index if not exists audit_logs_actor_id_idx on bot_app.audit_logs(actor_id);
