# AI CR — Developer Guide

Technical documentation (architecture, setup, tests, deployment). The student and CR guide is in [README.md](../README.md).

Class-representative assistant for many classes: a **Discord bot** where each channel is one class, a read-only
exam list per class, and a CR editor per class. Everything reads the same Supabase data.

## Deployment

- FastAPI backend + Discord interactions endpoint + scheduler (Render): https://ai-cr.onrender.com/
- Web app (Vercel production domain): https://ai-cr-three.vercel.app/
  - `/c/<view_key>` — a class's read-only exam list (no sign-in; calls only `GET /api/public/classes/<view_key>/*`)
  - `/cr/#t=<token>` — CR editor for one class, opened from the private link `/manage` sends

## Architecture

```
Discord ──slash command──► POST /discord/interactions (discord_bot/interactions.py)
          (Ed25519-signed)    │ verify signature → reply "thinking…" (ephemeral) within 3 s
                              │ background task: channel → class → updates.py / Chatbot.answer
                              └─► PATCH interaction webhook (the answer; no bot token needed)

Scheduler (scheduler.py, every 60 s in the web process; or POST /cron/tick)
   Friday 18:00 next-week update · 20:00 day-before reminder
   claim in class_notifications ──► POST /channels/<id>/messages (bot token)

Exam list (/c/<key>) ──no auth, read-only──► /api/public/classes/<key>/* (public_api.py, 30 s cache)
CR editor (/cr/)    ──Bearer editor token──► /api/* (cr_api.py): every route scoped to the token's class
                                             /api/discord/post* → the class channel

                    all of the above ──► Supabase (PostgREST, secret key): classes · courses · faculty ·
                                         exams · exam_details view · class-scoped RPCs
```

The bot uses only Discord's HTTP APIs — no gateway connection, so it runs inside the existing FastAPI service.

### Classes, links and who is a CR

- **One class = one Discord channel** (`classes.discord_channel_id`, unique). A command in a thread counts as its
  parent channel. Courses and faculty carry `class_id`; exams belong to a class through their course.
- **CR** = a member with Administrator, Manage Server or Manage Channels in that channel (Discord sends the computed
  `member.permissions` with every interaction), or with the class's `cr_role_id`. `/setup` needs Manage Channels.
- **Board link** `SITE_URL/c/<view_key>` — `view_key` is a random uuid per class; anyone with it can read that class.
- **Editor link** `SITE_URL/cr/#t=<token>` (`links.py`). `/manage` checks the member is a CR and sends the link
  ephemerally. The token is `e1.<class_id>.<discord_user_id>.<expiry>.<HMAC-SHA256>` signed with
  `EDITOR_LINK_SECRET`, valid `EDITOR_LINK_HOURS` (default 12). Nothing is stored; rotating the secret revokes all
  links. It is carried in the URL fragment (never sent to servers or in Referer), moved to `sessionStorage` and
  removed from the address bar on load (`AI_CR/src/lib/session.js`).
- `auth.require_cr` validates the token and loads the class; every `cr_api` route uses `user.class_id`. A course or
  exam of another class is reported as not found. The write RPCs take `p_class_id` and check it again.

### Data model (`supabase/migrations/`)

| Object | Purpose |
|---|---|
| `classes` | One per Discord channel: name, guild/channel/CR-role ids (text: snowflakes exceed JS integers), `view_key`, `auto_updates`. |
| `class_notifications` | Automatic posts already claimed per class (`weekly:<sunday>`, `eve:<exam day>`), status `sending`/`sent`/`failed`. |
| `courses` | `class_id`, code, title, aliases. `course_type` is a generated column from the code (odd = Theoretical, even = Sessional). Active = `archived_at is null`; one active row per code **per class**. |
| `faculty`, `course_faculty` | A faculty directory per class (names unique per class), many-to-many with courses; a trigger refuses linking a teacher of another class. `course_faculty.sections` lists the course sections (A, B) a teacher takes on a Theoretical course; empty for Sessional. |
| `exam_types` | The single list of allowed exam types per course type (CT 1, CT 2, Mid, CT 3; Project Update, Evaluation, Online Exam, Project Presentation, Lab Test). Shared by all classes. |
| `exams`, `exam_faculty` | One row per assessment: `exam_date` (date) + optional `exam_time`, Asia/Dhaka local; `section` = class section, Sessional only (NULL = whole class); `course_section` = A/B, Theoretical only (NULL = both course sections). The `exams_theory_whole_class` trigger keeps each column NULL for the other course type. Syllabus, venue, remarks, notes link. `created_by_discord`/`updated_by_discord` = Discord user id of the CR. `exam_faculty` is used for Sessional exams only. |
| `exam_details` (view) | Read model used by the bot, updates and editor; includes `class_id`. For Theoretical exams `faculty_*` are the teachers of the exam's course section(s), and `section_faculty` is `[{"section", "name"}]`. |
| `cr_save_course`, `cr_save_exam`, `cr_remove_course`, `cr_remove_faculty` | Transactional write RPCs, all taking `p_class_id` first; validation is repeated in triggers. |
| `cr_members` | Unused since the Discord switch (kept for rollback). |

The original flat `"Exams"` table is left untouched; its rows were copied into the new tables.

### Business rules

- **Course code**: 2–5 letters + 3–4 digits (`CSE-415`, `cse 415`, `GEEM433` are all accepted and stored as `CSE-415`). The type comes from the **last digit of the number**: odd → Theoretical, even → Sessional. Codes such as `CSE-415A` or `415` are rejected instead of guessed. The rule exists in `academic.py`, `AI_CR/src/lib/academic.js` and SQL (`course_type_for_code`); keep the three in sync.
- **Course sections (Theoretical)**: every Theoretical course has course sections A and B with one course teacher each; the same teacher may take both (so 1 or 2 distinct teachers). Sessional courses have no course sections and any number of teachers.
- **Theoretical exams** are posted for course section A, B or both. The teacher is derived from the section (exam-level picks are ignored). Both sections sit an exam together, so `cr_save_exam` moves the other section's record of the same exam type to the saved date/time. Only one record per course section per exam type (whatever the date).
- **Class sections**: only Sessional exams have one, and Sessional exams of different class sections may be at different times. The bot's `section` filter matches the class section or the course section (NULL rows always match).
- **Date/time input**: the editor uses dropdowns (`AI_CR/src/lib/pickers.js`) — dates from 14 days back to 180 days ahead, times 7 AM–11 PM in 5-minute steps; an existing value outside those lists is still offered.
- **Exam types** must match the course type — enforced by the API and by a database trigger.
- **Removing a course** that has exams archives it (history kept); a course without exams is deleted.
- **Duplicate saves**: the exam form sends a `client_request_id`; retries return the same row. A second Sessional exam with the same course, type, date and class section is rejected; for Theoretical, see above.

### Discord updates (`updates.py`)

Shared by the slash commands, the editor's Post buttons and the scheduler. Deterministic text from `exam_details`
rows; CR-typed text is escaped so it can't become Discord markdown, every message is sent with
`allowed_mentions: {parse: []}` (no `@everyone`/role pings), notes links are wrapped in `<…>` (no previews), and
messages are split under 2000 characters on record boundaries.

- `/this-week-update`: today → Thursday; Friday/Saturday says the week is over and shows next week.
- `/next-week-update`: next Sunday → Thursday.
- `/next-exam-day-update`: the earliest day with an exam that hasn't started (today's exams count until their start time), and **all** exams on it.
- `/next-exam-notes`: the same day, notes links only.
- Who sees it: for a CR (see above) the four update commands post the update in the channel (or thread) they were
  run in via the bot token, with a 20 s per-channel cooldown, and the CR gets a private confirmation; for everyone
  else the answer is ephemeral. The editor posts only next-exam-day/notes and single exams (`/api/discord/post*`);
  week updates come from Discord.
- Day-before reminder: all exams on tomorrow's date; skipped (and not claimed) when there are none.

### Scheduler (`scheduler.py`)

`run_tick()` runs every `TICK_SECONDS` (60) in the web process (`main.py` lifespan) when `DISCORD_BOT_TOKEN` is set
and `SCHEDULER_ENABLED` isn't `0`. For each class with a channel and `auto_updates`:

- weekly: due on Friday from `WEEKLY_UPDATE_TIME` (18:00) and all of Saturday (catch-up), key `weekly:<next Sunday>`;
- reminder: due from `EXAM_REMINDER_TIME` (20:00) until midnight, key `eve:<tomorrow>`, only if tomorrow has exams.

Each post is claimed with an `insert … on conflict do nothing` before sending, so it goes out once per class even
across restarts or several instances. Temporary Discord errors release the claim (retried next tick); permanent
ones (no channel access) are marked `failed`. On Render's free plan the service must be awake at those times — keep
the external pinger, or point an external cron at `POST /cron/tick` with header `X-Cron-Secret: $CRON_SECRET`.

### Joining and leaving servers

- **Joined** (`discord_bot/events.py`, `POST /discord/events`): Discord's signed `APPLICATION_AUTHORIZED` webhook
  event (guild install) triggers a short setup guide, posted in the server's system channel or else the first text
  channel the bot can write in. Answered with an empty 204; the message is sent in the background.
- **Removed**: HTTP-only bots get no event for this (`APPLICATION_DEAUTHORIZED` carries no server), so every
  `RECONCILE_SECONDS` (300) the scheduler lists the bot's servers (`GET /users/@me/guilds`) and deactivates
  (`classes.archived_at = now()`) every active class in a server it's no longer in. A failed listing deactivates
  nothing. A scheduled post failing with Unknown Channel (channel deleted) deactivates that class too.
- **Deactivated** classes keep all their data; board and editor links answer "no longer active" and nothing is
  posted. `/setup` in the same channel reactivates the class (`reactivate_class`) instead of creating a new one.

### Student agent (`Chatbot/`, used by `/ask`) — no AI service

Nothing in the bot calls an AI/LLM API (the OpenAI integration was removed on 2026-10-16).

1. Load the class's course catalog from Supabase (cached per class ≤ `CATALOG_TTL_SECONDS`, default 60 s; cleared instantly after any CR write to that class).
2. A rule-based parser (`intent.heuristic_parse`) extracts exam types, the kind of time range ("next week", "tomorrow", explicit dates, "Sunday to Thursday"…), section and requested fields; course mentions are found by scanning the message against the catalog.
3. Mentions are resolved deterministically against the class's catalog: code → exact title/alias → acronym → department prefix → word match → fuzzy. Several plausible courses → the bot asks which one.
4. Dates are computed in Python for Asia/Dhaka, then **one** filtered, sorted `exam_details` query runs, always filtered by `class_id`.
5. The reply is formatted from the rows (nothing generated), split at record boundaries under Discord's 2000-character limit.

Database failures are reported as such, never as "no exams".

**Weeks**: the academic week is Sunday–Thursday. Today is always taken in Asia/Dhaka.

## Setting up the Discord bot

1. **Create the application**: https://discord.com/developers/applications → **New Application**.
2. **General Information**: copy the **Application ID** → `DISCORD_APPLICATION_ID` and the **Public Key** →
   `DISCORD_PUBLIC_KEY`.
3. **Bot**: **Reset Token**, copy it → `DISCORD_BOT_TOKEN` (secret). No privileged gateway intents are needed
   (leave Message Content, Server Members and Presence off).
4. **Installation**: Installation Contexts → **Guild Install** only. Default install settings for Guild Install:
   scopes `applications.commands` and `bot`; permissions **View Channels**, **Send Messages**,
   **Send Messages in Threads**, **Embed Links**. Install link:
   https://discord.com/oauth2/authorize?client_id=1560680277808910479 (**Bot** → **Public Bot** on lets anyone use it).
5. **Deploy the backend** with the env vars below, then in **General Information** set
   **Interactions Endpoint URL** to `https://ai-cr.onrender.com/discord/interactions` and save. Discord sends a
   signed PING and an unsigned test request; saving succeeds only if both are answered correctly.
   For the welcome message: **Webhooks** → **Endpoint URL** `https://ai-cr.onrender.com/discord/events`, turn
   **Events** on, tick **Application Authorized**, save.
6. **Register the slash commands** (again whenever `discord_bot/commands.py` changes):
   ```bash
   env/Scripts/python scripts/register_discord_commands.py               # all servers (may take a few minutes)
   env/Scripts/python scripts/register_discord_commands.py --guild <id>  # one server, instantly (testing)
   ```
7. In each class's channel: `/setup name:<class name>` (optionally `cr_role:`), then a CR runs `/manage`.

## Local development

```bash
# Backend (Python 3.13)
python -m venv env && env/Scripts/pip install -r requirements.txt   # env/bin/pip on macOS/Linux
cp .env.example .env            # fill in values
env/Scripts/uvicorn main:app --host 127.0.0.1 --port 8001

# Ask the bot from the terminal (class id from public.classes)
env/Scripts/python -m Chatbot.Chatbot --class-id 1 "what exams do we have next week?"

# Web app
cd AI_CR && npm install
cp .env.example .env.local      # fill in values
npm run dev
```

To try slash commands against a local backend, expose it with a tunnel (e.g. `cloudflared tunnel --url
http://127.0.0.1:8001`), set the tunnel URL + `/discord/interactions` as the Interactions Endpoint URL of a
separate test application, and register commands with `--guild`.

## Tests

The automated test suites were removed from the repository on 2026-10-16 (see git history before that date to
restore them: `git log --diff-filter=D -- tests`).

## Applying the database migration

**Status:** migrations up to `20261014074933_theory_course_sections.sql` are applied on the live project.
**`20261016120000_discord_classes.sql` is not applied yet.** It must go in together with the new backend: the new
code needs `classes`, and the old code breaks on the new RPC signatures.

1. Back up: Supabase dashboard → Database → Backups (or export `courses`, `faculty`, `exams` as CSV).
2. Run the migration in the SQL editor, or with the CLI: `supabase db push`.
3. Check: `select id, name, discord_channel_id from classes;` — if courses or faculty existed, they are in one
   class named "My class" with no channel.
4. Deploy the backend (Render) and the web app (Vercel).
5. In the Discord channel that should own the existing data:
   `/setup name:<class name> use_existing_data:True`. Other channels: plain `/setup`.

Rollback: `supabase/rollback/20261016120000_discord_classes_down.sql` (it refuses to run if two classes share a
course code or teacher name; export first), then redeploy the previous backend and web app.

Older rollbacks: `supabase/rollback/20261014074933_theory_course_sections_down.sql`,
`20261013150000_course_rules_update_down.sql`, `20261013031917_dynamic_course_config_down.sql`.
`20261013031653_legacy_exams_baseline.sql` only documents the original `"Exams"` table (a no-op on the live database).

## Deploying

**Order**: migration → backend (Render) → web app (Vercel) → Discord Interactions Endpoint URL → register commands.

Render (`main.py`; build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`).
Run a **single instance** for the in-process scheduler to be cheap (several are safe, just redundant). Environment:

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | yes | `https://<ref>.supabase.co/rest/v1` |
| `SUPABASE_API_KEY` | yes | Supabase **secret** key. Server only. |
| `DISCORD_APPLICATION_ID` | yes | Developer Portal → General Information. |
| `DISCORD_PUBLIC_KEY` | yes | Developer Portal → General Information. Used to verify every interaction. |
| `DISCORD_BOT_TOKEN` | yes | Developer Portal → Bot. Secret. Needed for channel posts; the scheduler is off without it. |
| `EDITOR_LINK_SECRET` | yes | ≥ 32 random characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Changing it revokes all editor links. |
| `SITE_URL` | yes | The web app's URL, e.g. `https://ai-cr-three.vercel.app` (used in the links the bot sends). |
| `EDITOR_LINK_HOURS` | optional | Default 12. |
| `WEEKLY_UPDATE_TIME`, `EXAM_REMINDER_TIME` | optional | `HH:MM` Asia/Dhaka; defaults 18:00 and 20:00. |
| `SCHEDULER_ENABLED` | optional | `0` turns the in-process scheduler off (e.g. when only an external cron should run it). |
| `CRON_SECRET` | optional | Enables `POST /cron/tick` (header `X-Cron-Secret`). |
| `CORS_ALLOW_ORIGINS` | recommended | Comma-separated web app origins. Unset = `*` (the editor uses bearer tokens, not cookies). |
| `CORS_ALLOW_ORIGIN_REGEX` | optional | e.g. `https://ai-.*-sabit166s-projects\.vercel\.app` for Vercel previews. |
| `CATALOG_TTL_SECONDS`, `PUBLIC_CACHE_SECONDS` | optional | Defaults 60 and 30. |

The old `PAGE_ACCESS_TOKEN`, `MESSENGER_APP_SECRET`, `MESSENGER_VERIFY_TOKEN`, `OPENAI_API_KEY`, `MODEL` and `GEMINI_API_KEY` are no longer read; remove them.

Vercel (`AI_CR/`):

| Variable | Notes |
|---|---|
| `VITE_API_BASE_URL` | `https://ai-cr.onrender.com` |

`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` and `VITE_MESSENGER_URL` are no longer used; remove them.
`AI_CR/vercel.json` rewrites `/c/<key>` to the exam list page and `/cr/*` to the editor, and sends
`Referrer-Policy: no-referrer` on the editor.

### Exam list (`GET /api/public/classes/<view_key>/*`)

`/api/public/classes/<key>` (class name), `/exams?scope=upcoming|past&course_id=&limit=&offset=` and `/courses`.
No sign-in, GET only, one class per key; unknown keys are 404. They return only student-facing fields
(`public_api.PUBLIC_EXAM_FIELDS`), the same information the bot gives anyone in the channel. Responses are cached
in-process for `PUBLIC_CACHE_SECONDS` and the cache is cleared on every CR write.

### Discord Activity (in-Discord mini app) — not done

The exam list and editor open in the browser from Discord link buttons. Running them as a Discord **Activity**
(embedded app) is possible later: it needs the Embedded App SDK, an OAuth2 code exchange endpoint, URL mappings for
the API through Discord's proxy, and the `guilds.members.read` scope to check roles. The current link-based flow
already needs no login, so this would mainly change where the page opens.

### Removed

- Facebook Messenger: the `/webhook` endpoints, `messenger_profile.py`, `scripts/setup_messenger.py` and the
  Meta App Review data-deletion page.
- Supabase Auth sign-in for CRs (`LoginScreen`, `@supabase/supabase-js`, `cr_members` checks).
- The single-class public endpoints `GET /api/public/exams` and `/api/public/courses`.
