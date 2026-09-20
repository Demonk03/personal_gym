# Personal Gym

Private mobile-first training PWA with a Flask/Supabase backend. The application implements the Personal Gym design handoff: Today, complete check-in, server-generated plan, workout logging, completion, next-day response, history/editing, progress, body measurements, program, weekly review and settings.

## Local synthetic demo

```bash
python3 tests/preview_server.py
```

Open http://127.0.0.1:8774. In Settings, use that server address and the **test-only** key `preview-key`. Data is synthetic and resets when the demo server restarts. The demo does not access Supabase or send notifications. It uses a sample program, not the full cloud seed.

## API and static PWA

1. Install `requirements.txt` in a Python environment and configure `.env` from `.env.example`.
2. Apply `supabase/schema.sql` twice (the second pass verifies repeatability), then apply `supabase/seed_production.sql`. The production seed loads the 87-entry personal exercise catalog and real profile without creating or activating a demonstration program. Only walking starts as `allowed`; running, jump rope, tennis and padel start as `blocked`; all other cards require manual review before a new program can use them. Use `supabase/seed_demo.sql` only for an isolated demo database.
   For a deliberate clean installation that deletes all existing Personal Gym records first, run `supabase/reset_production.sql` instead of those two files.
3. For a fresh installation, apply `supabase/activate_pilot_program.sql` to approve the 10 pilot exercise cards and activate the Monday/Wednesday program. Reapply it after any later production seed. For an existing three-session pilot, apply `supabase/remove_scheduled_cardio.sql` instead: it keeps manually edited exercise statuses and historical workouts while removing the separate walking/cardio session from the active schedule. The pilot contains real user data while its deterministic check-in thresholds still require separate clinical approval, so the PWA labels it `ПИЛОТ`.
4. Start the API with `python3 app.py` (127.0.0.1:8001). For deployment use `gunicorn app:app` and the hosting platform's environment variables.
5. Serve `docs/` as static files, for example `python3 -m http.server 8000 --directory docs`. Set `DASHBOARD_ORIGIN` to that origin and enter the API URL/key in Settings.
6. Use HTTPS for a deployed PWA. A new workout needs network; an already started workout can continue offline with durable local writes.

Read [API and integration decisions](docs/api-integration.md) for payloads, recovery, concurrency and rollout details.

## Publishing the PWA

The production frontend is [Personal Gym on GitHub Pages](https://demonk03.github.io/personal_gym/). GitHub Pages publishes the `/docs` directory from `main` automatically after a push to `main`. `main` is the single source branch for the frontend; no separate release branch or manual publishing step is used.

Work on `main` locally and push when the intended group of changes is ready. Before pushing, review the files in the commit and run the verification commands below. After pushing, check that the GitHub Pages build succeeded and that the production URL serves the updated files. Backend deployment to Railway is separate from this frontend publication.

## Active pilot program

`supabase/activate_pilot_program.sql` creates the repeatable 2–3 week pilot:

| Day | Session | Plan |
|---|---|---|
| Monday | Full body A | Warm-up, Bird dog, glute bridge, band row, knee push-up, band lateral walk, Pallof press |
| Wednesday | Full body B + back | Warm-up, dead bug, band lateral walk, band row, band chest press, glute bridge, Pallof press |

Ordinary walking is not a scheduled workout. The walking card remains in the exercise library, and completed workouts from the earlier three-session pilot remain in history.

The migration sets 10 selected cards to `allowed`, keeps running, jump rope, tennis, padel and free handstand `blocked`, and returns every other active card to `needs_review`. It deactivates the previous program only inside the transaction and then activates the pilot as the sole active version. Database guards reject activation if any program exercise is inactive or not `allowed`.

The pilot uses real user records (`demo_only=false`) but keeps explicitly labeled pilot check-in rules. The `ПИЛОТ` badge means “operational trial”, not medical approval. On the Program screen, approved cards are under the `Разрешено` filter; the default filter remains `Нужно разобрать`.

## Optional push worker

Set the VAPID variables, including a valid `VAPID_SUBJECT` contact, and install the pywebpush dependency. Configure a separate scheduler to run `python3 jobs.py` every minute. Until configured, notification switches explain why they are unavailable. Permission denial never blocks the training app. Real push delivery still requires verification on the target device after deployment.

## Verification

```bash
npm run build
python3 -m pytest -q
python3 -m py_compile app.py db.py training.py integration.py notifications.py operations.py metrics.py gpt.py jobs.py
npm test
node --check docs/app.js
node --check docs/data.js
```

Catalog presence is not medical approval. Pilot exercise statuses and doses are explicitly selected by `activate_pilot_program.sql`; check-in thresholds remain pilot-only pending separate approval. Secrets and real health data do not belong in Git. Local tests and the browser walkthrough use synthetic workout data.

## Exercise library and quick logging

`GET /api/exercises` exposes the active catalog. The Program screen filters cards by `allowed`, `needs_review`, and `blocked`, and allows manual status, note, format, and archive edits. During a prepared or active workout, an existing non-blocked card can be attached or a minimal custom card can be created with a name, measurement format, and optional note.

Custom creation and workout attachment are one idempotent transaction. Offline sets depend on that transaction and retain stable IDs across reloads. Historical workout entries carry an immutable definition snapshot, so later renaming, format changes, or archiving do not rewrite prior facts. Supported formats are `reps`, `seconds`, `weighted_reps`, and `reps_seconds`.
