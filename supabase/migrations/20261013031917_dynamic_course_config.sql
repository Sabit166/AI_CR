-- =============================================================================
-- AI_CR: dynamic course configuration, normalized exam records, CR allowlist.
--
-- Non-destructive: the legacy public."Exams" table is NOT altered or dropped
-- (apart from revoking direct anon/authenticated grants that RLS already
-- blocked). Its rows are copied into the new model below and stay available
-- for rollback.
--
-- All access to the new objects goes through the FastAPI backend, which uses
-- the Supabase secret (service_role) key. anon/authenticated have no grants,
-- and RLS is enabled with no policies, so the public REST API cannot read or
-- write these tables even with a valid user JWT.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Course-code rules (mirrored in academic.py and AI_CR/src/lib/academic.js)
--
-- Canonical code: 2-5 uppercase letters, a hyphen, 3-4 digits. e.g. CSE-415.
-- Input such as "cse 415", "GEEM433" or "CSE_415" normalizes to that form.
-- Course type comes from the parity of the numeric component's LAST digit:
--   odd  -> Theoretical,  even -> Sessional.
-- Anything that does not match (e.g. "CSE-415A", "415") is rejected rather than
-- guessed.
-- -----------------------------------------------------------------------------
create or replace function public.normalize_course_code(p_code text)
returns text
language sql
immutable
set search_path = ''
as $$
  select case
    when p_code ~* '^\s*[A-Z]{2,5}[\s_-]*[0-9]{3,4}\s*$'
      then upper(regexp_replace(p_code, '^\s*([A-Za-z]{2,5})[\s_-]*([0-9]{3,4})\s*$', '\1-\2'))
  end
$$;

create or replace function public.course_type_for_code(p_code text)
returns text
language sql
immutable
set search_path = ''
as $$
  select case
    when p_code ~ '^[A-Z]{2,5}-[0-9]{3,4}$'
      then case when right(p_code, 1)::int % 2 = 0 then 'Sessional' else 'Theoretical' end
  end
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end
$$;

-- -----------------------------------------------------------------------------
-- Tables
-- -----------------------------------------------------------------------------
create table public.faculty (
  id bigint generated always as identity primary key,
  name text not null check (char_length(btrim(name)) between 2 and 120),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);
comment on table public.faculty is 'Faculty directory, reused across courses. Archived instead of deleted when historical exams reference it.';
create unique index faculty_name_active_key on public.faculty (lower(btrim(name))) where archived_at is null;

create table public.courses (
  id bigint generated always as identity primary key,
  code text not null check (code ~ '^[A-Z]{2,5}-[0-9]{3,4}$'),
  title text not null check (char_length(btrim(title)) between 2 and 200),
  course_type text generated always as (public.course_type_for_code(code)) stored,
  aliases text[] not null default '{}',
  faculty_exception_note text check (faculty_exception_note is null or char_length(btrim(faculty_exception_note)) between 3 and 500),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);
comment on table public.courses is 'Courses configured by the CR. Active = archived_at is null. Archiving keeps historical exams intact.';
comment on column public.courses.course_type is 'Derived from code parity: odd = Theoretical, even = Sessional. Cannot be set independently.';
comment on column public.courses.faculty_exception_note is 'Required reason when the faculty count differs from the norm (2 for Theoretical, 3-4 for Sessional).';
create unique index courses_code_active_key on public.courses (code) where archived_at is null;

create table public.course_faculty (
  course_id bigint not null references public.courses (id) on delete cascade,
  faculty_id bigint not null references public.faculty (id) on delete restrict,
  primary key (course_id, faculty_id)
);
create index course_faculty_faculty_idx on public.course_faculty (faculty_id);

create table public.exam_types (
  name text primary key,
  course_type text not null check (course_type in ('Theoretical', 'Sessional')),
  sort_order int not null,
  is_legacy boolean not null default false
);
comment on table public.exam_types is 'Single source of truth for which exam types each course type allows. Legacy types are only accepted on rows imported from the old "Exams" table.';

insert into public.exam_types (name, course_type, sort_order, is_legacy) values
  ('CT 1', 'Theoretical', 10, false),
  ('CT 2', 'Theoretical', 20, false),
  ('CT 3', 'Theoretical', 30, false),
  ('Project Update', 'Sessional', 110, false),
  ('Evaluation', 'Sessional', 120, false),
  ('Online Exam', 'Sessional', 130, false),
  ('Project Presentation', 'Sessional', 140, false),
  ('Lab Test', 'Sessional', 150, false),
  ('Mid', 'Theoretical', 900, true);

create table public.exams (
  id bigint generated always as identity primary key,
  course_id bigint not null references public.courses (id) on delete restrict,
  exam_type text not null references public.exam_types (name) on update cascade,
  exam_date date not null,
  exam_time time,
  section text check (section is null or section ~ '^[A-Z0-9]{1,10}$'),
  syllabus text check (syllabus is null or char_length(syllabus) <= 10000),
  venue text check (venue is null or char_length(venue) <= 200),
  remarks text check (remarks is null or char_length(remarks) <= 2000),
  notes_link text check (notes_link is null or (notes_link ~* '^https?://\S+$' and char_length(notes_link) <= 1000)),
  legacy_teacher text,
  legacy_exam_id bigint unique,
  client_request_id uuid unique,
  created_by uuid,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
comment on table public.exams is 'One row per scheduled assessment. exam_date/exam_time are Asia/Dhaka local values.';
comment on column public.exams.section is 'Class section (e.g. A, B). NULL means the whole class.';
comment on column public.exams.legacy_teacher is 'Free-text teacher name copied from the legacy "Exams" table. Not linked to the faculty directory.';
comment on column public.exams.legacy_exam_id is 'id of the source row in the legacy "Exams" table, for traceability.';
comment on column public.exams.client_request_id is 'Idempotency key sent by the CR form so a double-tapped save cannot create two rows.';
create index exams_date_idx on public.exams (exam_date, exam_time);
create index exams_course_date_idx on public.exams (course_id, exam_date);

create table public.exam_faculty (
  exam_id bigint not null references public.exams (id) on delete cascade,
  faculty_id bigint not null references public.faculty (id) on delete restrict,
  primary key (exam_id, faculty_id)
);
create index exam_faculty_faculty_idx on public.exam_faculty (faculty_id);

create table public.cr_members (
  user_id uuid primary key references auth.users (id) on delete cascade,
  note text,
  created_at timestamptz not null default now()
);
comment on table public.cr_members is 'Supabase Auth users allowed to use the CR dashboard. Add rows manually (see README).';

create trigger faculty_set_updated_at before update on public.faculty
  for each row execute function public.set_updated_at();
create trigger courses_set_updated_at before update on public.courses
  for each row execute function public.set_updated_at();
create trigger exams_set_updated_at before update on public.exams
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- Integrity triggers
-- -----------------------------------------------------------------------------
create or replace function public.exams_validate_type()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_course_type text;
begin
  select c.course_type into v_course_type from public.courses c where c.id = new.course_id;

  if not exists (
    select 1 from public.exam_types t
    where t.name = new.exam_type
      and t.course_type = v_course_type
      and (not t.is_legacy or new.legacy_exam_id is not null)
  ) then
    raise exception 'AICR:invalid_exam_type:% is not a valid exam type for a % course', new.exam_type, v_course_type
      using errcode = '23514';
  end if;

  return new;
end
$$;

create trigger exams_validate_type before insert or update of course_id, exam_type on public.exams
  for each row execute function public.exams_validate_type();

create or replace function public.courses_guard_type_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if public.course_type_for_code(new.code) is distinct from public.course_type_for_code(old.code)
     and exists (select 1 from public.exams e where e.course_id = old.id) then
    raise exception 'AICR:course_type_locked:Changing % to % would change its course type, but it already has exam records', old.code, new.code
      using errcode = '23514';
  end if;
  return new;
end
$$;

create trigger courses_guard_type_change before update of code on public.courses
  for each row execute function public.courses_guard_type_change();

-- -----------------------------------------------------------------------------
-- Read model used by the student agent and the CR dashboard.
-- faculty_* prefers the faculty picked for that exam, then the legacy
-- free-text teacher, then the course's assigned faculty.
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- Write RPCs. Each runs in a single transaction, so a course and its faculty
-- (or an exam and its faculty) are saved together or not at all.
-- Errors are raised as 'AICR:<code>:<message>' so the backend can map them to
-- HTTP responses.
-- -----------------------------------------------------------------------------
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

  v_count := cardinality(v_faculty);
  if v_note is null and (
       (v_type = 'Theoretical' and v_count <> 2)
    or (v_type = 'Sessional' and v_count not between 3 and 4)
  ) then
    raise exception 'AICR:faculty_count:% courses need % faculty members (got %). Add an exception note to save anyway.',
      v_type, case when v_type = 'Theoretical' then '2' else '3 or 4' end, v_count
      using errcode = '22023';
  end if;

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

create or replace function public.cr_remove_course(p_course_id bigint)
returns text
language plpgsql
set search_path = ''
as $$
begin
  if not exists (select 1 from public.courses where id = p_course_id) then
    raise exception 'AICR:not_found:Course % was not found', p_course_id using errcode = 'P0002';
  end if;

  if exists (select 1 from public.exams where course_id = p_course_id) then
    update public.courses set archived_at = coalesce(archived_at, now()) where id = p_course_id;
    return 'archived';
  end if;

  delete from public.courses where id = p_course_id;
  return 'deleted';
end
$$;

create or replace function public.cr_remove_faculty(p_faculty_id bigint)
returns text
language plpgsql
set search_path = ''
as $$
begin
  if not exists (select 1 from public.faculty where id = p_faculty_id) then
    raise exception 'AICR:not_found:Faculty member % was not found', p_faculty_id using errcode = 'P0002';
  end if;

  if exists (
    select 1 from public.course_faculty cf
    join public.courses c on c.id = cf.course_id
    where cf.faculty_id = p_faculty_id and c.archived_at is null
  ) then
    raise exception 'AICR:in_use:This faculty member is assigned to an active course. Remove them from the course first.'
      using errcode = '23503';
  end if;

  if exists (select 1 from public.exam_faculty where faculty_id = p_faculty_id)
     or exists (select 1 from public.course_faculty where faculty_id = p_faculty_id) then
    update public.faculty set archived_at = coalesce(archived_at, now()) where id = p_faculty_id;
    return 'archived';
  end if;

  delete from public.faculty where id = p_faculty_id;
  return 'deleted';
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

-- -----------------------------------------------------------------------------
-- Privileges: backend (service_role) only.
-- -----------------------------------------------------------------------------
alter table public.faculty enable row level security;
alter table public.courses enable row level security;
alter table public.course_faculty enable row level security;
alter table public.exam_types enable row level security;
alter table public.exams enable row level security;
alter table public.exam_faculty enable row level security;
alter table public.cr_members enable row level security;

revoke all on public.faculty, public.courses, public.course_faculty, public.exam_types,
              public.exams, public.exam_faculty, public.cr_members, public.exam_details
  from anon, authenticated;
grant select, insert, update, delete on public.faculty, public.courses, public.course_faculty,
              public.exam_types, public.exams, public.exam_faculty, public.cr_members
  to service_role;
grant select on public.exam_details to service_role;

-- The legacy table was already unreadable through RLS; drop the leftover grants too.
revoke all on public."Exams" from anon, authenticated;

revoke execute on function
  public.cr_save_course(bigint, text, text, text[], bigint[], text),
  public.cr_remove_course(bigint),
  public.cr_remove_faculty(bigint),
  public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, bigint[], uuid, uuid)
  from public, anon, authenticated;
grant execute on function
  public.cr_save_course(bigint, text, text, text[], bigint[], text),
  public.cr_remove_course(bigint),
  public.cr_remove_faculty(bigint),
  public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, bigint[], uuid, uuid)
  to service_role;

-- -----------------------------------------------------------------------------
-- Backfill from the legacy "Exams" table.
--
-- * Courses: one per normalizable course code. Title = the most recent
--   non-empty title; other title spellings become aliases.
-- * Faculty: NOT created. The legacy free-text names contain variants of the
--   same person (e.g. "Major Nazmul" / "Maj Nazmul Hasan") that cannot be
--   merged safely. They are kept per exam in legacy_teacher; the CR assigns
--   real faculty in the dashboard.
-- * Exams: copied when the code normalizes and the type maps to a type valid
--   for that course. Anything else stays only in the legacy table and is
--   reported with a NOTICE.
-- -----------------------------------------------------------------------------
create function pg_temp.legacy_exam_type(p_type text)
returns text
language sql
immutable
as $$
  select case lower(regexp_replace(coalesce(p_type, ''), '[^A-Za-z0-9]', '', 'g'))
    when 'ct1' then 'CT 1' when 'ctone' then 'CT 1' when 'classtest1' then 'CT 1' when 'classtestone' then 'CT 1'
    when 'ct2' then 'CT 2' when 'cttwo' then 'CT 2' when 'classtest2' then 'CT 2' when 'classtesttwo' then 'CT 2'
    when 'ct3' then 'CT 3' when 'ctthree' then 'CT 3' when 'classtest3' then 'CT 3' when 'classtestthree' then 'CT 3'
    when 'projectupdate' then 'Project Update'
    when 'evaluation' then 'Evaluation'
    when 'onlineexam' then 'Online Exam'
    when 'projectpresentation' then 'Project Presentation'
    when 'labtest' then 'Lab Test'
    when 'mid' then 'Mid' when 'midterm' then 'Mid' when 'midexam' then 'Mid'
  end
$$;

with titled as (
  select public.normalize_course_code(e."Course Code") as code,
         nullif(btrim(e."Course Title"), '') as title,
         e."Exam Date" as exam_at,
         e.id
  from public."Exams" e
),
per_code as (
  select code,
         (array_agg(title order by exam_at desc nulls last, id desc) filter (where title is not null))[1] as title,
         array_agg(distinct title) filter (where title is not null) as all_titles
  from titled
  where code is not null
  group by code
)
insert into public.courses (code, title, aliases)
select p.code,
       coalesce(p.title, p.code),
       coalesce((select array_agg(t order by t) from unnest(p.all_titles) t where t <> p.title), '{}')
from per_code p
where not exists (select 1 from public.courses c where c.code = p.code and c.archived_at is null);

insert into public.exams (
  course_id, exam_type, exam_date, exam_time, section, syllabus, notes_link, legacy_teacher, legacy_exam_id
)
select c.id,
       m.exam_type,
       e."Exam Date"::date,
       nullif(e."Exam Date"::time, time '00:00'),
       case when upper(btrim(e."Class Section")) ~ '^[A-Z0-9]{1,10}$' then upper(btrim(e."Class Section")) end,
       nullif(btrim(e."Syllabus"), ''),
       case when btrim(e."Exam Notes Drive Link") ~* '^https?://\S+$' then btrim(e."Exam Notes Drive Link") end,
       nullif(btrim(e."Course Teacher"), ''),
       e.id
from public."Exams" e
cross join lateral (select pg_temp.legacy_exam_type(e."Exam Type") as exam_type) m
join public.courses c on c.code = public.normalize_course_code(e."Course Code") and c.archived_at is null
join public.exam_types t on t.name = m.exam_type and t.course_type = c.course_type
where e."Exam Date" is not null
on conflict (legacy_exam_id) do nothing;

do $$
declare
  v_skipped text;
begin
  select string_agg(format('id=%s (code=%L, type=%L, date=%s)', e.id, e."Course Code", e."Exam Type", e."Exam Date"), '; ')
    into v_skipped
  from public."Exams" e
  where not exists (select 1 from public.exams x where x.legacy_exam_id = e.id);

  if v_skipped is not null then
    raise notice 'Legacy "Exams" rows NOT copied (kept in the legacy table, review manually): %', v_skipped;
  end if;
end
$$;
