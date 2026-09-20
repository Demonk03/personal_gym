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
  ]);

  const unsafe = await db.query(`select count(*)::int as count
    from program_session_exercises pse
    join program_sessions ps on ps.id=pse.session_id
    join exercise_library e on e.id=pse.exercise_id
    where ps.program_version_id=$1 and (not e.active or e.review_status<>'allowed')`, [active.rows[0].id]);
  assert.equal(unsafe.rows[0].count, 0);
  await db.close();
});

test("two-session pilot keeps the previous cardio session for workout history", async () => {
  const db = new PGlite();
  try {
    await db.exec(schema);
    await db.exec(seed);
    await db.exec(`insert into program_versions(id,version,name,rule_version,demo_only,approved,active)
      values('71000000-0000-4000-8000-000000000001',2,'Previous pilot','pilot-rules-v1',false,true,true);
      insert into program_sessions(id,program_version_id,session_key,name,session_type,weekday,estimated_minutes,position)
      values('72000000-0000-4000-8000-000000000003','71000000-0000-4000-8000-000000000001',
        'easy-cardio-pilot','Спокойное кардио','cardio',6,20,3);
      insert into workouts(id,program_version_id,program_session_id,status,checkin_mode,rule_version,program_snapshot)
      values('74000000-0000-4000-8000-000000000001','71000000-0000-4000-8000-000000000001',
        '72000000-0000-4000-8000-000000000003','completed','green','pilot-rules-v1','{}');`);
    await db.exec(pilot);
    const active = await db.query(`select id from program_versions where active`);
    assert.equal(active.rows.length, 1);
    assert.equal(active.rows[0].id, '71000000-0000-4000-8000-000000000002');
    assert.equal((await db.query(`select count(*)::int as count from program_sessions where program_version_id=$1`,
      [active.rows[0].id])).rows[0].count, 2);
    assert.equal((await db.query(`select session_key from program_sessions where id='72000000-0000-4000-8000-000000000003'`)).rows[0].session_key, 'easy-cardio-pilot');
    assert.equal((await db.query(`select program_session_id from workouts where id='74000000-0000-4000-8000-000000000001'`)).rows[0].program_session_id,
      '72000000-0000-4000-8000-000000000003');
  } finally { await db.close(); }
});
