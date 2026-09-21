const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { PGlite } = require('@electric-sql/pglite');

const root = path.resolve(__dirname, '..');
const sql = name => fs.readFileSync(path.join(root, 'supabase', name), 'utf8');

test('multiple-program migration is repeatable and preserves the pilot', async () => {
  const db = new PGlite();
  await db.exec(sql('schema.sql'));
  await db.exec('create role anon; create role authenticated;');
  await db.exec(sql('seed_production.sql'));
  await db.exec(sql('activate_pilot_program.sql'));
  const before = await db.query("select count(*)::int as count from exercise_library where review_status='allowed'");
  await db.exec(sql('multiple_programs.sql'));
  await db.exec(sql('multiple_programs.sql'));
  const selected = await db.query(`select p.program_code,p.stage_code,p.published
    from gym_program_selection s join program_versions p on p.id=s.program_version_id`);
  assert.deepEqual(selected.rows, [{program_code:'pilot',stage_code:'pilot',published:true}]);
  const after = await db.query("select count(*)::int as count from exercise_library where review_status='allowed'");
  assert.deepEqual(after.rows,before.rows);
  await db.query("update exercise_library set body_areas=array['спина','руки'] where id='band-row'");
  assert.deepEqual((await db.query("select body_areas from exercise_library where id='band-row'")).rows[0].body_areas,['спина','руки']);
  await db.close();
});
