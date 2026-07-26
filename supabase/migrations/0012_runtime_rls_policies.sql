-- The bot connects with this dedicated runtime role. RLS remains enabled and
-- access is not granted to Supabase anon/authenticated roles.
grant select, insert, update, delete on table
    bot_app.audit_logs,
    bot_app.task_templates,
    bot_app.application_review_messages,
    bot_app.task_questions
to optima_bot_runtime;

grant usage, select on all sequences in schema bot_app to optima_bot_runtime;

create policy runtime_all on bot_app.audit_logs
    for all
    to optima_bot_runtime
    using (true)
    with check (true);

create policy runtime_all on bot_app.task_templates
    for all
    to optima_bot_runtime
    using (true)
    with check (true);

create policy runtime_all on bot_app.application_review_messages
    for all
    to optima_bot_runtime
    using (true)
    with check (true);

create policy runtime_all on bot_app.task_questions
    for all
    to optima_bot_runtime
    using (true)
    with check (true);
