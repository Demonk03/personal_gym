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
