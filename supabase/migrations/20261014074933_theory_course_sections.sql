-- Theory course sections (requested by the CRs, 2026-10-14):
--   * Every Theoretical course runs as two course sections, A and B. Each
--     section has one course teacher; the same teacher may take both, so a
--     Theoretical course has 1 or 2 distinct teachers (the "exactly 2" rule is gone).
--   * Course sections are NOT class sections. A Theoretical exam is posted for
--     course section A, B, or both (course_section NULL), never for a class
--     section; Sessional exams keep their optional class section.
--   * Both course sections sit a Theoretical exam at the same time: saving one
--     section's CT/Mid moves the other section's record of the same exam type to
--     the same date and time. Each course section has at most one record per
--     Theoretical exam type.
--   * A Theoretical exam's teachers are derived from its course section(s), so
--     Theoretical exams no longer store their own faculty picks.
--
-- course_faculty keeps one row per (course, teacher); `sections` lists the
-- course sections that teacher takes. Readers that only need "who teaches this
-- course" (bot faculty lookup, exam_details.faculty_*, faculty removal) are unchanged.
-- Existing Theoretical courses keep their teachers with no sections assigned;
-- the CR assigns sections in the dashboard (nothing is guessed here).

alter table public.course_faculty
  add column sections text[] not null default '{}'
  check (sections <@ array['A', 'B']::text[]);
comment on column public.course_faculty.sections is
  'Course sections (A, B) this teacher takes. Theoretical courses only; always empty for Sessional courses.';

-- cr_save_course: section assignments replace the faculty-count rule.
drop function public.cr_save_course(bigint, text, text, text[], bigint[], text);

create function public.cr_save_course(
  p_course_id bigint,
  p_code text,
  p_title text,
  p_aliases text[],
  p_faculty_ids bigint[],
  p_section_faculty jsonb  -- Theoretical: {"A": <faculty id>, "B": <faculty id>}; Sessional: {} or null
)
returns bigint
language plpgsql
set search_path = ''
as $$
declare
  v_code text := public.normalize_course_code(p_code);
  v_type text;
  v_title text := btrim(coalesce(p_title, ''));
  v_sections jsonb := coalesce(p_section_faculty, '{}'::jsonb);
  v_faculty bigint[];
  v_a bigint;
  v_b bigint;
  v_aliases text[] := coalesce((
    select array_agg(distinct btrim(a)) from unnest(p_aliases) a where nullif(btrim(a), '') is not null
  ), '{}');
  v_id bigint;
begin
  if v_code is null then
    raise exception 'AICR:invalid_course_code:"%" is not a valid course code (expected e.g. CSE-415)', p_code using errcode = '22023';
  end if;
  v_type := public.course_type_for_code(v_code);

  if char_length(v_title) < 2 then
    raise exception 'AICR:invalid_title:Course title is required' using errcode = '22023';
  end if;

  if jsonb_typeof(v_sections) <> 'object'
     or exists (select 1 from jsonb_each(v_sections) s where s.key not in ('A', 'B') or jsonb_typeof(s.value) <> 'number') then
    raise exception 'AICR:faculty_sections:Course sections must be given as {"A": <teacher>, "B": <teacher>}' using errcode = '22023';
  end if;

  if v_type = 'Theoretical' then
    -- One teacher per course section; the same teacher may take both.
    v_a := (v_sections ->> 'A')::bigint;
    v_b := (v_sections ->> 'B')::bigint;
    if v_a is null or v_b is null then
      raise exception 'AICR:faculty_sections:Theoretical courses need a course teacher for Section A and Section B' using errcode = '22023';
    end if;
    v_faculty := array(select distinct x from unnest(array[v_a, v_b]) x);
  else
    if v_sections <> '{}'::jsonb then
      raise exception 'AICR:faculty_sections:Sessional courses do not have course sections' using errcode = '22023';
    end if;
    v_faculty := coalesce((select array_agg(distinct x) from unnest(p_faculty_ids) x where x is not null), '{}');
  end if;

  if exists (
    select 1 from unnest(v_faculty) fid
    where not exists (select 1 from public.faculty f where f.id = fid and f.archived_at is null)
  ) then
    raise exception 'AICR:unknown_faculty:One or more selected faculty members do not exist' using errcode = '22023';
  end if;

  if p_course_id is null then
    insert into public.courses (code, title, aliases)
    values (v_code, v_title, v_aliases)
    returning id into v_id;
  else
    update public.courses
       set code = v_code, title = v_title, aliases = v_aliases, faculty_exception_note = null
     where id = p_course_id and archived_at is null
    returning id into v_id;
    if v_id is null then
      raise exception 'AICR:not_found:Course % was not found or is archived', p_course_id using errcode = 'P0002';
    end if;
  end if;

  delete from public.course_faculty where course_id = v_id and faculty_id <> all (v_faculty);
  insert into public.course_faculty (course_id, faculty_id, sections)
  select v_id, fid,
         array(select s from (values ('A', v_a), ('B', v_b)) t(s, f) where f = fid order by s)
  from unnest(v_faculty) fid
  on conflict (course_id, faculty_id) do update set sections = excluded.sections;

  return v_id;
end
$$;

revoke execute on function public.cr_save_course(bigint, text, text, text[], bigint[], jsonb) from public, anon, authenticated;
grant execute on function public.cr_save_course(bigint, text, text, text[], bigint[], jsonb) to service_role;

-- -----------------------------------------------------------------------------
-- Exams: course section for Theoretical exams.
-- -----------------------------------------------------------------------------
alter table public.exams
  add column course_section text check (course_section in ('A', 'B'));
comment on column public.exams.course_section is
  'Theoretical exams only: course section A or B; NULL means both course sections. Always NULL for Sessional exams.';
comment on column public.exams.section is
  'Class section (e.g. A, B) for Sessional exams. NULL means the whole class; always NULL for Theoretical courses (see course_section).';

create or replace function public.exams_theory_whole_class()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (select c.course_type from public.courses c where c.id = new.course_id) = 'Theoretical' then
    new.section := null;
  else
    new.course_section := null;
  end if;
  return new;
end
$$;

drop trigger exams_theory_whole_class on public.exams;
create trigger exams_theory_whole_class before insert or update of course_id, section, course_section on public.exams
  for each row execute function public.exams_theory_whole_class();

drop function public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, bigint[], uuid, uuid);

create function public.cr_save_exam(
  p_exam_id bigint,
  p_course_id bigint,
  p_exam_type text,
  p_exam_date date,
  p_exam_time time,
  p_section text,
  p_course_section text,
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
  v_theory boolean;
  v_section text := nullif(upper(btrim(coalesce(p_section, ''))), '');
  v_course_section text := nullif(upper(btrim(coalesce(p_course_section, ''))), '');
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

  v_theory := (select c.course_type from public.courses c where c.id = p_course_id) = 'Theoretical';

  if v_theory then
    -- Course section instead of class section; teachers come from the course section.
    v_section := null;
    v_faculty := '{}';
    if v_course_section is not null and v_course_section not in ('A', 'B') then
      raise exception 'AICR:invalid_course_section:Course section must be A, B or both' using errcode = '22023';
    end if;
    if exists (
      select 1 from public.exams e
      where e.course_id = p_course_id
        and e.exam_type = p_exam_type
        and (e.course_section is null or v_course_section is null or e.course_section = v_course_section)
        and (p_exam_id is null or e.id <> p_exam_id)
    ) then
      raise exception 'AICR:duplicate:This course already has a % for %. Edit that one instead.', p_exam_type,
        coalesce('Section ' || v_course_section, 'these sections')
        using errcode = '23505';
    end if;
  else
    v_course_section := null;
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

  if not v_theory and exists (
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
      course_id, exam_type, exam_date, exam_time, section, course_section, syllabus, venue, remarks, notes_link,
      client_request_id, created_by, updated_by
    ) values (
      p_course_id, p_exam_type, p_exam_date, p_exam_time, v_section, v_course_section,
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
      course_section = v_course_section,
      syllabus = nullif(btrim(p_syllabus), ''),
      venue = nullif(btrim(p_venue), ''),
      remarks = nullif(btrim(p_remarks), ''),
      notes_link = nullif(btrim(p_notes_link), ''),
      updated_by = p_user_id
    where id = p_exam_id
    returning id into v_id;
  end if;

  if v_theory then
    -- Both course sections sit the exam together: the other section's record follows.
    update public.exams e
       set exam_date = p_exam_date, exam_time = p_exam_time, updated_by = p_user_id
     where e.course_id = p_course_id
       and e.exam_type = p_exam_type
       and e.id <> v_id
       and (e.exam_date, e.exam_time) is distinct from (p_exam_date, p_exam_time);
  end if;

  delete from public.exam_faculty where exam_id = v_id and faculty_id <> all (v_faculty);
  insert into public.exam_faculty (exam_id, faculty_id)
  select v_id, fid from unnest(v_faculty) fid
  on conflict do nothing;

  return v_id;
end
$$;

revoke execute on function public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, text, bigint[], uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, text, bigint[], uuid, uuid)
  to service_role;

-- Existing Theoretical exams become "both sections". Their exam-level faculty picks are kept
-- (exam_details shows them as before) until the CR next saves the exam, which clears them.

-- exam_details: course_section, section-aware faculty, and section_faculty
-- ([{"section": "A", "name": "..."}, ...]) for Theoretical exams.
create or replace view public.exam_details
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
  e.updated_at,
  e.course_section,
  coalesce(sf.items, '[]'::jsonb) as section_faculty
from public.exams e
join public.courses c on c.id = e.course_id
left join lateral (
  select array_agg(f.id order by f.name) as ids, array_agg(f.name order by f.name) as names
  from public.exam_faculty x
  join public.faculty f on f.id = x.faculty_id
  where x.exam_id = e.id
) ef on true
left join lateral (
  -- A section-specific Theoretical exam is taken by that section's teacher only.
  select array_agg(f.id order by f.name) as ids, array_agg(f.name order by f.name) as names
  from public.course_faculty x
  join public.faculty f on f.id = x.faculty_id
  where x.course_id = e.course_id
    and (e.course_section is null or e.course_section = any (x.sections))
) cf on true
left join lateral (
  select jsonb_agg(jsonb_build_object('section', s.section, 'name', f.name) order by s.section) as items
  from public.course_faculty x
  cross join lateral unnest(x.sections) as s(section)
  join public.faculty f on f.id = x.faculty_id
  where x.course_id = e.course_id
    and (e.course_section is null or s.section = e.course_section)
) sf on true;

