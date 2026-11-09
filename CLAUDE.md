# Personal Gym — Project Context

## Git workflow

- `main` is the only working and publishing branch. Make commits directly on `main` and push only to `origin/main`; do not create or use feature branches or pull-request branches for this project.
- Before pushing, verify the relevant changes and confirm that the push is a normal fast-forward. Never force-push or overwrite unrelated local changes. If `origin/main` has moved, stop and reconcile safely.

## Purpose

Private single-user training PWA. Product requirements live in `SPEC.md`; architecture and implementation plan live under `docs/superpowers/`.

## Architecture

```text
docs/ PWA (after design approval)
        ↓ Bearer API key
app.py Flask API (Railway)
        ├─ training.py → deterministic published workout plan
        ├─ operations.py → idempotent writes
        ├─ metrics.py → progress calculations
        ├─ db.py → Supabase
        └─ gpt.py → validated weekly review only
```

## Safety boundary

- Exercise selection and workout construction are deterministic and never delegated to AI.
- New workouts start without a pre-workout or next-day check-in. The retired rules and historical answers remain readable for compatibility, but they do not control new plans.
- Only active exercise cards with `review_status=allowed` may be included in a program. The activation SQL and database trigger enforce this invariant.
- AI may summarize saved facts and suggest IDs from the approved library. It cannot add exercises, diagnose, or override a blocked workout.
- Real medical data, exports, database backups, and secrets do not belong in Git.

## Production rollout

Apply database files in this order:

1. `supabase/schema.sql` twice;
2. `supabase/seed_production.sql`;
3. `supabase/activate_pilot_program.sql`.

For a fresh installation, the repeatable pilot migration approves 10 pilot exercise cards, blocks 5 excluded exercises, sets the rest to `needs_review`, and activates sessions on Monday and Wednesday only. For an existing three-session pilot, use `supabase/remove_scheduled_cardio.sql` to preserve manual catalog changes and historical workouts. Ordinary walking is not a scheduled workout.

After the pilot migration, apply `supabase/multiple_programs.sql` twice before using program selection, editable weekdays or date overrides.

## Checks

```bash
python3 -m pytest -q
python3 -m py_compile app.py db.py training.py operations.py metrics.py gpt.py jobs.py
npm test
node --check docs/app.js
```

## Hosting and operations

| Piece | Where |
|---|---|
| PWA | GitHub Pages, `main` → `/docs`, `https://demonk03.github.io/personal_gym/` |
| API | Railway, `https://personalgym-production.up.railway.app` |
| Database | Supabase project `personal_gym`, region `eu-central-1` (ref in the Railway env, not here) |

Frontend and backend deploy separately: pushing to `main` republishes Pages, but the
Railway service needs its own deploy. After a backend change, confirm Railway picked
up the commit.

Both the database and the API sleep when unused, and each failure looks different:

- Supabase pauses the project after about a week of inactivity. Every query then fails
  and `app.py` turns it into a generic 500 "Временная ошибка сервиса". Restoring is only
  possible from the Supabase dashboard; the MCP tools cannot unpause a project.
- Railway puts the service to sleep; the first request wakes it and can take a minute.
  Warm up through `/api/health`, which touches no database. Waking through
  `/api/bootstrap` is what produced false "Сервер не проснулся" reports.

The generic 500 hides the real cause by design — the traceback goes to the Railway logs
via `app.logger.exception`, so read them before guessing.

The Railway domain may be unreachable from a Russian ISP: `personalgym-production`
resolves to a blocked IP while `tenniscoach-production` on a neighbouring IP answers
normally. A TLS handshake timeout therefore means "blocked here", not "service down" —
check under VPN before concluding anything.

Tennis Coach shares the `Oura` Supabase project with the health tracker, which is why it
never sleeps: the Fitbit sync keeps that instance warm. Personal Gym sits on its own
instance with no such traffic.

## Read performance

Program reads are batched on purpose. `_session_context()` fetches weekdays, entries,
replacements, the legacy table and the library for a whole set of sessions in five
queries, and `_program_session()` composes each session from that in memory. Before this,
one app open cost about 130 Supabase round trips; bootstrap now issues 17 and
`list_programs` 7, with byte-identical responses.

Do not reintroduce per-session queries: every call is a separate HTTPS round trip to
`eu-central-1`, so the cost is network, not Postgres.

Writes already go through SQL functions (`gym_add_workout_exercise` and friends). The
remaining step, if reads ever feel slow again, is to move them into SQL functions too and
return ready `jsonb`, the way Tennis Coach does with its `pult_*` functions — one round
trip per screen. Measure before starting: the service region relative to the database may
matter more than the code.

## Private data in this repository

The repository is public. `supabase/seed_production.sql` and `supabase/reset_production.sql`
carry real medical notes and are git-ignored; `SPEC.md`, `docs/design/` and
`docs/superpowers/` are ignored for the same reason. A `.gitignore` entry only helps for
files Git does not already track, so check `git ls-tree` rather than trusting the ignore
list.

`tests/schema.test.cjs` asserts on personal values (target weight and the goal wording)
and reads the ignored production SQL. It stays local until those assertions are
anonymised.

## Агенты

Этот файл — единственный источник контекста проекта: его читают и Claude Code, и Codex
(у Codex через `project_doc_fallback_filenames` в `~/.codex/config.toml`).

- `AGENTS.md` в проекте не создавать и не вызывать `/init` — обновлять этот файл
- Задачи и открытые вопросы — в `plan.md`, он же точка синхронизации между агентами
- В конце сессии, если контекст проекта изменился, обновить соответствующие разделы здесь
