# Personal Gym

Private mobile-first training PWA with a Flask/Supabase backend. The application implements the Personal Gym design handoff: Today, complete check-in, server-generated plan, workout logging, completion, next-day response, history/editing, progress, body measurements, program, weekly review and settings.

## Local synthetic demo

```bash
python3 tests/preview_server.py
```

Open http://127.0.0.1:8774. In Settings, use that server address and the **test-only** key `preview-key`. Data is synthetic and resets when the demo server restarts. The demo does not access Supabase or send notifications. It uses a sample program, not the full cloud seed.

## API and static PWA

1. Install `requirements.txt` in a Python environment and configure `.env` from `.env.example`.
2. Apply `supabase/schema.sql` twice (the second pass verifies repeatability), then apply `supabase/seed_demo.sql`. The seed now contains the 87-entry personal exercise catalog, but deactivates the old demonstration program. Only walking starts as `allowed`; running, jump rope, tennis and padel start as `blocked`; all other cards require manual review before a new program can use them.
3. Start the API with `python3 app.py` (127.0.0.1:8001). For deployment use `gunicorn app:app` and the hosting platform's environment variables.
4. Serve `docs/` as static files, for example `python3 -m http.server 8000 --directory docs`. Set `DASHBOARD_ORIGIN` to that origin and enter the API URL/key in Settings.
5. Use HTTPS for a deployed PWA. A new workout needs network; an already started workout can continue offline with durable local writes.

Read [API and integration decisions](docs/api-integration.md) for payloads, recovery, concurrency and rollout details.

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

Catalog presence is not medical approval. Exercise status changes are manual; doses and check-in thresholds remain demonstration-only pending separate approval. Secrets and real health data do not belong in Git. Local tests and the browser walkthrough use synthetic workout data.

## Exercise library and quick logging

`GET /api/exercises` exposes the active catalog. The Program screen filters cards by `allowed`, `needs_review`, and `blocked`, and allows manual status, note, format, and archive edits. During a prepared or active workout, an existing non-blocked card can be attached or a minimal custom card can be created with a name, measurement format, and optional note.

Custom creation and workout attachment are one idempotent transaction. Offline sets depend on that transaction and retain stable IDs across reloads. Historical workout entries carry an immutable definition snapshot, so later renaming, format changes, or archiving do not rewrite prior facts. Supported formats are `reps`, `seconds`, `weighted_reps`, and `reps_seconds`.
