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
        ├─ training.py → deterministic check-in and workout plan
        ├─ operations.py → idempotent writes
        ├─ metrics.py → progress calculations
        ├─ db.py → Supabase
        └─ gpt.py → validated weekly review only
```

## Safety boundary

- Exercise selection, check-in modes, and workout blocking are deterministic and never delegated to AI.
- The active 2–3 week program is an operationally approved pilot (`pilot-rules-v1`), not medical clearance. Its thresholds intentionally match the earlier deterministic demo rules until they are reviewed separately.
- Only active exercise cards with `review_status=allowed` may be included in a program. The activation SQL and database trigger enforce this invariant.
- AI may summarize saved facts and suggest IDs from the approved library. It cannot add exercises, diagnose, or override a blocked workout.
- Real medical data, exports, database backups, and secrets do not belong in Git.

## Production rollout

Apply database files in this order:

1. `supabase/schema.sql` twice;
2. `supabase/seed_production.sql`;
3. `supabase/activate_pilot_program.sql`.

The pilot migration is repeatable and must be rerun after the production seed. It approves 10 pilot exercises, blocks 5 excluded exercises, sets the rest to `needs_review`, and activates sessions on Monday, Wednesday, and Saturday.

The PWA renders `pilot-rules-v1` as `ПИЛОТ`. Do not replace it with `ПРОГРАММА` until the check-in rules have been separately approved.

## Checks

```bash
python3 -m pytest -q
python3 -m py_compile app.py db.py training.py operations.py metrics.py gpt.py jobs.py
npm test
node --check docs/app.js
```
