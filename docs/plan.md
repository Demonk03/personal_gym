# Personal Gym delivery status

| Task | Status | Notes |
|---|---|---|
| 1. Backend scaffold | Complete | Visual frontend shell deferred until design handoff |
| 2. Database and seeds | Complete locally | Schema, demo seed, production seed and repeatable pilot activation verified with PGlite |
| 3. Check-in rules and planning | Pilot ready | Deterministic `pilot-rules-v1`; same thresholds as demo rules; no AI dependency and no medical-clearance claim |
| 4. Workout API | Complete | Auth, validation, lifecycle, revisions and idempotency verified locally |
| 5. Metrics and export | Complete | Timezone-aware weight, separate load types, history and JSON/CSV export |
| 6. Weekly review | Complete | Strict JSON contract; tests use a fake model client |
| 7–10. PWA and design integration | Implemented locally | Handoff screens, durable queue, history and measurements; browser walkthrough verified |
| 11. Push and worker | Implemented; deployment required | Subscription API, neutral delivery, durable claims; fake-delivery tests only |
| 12. Cloud release | Partially deployed | Production API is reachable; apply `activate_pilot_program.sql`, refresh the PWA, then verify a real workout and iPhone push |
| Exercise library and quick entry | Production catalog present | 87 cards and manual statuses are available; pilot migration selects 10 allowed, 5 blocked and leaves the rest for review |
| Cautious 3-week pilot | Code in `main`; DB rollout pending | Monday/Wednesday full-body sessions with back-control work and Saturday walking; SQL is repeatable and activation-guarded |
| Backlog: progress gamification | Idea | Active days, schedule streaks, personal records and milestones; definitions require a separate design |

Design integration decisions: [API contract](api-integration.md). Original gaps: [audit](design-backend-gap-analysis.md).

## Open tasks after the 2026-11 incident

The app had stopped working: the Supabase project had been paused, and the deployed code
expected `supabase/multiple_programs.sql`, which had never been applied in production.
Both are fixed — the project is restored and the migration is in place. What is left:

- [ ] Deploy `d58ae9c` to Railway. The read batching lives in `db.py`, so until the
      backend redeploys, the published PWA still talks to the slow version.
- [ ] Check the Railway region against the database in `eu-central-1`. If the service
      runs outside Europe, the round trip may cost more than any code change saves.
- [ ] Rotate `API_KEY`: the current value is 7 characters and there is no rate limiting,
      lockout or failed-attempt logging in front of medical data.
      Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- [ ] Install Node and pytest locally. Neither exists on this machine, so `npm test`,
      `node --check` and the Python suite have not run for several commits; those changes
      were verified only by parsing and by an ad-hoc equivalence check.
- [ ] Anonymise `tests/schema.test.cjs` so it can be committed — today it asserts on the
      target weight and the goal wording and reads git-ignored production SQL.
- [ ] Decide on the uncommitted leftovers: the deletion of `.openai/hosting.json`, and
      whether `Dockerfile` and `.dockerignore` belong in the repository now that the move
      to Yandex Cloud is cancelled.

Deferred by choice: moving reads into SQL functions returning `jsonb`, the way Tennis
Coach does it. Worth revisiting only if the app still feels slow after the batching is
actually deployed and measured.
