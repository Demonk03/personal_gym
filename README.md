# Personal Gym

Private mobile-first training PWA with a Flask/Supabase backend. The application implements the Personal Gym design handoff: Today, complete check-in, server-generated plan, workout logging, completion, next-day response, history/editing, progress, body measurements, program, weekly review and settings.

## Local synthetic demo

```bash
python3 tests/preview_server.py
```

Open http://127.0.0.1:8774. In Settings, use that server address and the **test-only** key `preview-key`. Data is synthetic and resets when the demo server restarts. The demo does not access Supabase or send notifications. It uses a sample program, not the full cloud seed.

## API and static PWA

1. Install `requirements.txt` in a Python environment and configure `.env` from `.env.example`.
2. Apply `supabase/schema.sql` to the target Supabase project. Use `seed_demo.sql` only for a separate demo database: it deliberately contains an unapproved demonstration program.
3. Start the API with `python3 app.py` (127.0.0.1:8001). For deployment use `gunicorn app:app` and the hosting platform's environment variables.
4. Serve `docs/` as static files, for example `python3 -m http.server 8000 --directory docs`. Set `DASHBOARD_ORIGIN` to that origin and enter the API URL/key in Settings.
5. Use HTTPS for a deployed PWA. A new workout needs network; an already started workout can continue offline with durable local writes.

Read [API and integration decisions](docs/api-integration.md) for payloads, recovery, concurrency and rollout details.

## Optional push worker

Set the VAPID variables, including a valid `VAPID_SUBJECT` contact, and install the pywebpush dependency. Configure a separate scheduler to run `python3 jobs.py` every minute. Until configured, notification switches explain why they are unavailable. Permission denial never blocks the training app. Real push delivery still requires verification on the target device after deployment.

## Verification

```bash
python3 -m pytest -q
python3 -m py_compile app.py db.py training.py integration.py notifications.py operations.py metrics.py gpt.py jobs.py
npm test
node --check docs/app.js
node --check docs/data.js
```

All exercises, doses and thresholds remain demo-only pending separate approval. Secrets and real health data do not belong in Git. Local tests and the browser walkthrough use synthetic data.
