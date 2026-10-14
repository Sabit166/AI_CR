-- Rollback of 20261014074933_theory_course_sections.sql.
-- Restores the 20261013150000 functions, trigger and exam_details view, and drops
-- course_faculty.sections and exams.course_section. Course-section assignments and
-- Theoretical exams' course sections are lost; Theoretical courses whose teachers
-- are not exactly 2 must be fixed by hand before they can be saved again.

drop view public.exam_details;
create view public.exam_details
with (security_invoker = true)
as
select
  e.id,
  e.course_id,
  c.code as course_code,
  c.title as course_title,
  c.course_type,
  (c.archived_at is not null) as course_archived,
  e.exam_type,
  e.exam_date,
  e.exam_time,
  e.section,
  e.syllabus,
  e.venue,
  e.remarks,
  e.notes_link,
  coalesce(ef.ids, cf.ids, '{}'::bigint[]) as faculty_ids,
  coalesce(ef.names,
           case when e.legacy_teacher is not null then array[e.legacy_teacher] end,
           cf.names,
           '{}'::text[]) as faculty_names,
  case
    when ef.ids is not null then 'exam'
    when e.legacy_teacher is not null then 'legacy'
    when cf.ids is not null then 'course'
    else 'none'
  end as faculty_source,
  coalesce(ef.ids, '{}'::bigint[]) as exam_faculty_ids,
  e.legacy_exam_id,
  e.created_at,
  e.updated_at
from public.exams e
join public.courses c on c.id = e.course_id
left join lateral (
  select array_agg(f.id order by f.name) as ids, array_agg(f.name order by f.name) as names
  from public.exam_faculty x
  join public.faculty f on f.id = x.faculty_id
  where x.exam_id = e.id
) ef on true
left join lateral (
  select array_agg(f.id order by f.name) as ids, array_agg(f.name order by f.name) as names
  from public.course_faculty x
  join public.faculty f on f.id = x.faculty_id
  where x.course_id = e.course_id
) cf on true;

revoke all on public.exam_details from anon, authenticated;
grant select on public.exam_details to service_role;

drop function public.cr_save_course(bigint, text, text, text[], bigint[], jsonb);
drop function public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, text, bigint[], uuid, uuid);

create or replace function public.cr_save_course(
  p_course_id bigint,
  p_code text,
  p_title text,
  p_aliases text[],
  p_faculty_ids bigint[],
  p_faculty_exception_note text
)
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  v_code text := public.normalize_course_code(p_code);
  v_type text;
  v_title text := btrim(coalesce(p_title, ''));
  v_note text := nullif(btrim(coalesce(p_faculty_exception_note, '')), '');
  v_faculty bigint[] := coalesce((select array_agg(distinct x) from unnest(p_faculty_ids) x where x is not null), '{}');
  v_aliases text[] := coalesce((
    select array_agg(distinct btrim(a)) from unnest(p_aliases) a where nullif(btrim(a), '') is not null
  ), '{}');
  v_count int;
  v_id bigint;
begin
  if v_code is null then
    raise exception 'AICR:invalid_course_code:"%" is not a valid course code (expected e.g. CSE-415)', p_code using errcode = '22023';
  end if;
  v_type := public.course_type_for_code(v_code);

  if char_length(v_title) < 2 then
    raise exception 'AICR:invalid_title:Course title is required' using errcode = '22023';
  end if;

  if exists (
    select 1 from unnest(v_faculty) fid
    where not exists (select 1 from public.faculty f where f.id = fid and f.archived_at is null)
  ) then
    raise exception 'AICR:unknown_faculty:One or more selected faculty members do not exist' using errcode = '22023';
  end if;

  -- Theoretical courses always have exactly two course teachers; Sessional courses any number.
  v_count := cardinality(v_faculty);
  if v_type = 'Theoretical' and v_count <> 2 then
    raise exception 'AICR:faculty_count:Theoretical courses need exactly 2 course teachers (got %).', v_count
      using errcode = '22023';
  end if;
  v_note := null;  -- exception notes are no longer used

  if p_course_id is null then
    insert into public.courses (code, title, aliases, faculty_exception_note)
    values (v_code, v_title, v_aliases, v_note)
    returning id into v_id;
  else
    update public.courses
       set code = v_code, title = v_title, aliases = v_aliases, faculty_exception_note = v_note
     where id = p_course_id and archived_at is null
    returning id into v_id;
    if v_id is null then
      raise exception 'AICR:not_found:Course % was not found or is archived', p_course_id using errcode = 'P0002';
    end if;
  end if;

  delete from public.course_faculty where course_id = v_id and faculty_id <> all (v_faculty);
  insert into public.course_faculty (course_id, faculty_id)
  select v_id, fid from unnest(v_faculty) fid
  on conflict do nothing;

  return v_id;
end
$$;

create or replace function public.cr_save_exam(
  p_exam_id bigint,
  p_course_id bigint,
  p_exam_type text,
  p_exam_date date,
  p_exam_time time,
  p_section text,
  p_syllabus text,
  p_venue text,
  p_remarks text,
  p_notes_link text,
  p_faculty_ids bigint[],
  p_client_request_id uuid,
  p_user_id uuid
)
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  v_id bigint;
  v_existing public.exams%rowtype;
  v_section text := nullif(upper(btrim(coalesce(p_section, ''))), '');
  v_faculty bigint[] := coalesce((select array_agg(distinct x order by x) from unnest(p_faculty_ids) x where x is not null), '{}');
  v_current_faculty bigint[];
begin
  if p_exam_id is null and p_client_request_id is not null then
    select id into v_id from public.exams where client_request_id = p_client_request_id;
    if v_id is not null then
      return v_id;  -- same submission retried: return the row it already created
    end if;
  end if;

  if p_exam_date is null then
    raise exception 'AICR:invalid_date:Exam date is required' using errcode = '22023';
  end if;

  if p_exam_id is not null then
    select * into v_existing from public.exams where id = p_exam_id for update;
    if not found then
      raise exception 'AICR:not_found:Exam % was not found', p_exam_id using errcode = 'P0002';
    end if;
  end if;

  if not exists (
    select 1 from public.courses c
    where c.id = p_course_id
      and (c.archived_at is null or (p_exam_id is not null and v_existing.course_id = p_course_id))
  ) then
    raise exception 'AICR:invalid_course:The selected course does not exist or is no longer active' using errcode = '22023';
  end if;

  -- Theoretical exams (CTs, Mid) are held on the same day for every section.
  if (select c.course_type from public.courses c where c.id = p_course_id) = 'Theoretical' then
    v_section := null;
  end if;

  select coalesce(array_agg(faculty_id order by faculty_id), '{}') into v_current_faculty
  from public.exam_faculty where exam_id = p_exam_id;

  if (p_exam_id is null or v_faculty is distinct from v_current_faculty or v_existing.course_id <> p_course_id)
     and exists (
       select 1 from unnest(v_faculty) fid
       where not exists (select 1 from public.course_faculty cf where cf.course_id = p_course_id and cf.faculty_id = fid)
     ) then
    raise exception 'AICR:invalid_faculty:Selected faculty must be assigned to the selected course' using errcode = '22023';
  end if;

  if exists (
    select 1 from public.exams e
    where e.course_id = p_course_id
      and e.exam_type = p_exam_type
      and e.exam_date = p_exam_date
      and e.section is not distinct from v_section
      and (p_exam_id is null or e.id <> p_exam_id)
  ) then
    raise exception 'AICR:duplicate:This course already has a % on % for this section', p_exam_type, p_exam_date
      using errcode = '23505';
  end if;

  if p_exam_id is null then
    insert into public.exams (
      course_id, exam_type, exam_date, exam_time, section, syllabus, venue, remarks, notes_link,
      client_request_id, created_by, updated_by
    ) values (
      p_course_id, p_exam_type, p_exam_date, p_exam_time, v_section,
      nullif(btrim(p_syllabus), ''), nullif(btrim(p_venue), ''), nullif(btrim(p_remarks), ''), nullif(btrim(p_notes_link), ''),
      p_client_request_id, p_user_id, p_user_id
    )
    returning id into v_id;
  else
    update public.exams set
      course_id = p_course_id,
      exam_type = p_exam_type,
      exam_date = p_exam_date,
      exam_time = p_exam_time,
      section = v_section,
      syllabus = nullif(btrim(p_syllabus), ''),
      venue = nullif(btrim(p_venue), ''),
      remarks = nullif(btrim(p_remarks), ''),
      notes_link = nullif(btrim(p_notes_link), ''),
      updated_by = p_user_id
    where id = p_exam_id
    returning id into v_id;
  end if;

  delete from public.exam_faculty where exam_id = v_id and faculty_id <> all (v_faculty);
  insert into public.exam_faculty (exam_id, faculty_id)
  select v_id, fid from unnest(v_faculty) fid
  on conflict do nothing;

  return v_id;
end
$$;

revoke execute on function
  public.cr_save_course(bigint, text, text, text[], bigint[], text),
  public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, bigint[], uuid, uuid)
  from public, anon, authenticated;
grant execute on function
  public.cr_save_course(bigint, text, text, text[], bigint[], text),
  public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, bigint[], uuid, uuid)
  to service_role;

drop trigger exams_theory_whole_class on public.exams;
create or replace function public.exams_theory_whole_class()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (select c.course_type from public.courses c where c.id = new.course_id) = 'Theoretical' then
    new.section := null;
  end if;
  return new;
end
$$;

create trigger exams_theory_whole_class before insert or update of course_id, section on public.exams
  for each row execute function public.exams_theory_whole_class();

alter table public.exams drop column course_section;
alter table public.course_faculty drop column sections;
comment on column public.exams.section is 'Class section (e.g. A, B) for Sessional exams. NULL means the whole class; always NULL for Theoretical courses.';
