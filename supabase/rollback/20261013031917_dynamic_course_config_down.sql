-- Rollback for 20261013031917_dynamic_course_config.sql
--
-- WARNING: this drops every course, faculty member and exam created through the
-- new CR dashboard. Export them first if they matter:
--   select * from public.exam_details;   (and public.courses / public.faculty)
--
-- The legacy public."Exams" table is untouched by the migration, so after this
-- rollback the previous application version keeps working against it. Exams
-- created after the migration exist only in public.exams and are NOT copied
-- back automatically.

begin;

drop view if exists public.exam_details;

drop function if exists public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, bigint[], uuid, uuid);
drop function if exists public.cr_save_course(bigint, text, text, text[], bigint[], text);
drop function if exists public.cr_remove_course(bigint);
drop function if exists public.cr_remove_faculty(bigint);

drop table if exists public.exam_faculty;
drop table if exists public.exams;
drop table if exists public.exam_types;
drop table if exists public.course_faculty;
drop table if exists public.courses;
drop table if exists public.faculty;
drop table if exists public.cr_members;

drop function if exists public.exams_validate_type();
drop function if exists public.courses_guard_type_change();
drop function if exists public.set_updated_at();
drop function if exists public.course_type_for_code(text);
drop function if exists public.normalize_course_code(text);

-- The migration revoked anon/authenticated grants on the legacy table. RLS
-- (enabled, no policies) blocked them anyway, so they are intentionally not
-- restored here.

commit;
