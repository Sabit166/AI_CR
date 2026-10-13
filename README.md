# AI CR

Class-representative assistant: a CR dashboard for configuring courses and posting exam
information, and a Facebook Messenger bot that answers students' exam questions from the
same Supabase data.

## Deployment

- FastAPI backend + Messenger webhook (Render): https://ai-cr.onrender.com/
- CR dashboard (Vercel): https://ai-e4mnoglc3-sabit166s-projects.vercel.app/

## Architecture

```
CR dashboard (React, AI_CR/) ──Supabase Auth token──► FastAPI /api/* (cr_api.py)
                                                         │  checks token + cr_members allowlist
                                                         ▼
Messenger ──► POST /webhook (main.py) ──► Chatbot.answer ──► Supabase (PostgREST, secret key)
                                            1 LLM call         courses · faculty · exams
                                            (intent only)      exam_details view · RPCs
```

### Data model (`supabase/migrations/`)

| Object | Purpose |
|---|---|
| `courses` | Code, title, aliases. `course_type` is a generated column from the code (odd = Theoretical, even = Sessional). Active = `archived_at is null`; one active row per code. |
| `faculty`, `course_faculty` | One faculty directory, many-to-many with courses. |
| `exam_types` | The single list of allowed exam types per course type (CT 1–3; Project Update, Evaluation, Online Exam, Project Presentation, Lab Test). `Mid` is kept only for imported legacy rows. |
| `exams`, `exam_faculty` | One row per assessment: `exam_date` (date) + optional `exam_time`, Asia/Dhaka local; optional section (NULL = whole class), syllabus, venue, remarks, notes link. |
| `exam_details` (view) | Read model used by the bot and dashboard. |
| `cr_save_course`, `cr_save_exam`, `cr_remove_course`, `cr_remove_faculty` | Transactional write RPCs; validation is repeated in triggers. |
| `cr_members` | Supabase Auth users allowed to use the dashboard. |

The original flat `"Exams"` table is left untouched; its rows were copied into the new tables.

### Business rules

- **Course code**: 2–5 letters + 3–4 digits (`CSE-415`, `cse 415`, `GEEM433` are all accepted and stored as `CSE-415`). The type comes from the **last digit of the number**: odd → Theoretical, even → Sessional. Codes such as `CSE-415A` or `415` are rejected instead of guessed. The rule exists in `academic.py`, `AI_CR/src/lib/academic.js` and SQL (`course_type_for_code`), with shared test vectors.
- **Faculty per course**: Theoretical 2, Sessional 3–4. A different count needs a short exception note (stored as `faculty_exception_note`).
- **Exam types** must match the course type — enforced by the API and by a database trigger.
- **Removing a course** that has exams archives it (history kept); a course without exams is deleted.
- **Duplicate saves**: the exam form sends a `client_request_id`; retries return the same row. A second exam with the same course, type, date and section is rejected.

### Student agent (`Chatbot/`)

1. Load the course catalog from Supabase (cached ≤ `CATALOG_TTL_SECONDS`, default 60 s; cleared instantly after any CR write).
2. **One** structured-output LLM call extracts intent: verbatim course/teacher mentions, exam types, kind of time range, requested fields. The prompt contains no course, teacher or date data.
3. Unambiguous time phrases ("next week", "this week", "tomorrow", explicit dates, "Sunday to Thursday") are detected by rules and override the LLM.
4. Mentions are resolved deterministically: code → exact title/alias → acronym → department prefix → word match → fuzzy. Several plausible courses → the bot asks which one (an exam type can settle it: "Database CT" can only be the theory course).
5. Dates are computed in Python for Asia/Dhaka, then **one** filtered, sorted `exam_details` query runs.
6. The reply is formatted from the rows (nothing generated), split at record boundaries under Messenger's 2000-character limit.

If the LLM is unavailable a rule-based parser takes over. Database failures are reported as such, never as "no exams".

**Weeks**: the academic week is Sunday–Thursday. "This week" = today → Thursday (on Friday/Saturday the bot says the week is over and shows next week). "Next week" = the following Sunday–Thursday. Today is always taken in Asia/Dhaka.

## Local development

```bash
# Backend (Python 3.13)
python -m venv env && env/Scripts/pip install -r requirements-dev.txt   # env/bin/pip on macOS/Linux
cp .env.example .env            # fill in values
env/Scripts/uvicorn main:app --host 127.0.0.1 --port 8001

# Ask the bot from the terminal
env/Scripts/python -m Chatbot.Chatbot "what exams do we have next week?"

# Dashboard
cd AI_CR && npm install
cp .env.example .env.local      # fill in values
npm run dev
```

## Tests

```bash
# Unit + API tests (no network)
env/Scripts/python -m pytest

# Integration tests: real migrations in an isolated Postgres + PostgREST (Docker)
docker compose -f tests/db/docker-compose.yml up -d --wait
env/Scripts/python -m pytest tests/integration
docker compose -f tests/db/docker-compose.yml down -v

# Frontend
cd AI_CR && npm run lint && npm test && npm run build

# Mobile UI end-to-end (needs the Docker stack above and Google Chrome)
env/Scripts/python tests/e2e/server.py                 # repo root, port 8011
cd AI_CR && npm run e2e:build && npm run e2e:preview    # port 4179
cd AI_CR && npm run e2e
```

Tests never touch Supabase: `tests/conftest.py` pins harmless connection settings.

## Applying the database migration

**Status:** both migrations were applied to the live project on 2026-10-13 (versions match the
file names in `supabase/migrations/`). All 6 legacy rows were copied. The steps below are for
a fresh project or for reference; step 5 (CR account) still has to be done once.

`supabase/migrations/20261013031917_dynamic_course_config.sql` is the real change;
`20261013031653_legacy_exams_baseline.sql` only documents the existing table (a no-op on the live database).

1. Back up: Supabase dashboard → Database → Backups, or export the `Exams` table as CSV.
2. Run the migration in the SQL editor, or with the CLI: `supabase db push`.
3. Read the NOTICE output: any legacy rows that could not be copied are listed by id and stay in `"Exams"`.
4. Check: `select * from exam_details order by exam_date;`
5. Create the CR account: Authentication → Users → **Add user** (email + password). Then:
   ```sql
   insert into public.cr_members (user_id, note)
   select id, 'Class representative' from auth.users where email = 'cr@example.com';
   ```
6. Recommended: Authentication → Providers → Email → turn off **Allow new users to sign up**. (Even if someone signs up, they are not in `cr_members` and get 403.)

The legacy teacher names are kept per exam (`legacy_teacher`) but not turned into faculty records, because variants such as "Major Nazmul" / "Maj Nazmul Hasan" can't be merged safely. Add faculty and assign them to courses in the dashboard.

### Rollback

- **Application**: redeploy the previous commit on Render/Vercel. The old code only uses the untouched `"Exams"` table.
- **Database**: `supabase/rollback/20261013031917_dynamic_course_config_down.sql` drops the new objects. Exams created after the migration exist only in `public.exams`; export them first.

## Deploying

**Order**: migration → backend (Render) → dashboard (Vercel).

Render (`main.py`; build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`) — unchanged commands. Environment:

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | yes | `https://<ref>.supabase.co/rest/v1` (as before) |
| `SUPABASE_API_KEY` | yes | Supabase **secret** key. Server only. |
| `OPENAI_API_KEY`, `MODEL` | yes | As before. Without them the rule-based parser is used. |
| `PAGE_ACCESS_TOKEN` | yes | As before. |
| `MESSENGER_APP_SECRET` | recommended | Facebook App Secret. When set, webhook calls must carry a valid `X-Hub-Signature-256`. |
| `MESSENGER_VERIFY_TOKEN` | optional | Defaults to the previous hard-coded token. |
| `CORS_ALLOW_ORIGINS` | recommended | Comma-separated dashboard origins. Unset = `*` (auth uses bearer tokens, not cookies). |
| `CORS_ALLOW_ORIGIN_REGEX` | optional | e.g. `https://ai-.*-sabit166s-projects\.vercel\.app` for Vercel previews. |
| `CATALOG_TTL_SECONDS` | optional | Default 60. |

Vercel (`AI_CR/`):

| Variable | Notes |
|---|---|
| `VITE_API_BASE_URL` | `https://ai-cr.onrender.com` |
| `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Publishable (anon) key — safe in the browser; it grants no table access. Never put the secret key here. |

### Removed

The unauthenticated `GET/POST/PATCH/DELETE /exams` endpoints are gone (anyone could edit or delete exams). The dashboard now uses the authenticated `/api/*` routes.
