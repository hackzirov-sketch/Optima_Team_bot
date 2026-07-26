create index if not exists application_review_messages_staff_idx on bot_app.application_review_messages(staff_id);
create index if not exists task_questions_answered_by_idx on bot_app.task_questions(answered_by);
create index if not exists users_application_reviewed_by_idx on bot_app.users(application_reviewed_by);

-- This dashboard-created helper does not need to be exposed through the Data API.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
