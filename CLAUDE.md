# Personal Gym — Project Context

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
- Until approved, rules and programs are `demo_only=true` and cannot be represented as medical clearance.
- AI may summarize saved facts and suggest IDs from the approved library. It cannot add exercises, diagnose, or override a blocked workout.
- Real medical data, exports, database backups, and secrets do not belong in Git.

## Checks

```bash
python3 -m pytest -q
python3 -m py_compile app.py db.py training.py operations.py metrics.py gpt.py jobs.py
npm test
```

