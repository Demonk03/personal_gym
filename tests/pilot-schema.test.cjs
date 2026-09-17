const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { PGlite } = require("@electric-sql/pglite");

const root = path.resolve(__dirname, "..");
const schema = fs.readFileSync(path.join(root, "supabase/schema.sql"), "utf8");
const seed = fs.readFileSync(path.join(root, "supabase/seed_demo.sql"), "utf8");
const pilot = fs.readFileSync(path.join(root, "supabase/activate_pilot_program.sql"), "utf8");

test("pilot migration is repeatable and activates only allowed exercises", async () => {
  const db = new PGlite();
  await db.exec(schema);
  await db.exec(seed);
  await db.exec(pilot);
  await db.exec(pilot);

  const statuses = await db.query(`select
    count(*) filter (where active and review_status='allowed')::int as allowed,
    count(*) filter (where active and review_status='blocked')::int as blocked
    from exercise_library`);
  assert.deepEqual(statuses.rows[0], {allowed: 10, blocked: 5});

  const active = await db.query(`select id,name,rule_version,demo_only,approved
    from program_versions where active`);
  assert.equal(active.rows.length, 1);
  assert.equal(active.rows[0].name, "Осторожный пилот · 3 недели");
  assert.equal(active.rows[0].rule_version, "pilot-rules-v1");
  assert.equal(active.rows[0].demo_only, false);
  assert.equal(active.rows[0].approved, true);

  const sessions = await db.query(`select session_key,weekday,count(pse.id)::int as exercises
    from program_sessions ps
    join program_session_exercises pse on pse.session_id=ps.id
    where ps.program_version_id=$1
    group by ps.id order by ps.position`, [active.rows[0].id]);
  assert.deepEqual(sessions.rows, [
    {session_key: "full-body-a-pilot", weekday: 1, exercises: 7},
    {session_key: "full-body-b-pilot", weekday: 3, exercises: 7},
    {session_key: "easy-cardio-pilot", weekday: 6, exercises: 1},
  ]);

  const unsafe = await db.query(`select count(*)::int as count
    from program_session_exercises pse
    join program_sessions ps on ps.id=pse.session_id
    join exercise_library e on e.id=pse.exercise_id
    where ps.program_version_id=$1 and (not e.active or e.review_status<>'allowed')`, [active.rows[0].id]);
  assert.equal(unsafe.rows[0].count, 0);
  await db.close();
});
