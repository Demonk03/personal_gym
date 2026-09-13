# Personal Gym

Personal Gym is a private mobile-first training application. The backend prepares a deterministic demo workout from a versioned program and check-in, stores workout history in Supabase, calculates progress metrics, and generates a validated weekly AI review.

The current implementation phase covers backend tasks 1–6 from [`docs/superpowers/plans/2026-09-13-personal-gym-mvp.md`](docs/superpowers/plans/2026-09-13-personal-gym-mvp.md). The PWA interface will be implemented after the product design is approved.

## Local backend

1. Copy `.env.example` to `.env` and fill local values.
2. Install dependencies: `python3 -m pip install -r requirements.txt`.
3. Run tests: `python3 -m pytest -q`.
4. Start the API: `python3 app.py`.

Health check: `GET http://127.0.0.1:8001/api/health`.

All current exercises and thresholds are demonstration data. They are not a medical recommendation and must not be enabled as a working personal program before separate approval.
