const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {PGlite}=require('@electric-sql/pglite');

test('obsolete pre-checkin JSON keys are removed without touching other answers',async()=>{
 const db=new PGlite();
 try{
  await db.exec('create table checkins (id integer primary key, kind text, payload jsonb, updated_at timestamptz default now())');
  await db.exec(`insert into checkins (id,kind,payload) values
    (1,'pre','{"pain_change":"same","leg_symptoms":{"trend":"worse","saddle_numbness":false,"bladder_bowel_change":false},"systemic_symptoms":{"fainting":false}}'),
    (2,'post','{"systemic_symptoms":{"fainting":true}}')`);
  const sql=fs.readFileSync(path.join(__dirname,'../supabase/remove_obsolete_checkin_fields.sql'),'utf8');
  await db.exec(sql);
  await db.exec(sql);
  const {rows}=await db.query('select id,payload from checkins order by id');
  assert.deepEqual(rows[0].payload,{pain_change:'same',leg_symptoms:{trend:'worse'}});
  assert.deepEqual(rows[1].payload,{systemic_symptoms:{fainting:true}});
 }finally{await db.close()}
});
