# Frontend/API contract — design integration

The authoritative rules are `training.py` / `demo-rules-v1`. The HTML design runtime is not used by the application. `docs/index.html` loads the standalone vanilla-JS PWA. All personal API calls use Bearer authentication and `no-store`.

## Read models

- `GET /api/bootstrap`: `contract_version:1`, profile, default program and **sessions[]**. Each session includes name, type, weekday (ISO 1–7), estimated minutes, exercise library, allowed replacements and reasons. History uses its saved program snapshot.
- `GET /api/today`: local date in profile timezone, active workout bundle, latest blocked check-in for that date, scheduled sessions, and unanswered next-day check-ins from the last 14 days. No answer is fabricated for missing symptoms.
- `GET /api/workouts/:id`: `{workout, exercises, sets, checkins}`. Prepared and mutation responses also return bundles where appropriate. Operation recovery can return a small stored result; the client rereads the bundle before removing the operation from its queue.
- `GET /api/measurements`: chronological `entries[]`, in cm.
- Weekly review GET includes the saved review, deterministic facts, no-data flag and the number of missing next-day answers. The UI shows the preceding complete calendar week, without asserting full data coverage from workout count alone.

## Writes

All workout edits, weight writes and measurements require a UUID `idempotency_key`. Keep the same body and key when retrying an uncertain operation.

| Route | Body in addition to idempotency key |
|---|---|
| `POST /api/workouts/prepare` | checkin, session_key, scheduled_date, is_extra (boolean) |
| `POST /api/workouts/:id/edit` | revision and action described below |
| action `reprepare` | complete checkin; only preparing; atomically replaces the plan; red ends the preparation and preserves the evaluation |
| action `remove` / `restore` | entry_id; removes from the chosen plan while preserving the source plan; removal of an exercise with facts is rejected |
| action `skip` / `unskip` | entry_id; preserves already recorded sets |
| action `undo_set` | set_id, set_revision; only in_progress; the edit is recorded in the audit table |
| action `edit_post` | post_checkin; only completed/stopped_early; marks the workout edited |
| `POST /api/measurements` | measured_at with timezone; waist_cm, chest_cm, hips_cm, thigh_cm, each 10–300 |
| `POST /api/push/subscription` | native PushSubscription JSON and boolean preferences next_day/review |

Replacement cannot change an exercise with recorded sets. Equipment and measurement type must match. Auto-replacement and omission reasons survive database round-trips. Completed status requires all non-removed exercises to have their prescribed number of sets and no skips; otherwise use stopped_early and a reason. Set recording accepts an optional timezone-bearing completed_at so offline facts retain their timestamp.

## UI decisions

- The complete backend check-in fields are asked explicitly in the handoff's cards/chips. Missing flags are never silently false.
- Post-workout difficulty chips mean 2/5/8/10 on the stored 1–10 scale; the numbers are visible. Leg symptoms use better/same/worse. Zero pain is displayed as zero.
- Next-day questions are pain change, leg symptom change, unusual fatigue, and readiness for a similar load. Sleep is not substituted for readiness.
- kg/lb are display preferences; writes use kg. Timed exercises are entered in minutes, converted to seconds. Body measurements use cm.
- Dates, quantities, mode reasons, comparisons and charts derive from saved data; no prototype constants become production records.
- Removing an exercise and skipping it are separate operations. A skipped or partially completed exercise makes completion early.
- The theme and display units are local preferences. Schedule editing stays disabled until a program is approved, as specified in the handoff.

## Offline and concurrency

New preparation/start require network. Active workouts, weight and measurements use an IndexedDB queue. The queue atomically appends records, retains immutable operation payloads, drains sequentially and updates confirmed revisions only after successful server reads. Timed-out requests query operation status before retrying. A revision conflict stops the queue and offers explicit comparison/retry against the current server version. Local data is isolated by a hash of API URL and key; changing connection is blocked while a queue is pending.

A renewable IndexedDB lease coordinates the writing tab; explicit takeover is available. Web Locks additionally serialize queue draining where supported. Tab coordination is local to a browser; cross-device edits are protected by server revisions and unique set numbers rather than a global device lock.

The service worker caches only the application shell and Onest font responses; it excludes authenticated requests and API URLs. Opened history details and read models are cached separately in the connection's IndexedDB database. Previously unopened history details require network.

## Delivery boundary

Schema changes are repeatable in `supabase/schema.sql` and were checked using PGlite. Apply the updated schema to the target Supabase project before running this frontend against it. The local demo uses MemoryRepository and synthetic data. No migration, deployment or notification delivery to a real device was performed as part of local implementation.

Push requires pywebpush, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT and a scheduler invoking `python3 jobs.py` every minute. Next-day reminders become due at 09:00 local the following morning; the preceding week's review is generated Monday at/after 09:00. Failed notifications retry; expired subscriptions are disabled. Notification text contains no health information. Delivery is at-least-once after an ambiguous network failure; stable notification tags coalesce repeats on the device.
