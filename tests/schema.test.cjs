const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { PGlite } = require("@electric-sql/pglite");

const root = path.resolve(__dirname, "..");
const schema = fs.readFileSync(path.join(root, "supabase/schema.sql"), "utf8");
const seed = fs.readFileSync(path.join(root, "supabase/seed_demo.sql"), "utf8");

async function database() {
  const db = new PGlite();
  await db.exec(schema);
  return db;
}

test("schema is repeatable and contains the backend tables", async () => {
  const db = await database();
  await db.exec(schema);
  const expected = [
    "player_profile", "exercise_library", "program_versions", "program_sessions",
    "workouts", "workout_exercises", "workout_sets", "checkins",
    "weight_entries", "weekly_reviews", "gym_operations",
    "push_subscriptions", "scheduled_jobs",
  ];
  const result = await db.query(
    "select tablename from pg_tables where schemaname='public' order by tablename",
  );
  const names = result.rows.map((row) => row.tablename);
  for (const table of expected) assert.ok(names.includes(table), `missing ${table}`);
  await db.close();
});

test("demo seed is repeatable and stays unapproved", async () => {
  const db = await database();
  await db.exec(seed);
  await db.exec(seed);
  const exercises = await db.query(
    "select count(*)::int as count, bool_and(demo_only and not approved) as safe from exercise_library",
  );
  assert.equal(exercises.rows[0].count, 7);
  assert.equal(exercises.rows[0].safe, true);
  const programs = await db.query("select count(*)::int as count from program_versions where active");
  assert.equal(programs.rows[0].count, 1);
  await db.close();
});

test("workout constraints reject invalid and concurrent active rows", async () => {
  const db = await database();
  await db.exec(seed);
  await assert.rejects(
    db.query(`insert into workouts
      (id,status,checkin_mode,rule_version,program_snapshot)
      values ('40000000-0000-4000-8000-000000000001','unknown','green','v1','{}')`),
  );
  await db.query(`insert into workouts
    (id,status,checkin_mode,rule_version,program_snapshot)
    values ('40000000-0000-4000-8000-000000000001','preparing','green','v1','{}')`);
  await assert.rejects(
    db.query(`insert into workouts
      (id,status,checkin_mode,rule_version,program_snapshot)
      values ('40000000-0000-4000-8000-000000000002','in_progress','green','v1','{}')`),
  );
  await db.close();
});

test("operation IDs return a stored result and reject changed bodies", async () => {
  const db = await database();
  const id = "50000000-0000-4000-8000-000000000001";
  const first = await db.query(
    "select gym_claim_operation($1,'save_set',null,'hash-a') as value", [id],
  );
  assert.equal(first.rows[0].value.status, "claimed");
  const token = first.rows[0].value.token;
  const committed = await db.query(
    "select gym_commit_operation($1,$2,'{\"set_id\":\"one\"}') as value", [id, token],
  );
  assert.equal(committed.rows[0].value, true);
  const repeated = await db.query(
    "select gym_claim_operation($1,'save_set',null,'hash-a') as value", [id],
  );
  assert.equal(repeated.rows[0].value.status, "succeeded");
  assert.equal(repeated.rows[0].value.result.set_id, "one");
  const conflict = await db.query(
    "select gym_claim_operation($1,'save_set',null,'hash-b') as value", [id],
  );
  assert.equal(conflict.rows[0].value.status, "conflict");
  await db.close();
});

test("workout, set, and finish RPCs are idempotent and revision-safe", async () => {
  const db = await database();
  await db.exec(seed);
  const workoutId = "40000000-0000-4000-8000-000000000010";
  const exerciseEntryId = "41000000-0000-4000-8000-000000000010";
  const workout = JSON.stringify({
    id: workoutId,
    program_version_id: "10000000-0000-4000-8000-000000000001",
    program_session_id: "20000000-0000-4000-8000-000000000002",
    scheduled_date: "2026-09-13",
    checkin_mode: "green",
    checkin_reasons: [],
    demo_only: true,
    rule_version: "demo-rules-v1",
    profile_snapshot: {},
    program_snapshot: {
      exercises: [{exercise_id: "incline-pushup", allowed_replacements: ["wall-pushup"]}],
    },
  });
  const exercises = JSON.stringify([{
    id: exerciseEntryId,
    original_exercise_id: "incline-pushup",
    exercise_id: "incline-pushup",
    position: 1,
    planned_sets: 3,
    planned_reps: 6,
  }]);
  const createArgs = [
    "51000000-0000-4000-8000-000000000010", "create-hash", workout, exercises,
  ];
  const first = await db.query(
    "select gym_create_prepared_workout($1,$2,$3,$4) as value", createArgs,
  );
  const repeated = await db.query(
    "select gym_create_prepared_workout($1,$2,$3,$4) as value", createArgs,
  );
  assert.equal(first.rows[0].value.status, "succeeded");
  assert.equal(repeated.rows[0].value.status, "succeeded");
  const workoutCount = await db.query("select count(*)::int as count from workouts");
  assert.equal(workoutCount.rows[0].count, 1);

  const started = await db.query(
    "select gym_start_workout($1,'start-hash',$2,1) as value",
    ["51100000-0000-4000-8000-000000000010", workoutId],
  );
  assert.equal(started.rows[0].value.result.revision, 2);
  const reordered = await db.query(
    "select gym_reorder_workout($1,'order-hash',$2,2,array[$3::uuid]) as value",
    ["51200000-0000-4000-8000-000000000010", workoutId, exerciseEntryId],
  );
  assert.equal(reordered.rows[0].value.result.revision, 3);
  const replaced = await db.query(
    "select gym_replace_workout_exercise($1,'replace-hash',$2,3,$3,'wall-pushup','demo') as value",
    ["51300000-0000-4000-8000-000000000010", workoutId, exerciseEntryId],
  );
  assert.equal(replaced.rows[0].value.result.revision, 4);
  const setBody = JSON.stringify({
    id: "42000000-0000-4000-8000-000000000010",
    workout_id: workoutId,
    workout_exercise_id: exerciseEntryId,
    set_number: 1,
    actual_reps: 6,
  });
  const setArgs = ["52000000-0000-4000-8000-000000000010", "set-hash", setBody];
  await db.query("select gym_save_set($1,$2,$3) as value", setArgs);
  await db.query("select gym_save_set($1,$2,$3) as value", setArgs);
  const setCount = await db.query("select count(*)::int as count from workout_sets");
  assert.equal(setCount.rows[0].count, 1);

  const finishArgs = [
    "53000000-0000-4000-8000-000000000010", "finish-hash", workoutId, 4,
    "completed", "2026-09-13T12:00:00Z", null,
    JSON.stringify({overall_difficulty: 5, back_pain: 3, leg_symptoms_change: "same"}),
  ];
  const finished = await db.query(
    "select gym_finish_workout($1,$2,$3,$4,$5,$6,$7,$8) as value", finishArgs,
  );
  const finishRepeat = await db.query(
    "select gym_finish_workout($1,$2,$3,$4,$5,$6,$7,$8) as value", finishArgs,
  );
  assert.equal(finished.rows[0].value.result.revision, 5);
  assert.equal(finishRepeat.rows[0].value.result.revision, 5);
  await assert.rejects(
    db.query(
      "select gym_finish_workout($1,$2,$3,$4,$5,$6,$7,$8)",
      ["53000000-0000-4000-8000-000000000011", "other", workoutId, 4,
        "completed", "2026-09-13T12:01:00Z", null, JSON.stringify({})],
    ),
  );
  const nextDay = await db.query(
    "select gym_save_next_day_checkin($1,'next-hash',$2,5,$3) as value",
    ["53100000-0000-4000-8000-000000000010", workoutId,
      JSON.stringify({pain_change: "same", ready_for_similar_load: true})],
  );
  assert.equal(nextDay.rows[0].value.result.revision, 6);
  await db.close();
});

test("RLS is enabled on personal tables", async () => {
  const db = await database();
  const result = await db.query(
    "select bool_and(relrowsecurity) as enabled from pg_class where relname in ('workouts','checkins','weight_entries','weekly_reviews')",
  );
  assert.equal(result.rows[0].enabled, true);
  await db.close();
});

test("weekly review and operation result commit in one database call", async () => {
  const db = await database();
  const operationId = "54000000-0000-4000-8000-000000000001";
  const reviewId = "55000000-0000-4000-8000-000000000001";
  const sourceId = "56000000-0000-4000-8000-000000000001";
  const claim = await db.query(
    "select gym_claim_operation($1,'weekly_review',$2,'review-hash') as value",
    [operationId, reviewId],
  );
  const record = JSON.stringify({
    id: reviewId, week_start: "2026-09-07", source_hash: "source-hash",
    source_workout_ids: [sourceId], prompt_version: "v1", model: "fake",
    result: {summary: "ok"},
  });
  const saved = await db.query(
    "select gym_commit_weekly_review($1,$2,$3) as value",
    [operationId, claim.rows[0].value.token, record],
  );
  const operation = await db.query("select status,result from gym_operations where id=$1", [operationId]);
  assert.equal(saved.rows[0].value.status, "ready");
  assert.equal(operation.rows[0].status, "succeeded");
  assert.equal(operation.rows[0].result.status, "ready");
  await db.close();
});
