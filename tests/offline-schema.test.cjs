const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {PGlite}=require('@electric-sql/pglite');

const schema=fs.readFileSync(path.join(__dirname,'../supabase/schema.sql'),'utf8');
const wid='a1000000-0000-4000-8000-000000000001';
const eid='a1000000-0000-4000-8000-000000000002';
const setId='a1000000-0000-4000-8000-000000000003';

async function setup(){
 const db=new PGlite();await db.exec(schema);
 await db.exec("insert into exercise_library(id,name,measurement_type,review_status,source) values('test-reps','Test','reps','allowed','base_catalog')");
 const snapshot={exercises:[{exercise_id:'test-reps',allowed_replacements:[]}],exercise_library:{'test-reps':{id:'test-reps',name:'Test',measurement_type:'reps',review_status:'allowed',active:true,equipment:[]}}};
 await db.query("insert into workouts(id,status,checkin_mode,rule_version,program_snapshot,revision) values($1,'in_progress','green','test',$2,2)",[wid,JSON.stringify(snapshot)]);
 await db.query("insert into workout_exercises(id,workout_id,original_exercise_id,exercise_id,position,planned_sets,planned_reps,definition_snapshot) values($1,$2,'test-reps','test-reps',1,1,8,$3)",[eid,wid,JSON.stringify(snapshot.exercise_library['test-reps'])]);
 await db.query("insert into checkins(id,workout_id,kind,payload) values(gen_random_uuid(),$1,'pre',$2)",[wid,JSON.stringify({equipment:[]})]);
 return db;
}
function payload(setEntry=eid){return {revision:2,status:'completed',finished_at:'2026-09-19T12:00:00Z',stop_reason:null,
 post_checkin:{overall_difficulty:5,back_pain:2,leg_symptoms_change:'same',comment:''},
 entries:[{id:eid,position:1,exercise_id:'test-reps',removed:false,skipped:false}],
 sets:[{id:setId,workout_exercise_id:setEntry,set_number:1,actual_reps:8,completed_at:'2026-09-19T11:00:00Z'}]};}

test('offline snapshot commits all facts once and rejects changed-body retry',async()=>{
 const db=await setup(),op='a1000000-0000-4000-8000-000000000004';
 try{
  const args=[op,'same-hash',wid,JSON.stringify(payload())];
  const first=await db.query('select gym_commit_offline_workout($1,$2,$3,$4) as result',args);
  const repeat=await db.query('select gym_commit_offline_workout($1,$2,$3,$4) as result',args);
  assert.deepEqual(first.rows[0].result,repeat.rows[0].result);
  assert.equal(first.rows[0].result.result.status,'completed');
  assert.equal((await db.query('select count(*)::int as count from workout_sets')).rows[0].count,1);
  assert.equal((await db.query("select count(*)::int as count from checkins where kind='post'")).rows[0].count,1);
  assert.equal((await db.query('select gym_commit_offline_workout($1,$2,$3,$4) as result',[op,'other-hash',wid,JSON.stringify(payload())])).rows[0].result.status,'conflict');
 }finally{await db.close()}
});

test('invalid offline snapshot rolls back every server change',async()=>{
 const db=await setup();
 try{
  await assert.rejects(db.query('select gym_commit_offline_workout($1,$2,$3,$4)',
   ['a1000000-0000-4000-8000-000000000005','invalid-hash',wid,JSON.stringify(payload('a1000000-0000-4000-8000-000000000099'))]));
  assert.equal((await db.query('select status from workouts where id=$1',[wid])).rows[0].status,'in_progress');
  assert.equal((await db.query('select count(*)::int as count from workout_sets')).rows[0].count,0);
  assert.equal((await db.query('select count(*)::int as count from workout_exercises')).rows[0].count,1);
 }finally{await db.close()}
});

test('zero repetitions cannot be committed',async()=>{
 const db=await setup();
 try{
  const body=payload();body.sets[0].actual_reps=0;
  await assert.rejects(db.query('select gym_commit_offline_workout($1,$2,$3,$4)',
   ['a1000000-0000-4000-8000-000000000006','zero-reps',wid,JSON.stringify(body)]));
  assert.equal((await db.query('select status from workouts where id=$1',[wid])).rows[0].status,'in_progress');
 }finally{await db.close()}
});

test('custom exercise and its set arrive in one commit',async()=>{
 const db=await setup(),cardId='custom-a1000000-0000-4000-8000-000000000007',entryId='a1000000-0000-4000-8000-000000000008';
 try{
  const body=payload();body.entries.push({id:entryId,position:2,exercise_id:cardId,exercise:{id:cardId,name:'New lift',measurement_type:'reps',note:''},removed:false,skipped:false});
  body.sets.push({id:'a1000000-0000-4000-8000-000000000009',workout_exercise_id:entryId,set_number:1,actual_reps:5,completed_at:'2026-09-19T11:01:00Z'});
  const result=await db.query('select gym_commit_offline_workout($1,$2,$3,$4) as result',
   ['a1000000-0000-4000-8000-00000000000a','custom-card',wid,JSON.stringify(body)]);
  assert.equal(result.rows[0].result.result.status,'completed');
  assert.equal((await db.query('select count(*)::int as count from workout_sets')).rows[0].count,2);
  assert.equal((await db.query('select review_status from exercise_library where id=$1',[cardId])).rows[0].review_status,'needs_review');
 }finally{await db.close()}
});
