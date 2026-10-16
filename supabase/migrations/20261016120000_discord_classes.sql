-- Discord bot, many classes (2026-10-16):
--   * Messenger is gone. The bot now lives in Discord, and each Discord channel
--     represents one class. Every course and faculty member belongs to a class;
--     exams belong to a class through their course.
--   * There are no dashboard accounts any more: the bot hands out a read-only
--     board link per class (classes.view_key) and short-lived signed editor
--     links to CRs (signed by the backend, nothing stored). cr_members is no
--     longer read; it is kept for rollback.
--   * class_notifications records the automatic posts (Friday next-week update,
--     day-before reminders) so each goes out once, even after a restart or with
--     several backend instances.
--
-- Existing data: if courses or faculty already exist, they are put in one class
-- with no channel yet. The first `/setup use_existing_data:True` in a Discord
-- channel links that class to the channel (see docs/DEVELOPER.md).
--
-- The write RPCs gain a leading p_class_id and refuse to touch another class's
-- rows, so the backend's own checks are backed up by the database.

create table public.classes (
  id bigint generated always as identity primary key,
  name text not null check (char_length(btrim(name)) between 2 and 100),
  discord_guild_id text check (discord_guild_id ~ '^[0-9]{5,25}$'),
  discord_channel_id text unique check (discord_channel_id ~ '^[0-9]{5,25}$'),
  cr_role_id text check (cr_role_id ~ '^[0-9]{5,25}$'),
  view_key uuid not null unique default gen_random_uuid(),
  auto_updates boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);
comment on table public.classes is 'One class = one Discord channel. Courses and faculty belong to a class; exams through their course.';
comment on column public.classes.view_key is 'Unguessable key in the read-only board link (/c/<view_key>) the bot shares in the channel.';
comment on column public.classes.cr_role_id is 'Discord role whose members count as CRs, in addition to members with Manage Channels.';
comment on column public.classes.auto_updates is 'Friday next-week update and day-before exam reminders in the channel.';

create trigger classes_set_updated_at before update on public.classes
  for each row execute function public.set_updated_at();

create table public.class_notifications (
  class_id bigint not null references public.classes (id) on delete cascade,
  key text not null check (char_length(key) between 1 and 100),
  status text not null default 'sending' check (status in ('sending', 'sent', 'failed')),
  detail text,
  created_at timestamptz not null default now(),
  primary key (class_id, key)
);
comment on table public.class_notifications is 'Automatic Discord posts already claimed per class (e.g. weekly:2026-10-18, eve:2026-10-19), so each is sent once.';

-- Existing rows go into one class that a channel can claim with /setup.
insert into public.classes (name)
select 'My class'
where exists (select 1 from public.courses) or exists (select 1 from public.faculty);

alter table public.courses add column class_id bigint references public.classes (id) on delete restrict;
alter table public.faculty add column class_id bigint references public.classes (id) on delete restrict;
update public.courses set class_id = (select min(id) from public.classes) where class_id is null;
update public.faculty set class_id = (select min(id) from public.classes) where class_id is null;
alter table public.courses alter column class_id set not null;
alter table public.faculty alter column class_id set not null;
create index courses_class_idx on public.courses (class_id);
create index faculty_class_idx on public.faculty (class_id);

-- Course codes and teacher names are unique within a class, not globally.
drop index public.courses_code_active_key;
create unique index courses_code_active_key on public.courses (class_id, code) where archived_at is null;
drop index public.faculty_name_active_key;
create unique index faculty_name_active_key on public.faculty (class_id, lower(btrim(name))) where archived_at is null;

-- Who saved an exam is now a Discord user id (a number), not a Supabase Auth uuid.
alter table public.exams add column created_by_discord text, add column updated_by_discord text;
comment on column public.exams.created_by_discord is 'Discord user id of the CR whose editor link created this exam.';

-- A course may only list teachers of its own class.
create or replace function public.course_faculty_same_class()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (select c.class_id from public.courses c where c.id = new.course_id)
     is distinct from (select f.class_id from public.faculty f where f.id = new.faculty_id) then
    raise exception 'AICR:unknown_faculty:That teacher belongs to another class' using errcode = '23514';
  end if;
  return new;
end
$$;

create trigger course_faculty_same_class before insert or update on public.course_faculty
  for each row execute function public.course_faculty_same_class();

-- -----------------------------------------------------------------------------
-- exam_details: + class_id (appended, so existing columns keep their positions)
-- -----------------------------------------------------------------------------
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
  coalesce(sf.items, '[]'::jsonb) as section_faculty,
  c.class_id
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

-- -----------------------------------------------------------------------------
-- Class-scoped write RPCs (replace the previous signatures)
-- -----------------------------------------------------------------------------
drop function public.cr_save_course(bigint, text, text, text[], bigint[], jsonb);
drop function public.cr_remove_course(bigint);
drop function public.cr_remove_faculty(bigint);
drop function public.cr_save_exam(bigint, bigint, text, date, time, text, text, text, text, text, text, bigint[], uuid, uuid);

create function public.cr_save_course(
  p_class_id bigint,
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
  if not exists (select 1 from public.classes k where k.id = p_class_id and k.archived_at is null) then
    raise exception 'AICR:not_found:Class % was not found', p_class_id using errcode = 'P0002';
  end if;
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
    where not exists (
      select 1 from public.faculty f where f.id = fid and f.archived_at is null and f.class_id = p_class_id
    )
  ) then
    raise exception 'AICR:unknown_faculty:One or more selected faculty members do not exist' using errcode = '22023';
  end if;

  if p_course_id is null then
    insert into public.courses (class_id, code, title, aliases)
    values (p_class_id, v_code, v_title, v_aliases)
    returning id into v_id;
  else
    update public.courses
       set code = v_code, title = v_title, aliases = v_aliases, faculty_exception_note = null
     where id = p_course_id and class_id = p_class_id and archived_at is null
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

create function public.cr_remove_course(p_class_id bigint, p_course_id bigint)
returns text
language plpgsql
set search_path = ''
as $$
begin
  if not exists (select 1 from public.courses where id = p_course_id and class_id = p_class_id) then
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

create function public.cr_remove_faculty(p_class_id bigint, p_faculty_id bigint)
returns text
language plpgsql
set search_path = ''
as $$
begin
  if not exists (select 1 from public.faculty where id = p_faculty_id and class_id = p_class_id) then
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

create function public.cr_save_exam(
  p_class_id bigint,
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
  p_actor text
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
    select e.id into v_id
      from public.exams e join public.courses c on c.id = e.course_id
     where e.client_request_id = p_client_request_id and c.class_id = p_class_id;
    if v_id is not null then
      return v_id;  -- same submission retried: return the row it already created
    end if;
  end if;

  if p_exam_date is null then
    raise exception 'AICR:invalid_date:Exam date is required' using errcode = '22023';
  end if;

  if p_exam_id is not null then
    select e.* into v_existing
      from public.exams e join public.courses c on c.id = e.course_id
     where e.id = p_exam_id and c.class_id = p_class_id
       for update of e;
    if not found then
      raise exception 'AICR:not_found:Exam % was not found', p_exam_id using errcode = 'P0002';
    end if;
  end if;

  if not exists (
    select 1 from public.courses c
    where c.id = p_course_id
      and c.class_id = p_class_id
      and (c.archived_at is null or (p_exam_id is not null and v_existing.course_id = p_course_id))
  ) then
    raise exception 'AICR:invalid_course:The selected course does not exist or is no longer active' using errcode = '22023';
  end if;

  v_theory := (select c.course_type from public.courses c where c.id = p_course_id) = 'Theoretical';

  if v_theory then
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
      client_request_id, created_by_discord, updated_by_discord
    ) values (
      p_course_id, p_exam_type, p_exam_date, p_exam_time, v_section, v_course_section,
      nullif(btrim(p_syllabus), ''), nullif(btrim(p_venue), ''), nullif(btrim(p_remarks), ''), nullif(btrim(p_notes_link), ''),
      p_client_request_id, p_actor, p_actor
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
      updated_by_discord = p_actor
    where id = p_exam_id
    returning id into v_id;
  end if;

  if v_theory then
    -- Both course sections sit the exam together: the other section's record follows.
    update public.exams e
       set exam_date = p_exam_date, exam_time = p_exam_time, updated_by_discord = p_actor
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

-- -----------------------------------------------------------------------------
-- Privileges: backend (service_role) only, as for the other tables.
-- -----------------------------------------------------------------------------
alter table public.classes enable row level security;
alter table public.class_notifications enable row level security;
revoke all on public.classes, public.class_notifications from anon, authenticated;
grant select, insert, update, delete on public.classes, public.class_notifications to service_role;
revoke all on public.exam_details from anon, authenticated;
grant select on public.exam_details to service_role;

revoke execute on function
  public.cr_save_course(bigint, bigint, text, text, text[], bigint[], jsonb),
  public.cr_remove_course(bigint, bigint),
  public.cr_remove_faculty(bigint, bigint),
  public.cr_save_exam(bigint, bigint, bigint, text, date, time, text, text, text, text, text, text, bigint[], uuid, text),
  public.course_faculty_same_class()
  from public, anon, authenticated;
grant execute on function
  public.cr_save_course(bigint, bigint, text, text, text[], bigint[], jsonb),
  public.cr_remove_course(bigint, bigint),
  public.cr_remove_faculty(bigint, bigint),
  public.cr_save_exam(bigint, bigint, bigint, text, date, time, text, text, text, text, text, text, bigint[], uuid, text)
  to service_role;

comment on table public.cr_members is 'Unused since 2026-10-16 (CRs are recognised in Discord). Kept for rollback.';
