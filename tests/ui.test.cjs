const test=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
class MemoryStore{constructor(){this.name='test';this.values={}}async get(k){return structuredClone(this.values[k])}async set(k,v){this.values[k]=structuredClone(v)}async update(k,fn){const v=fn(structuredClone(this.values[k]));this.values[k]=structuredClone(v);return v}}
const response=(data,status=200)=>({ok:status<400,status,json:async()=>data});
Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});

test('exercise library interface exposes quick entry, statuses, and all measurement formats',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../docs/app.js'),'utf8');
 for(const text of ['Добавить упражнение','Создать новое','Нужно разобрать','Заблокировано','reps_seconds','weighted_reps','Добавлено вручную'])assert.match(source,new RegExp(text));
 assert.match(source,/data-action="catalog-edit"/);assert.match(source,/'create-exercise'/);
});

test('program badge labels pilot rules honestly on both program surfaces',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../docs/app.js'),'utf8');
 assert.match(source,/const programBadge=/);
 assert.match(source,/pilot-rules-v1.*ПИЛОТ/);
 assert.equal((source.match(/programBadge\(boot\.program\)/g)||[]).length,2);
});

test('queue keeps a new set added while previous request is in flight',async()=>{
 const {Queue}=await import('../docs/data.js');const store=new MemoryStore();let release;const gate=new Promise(r=>release=r);const calls=[];
 global.fetch=async(url,options)=>{calls.push(JSON.parse(options.body));if(calls.length===1)await gate;return response({saved:true})};
 const q=new Queue(store,{url:'http://test',key:'test'},async()=>{});
 await q.add({path:'/api/weight',body:{weight_kg:70}});
 await new Promise(r=>setImmediate(r));
 await q.add({path:'/api/weight',body:{weight_kg:71}});release();
 while(q.running)await new Promise(r=>setImmediate(r));
 assert.equal(calls.length,2);assert.equal(calls[1].weight_kg,71);assert.equal((await q.read()).length,0);
});

test('unknown outcome checks stable operation ID instead of posting twice',async()=>{
 const {Queue}=await import('../docs/data.js');const store=new MemoryStore();let posts=0,lookups=0;
 global.fetch=async(url,options)=>{if(options.method==='POST'){posts++;throw Object.assign(new Error('timeout'),{name:'AbortError'})}lookups++;return response({status:'succeeded',result:{saved:true}})};
 const q=new Queue(store,{url:'http://test',key:'test'},async()=>{});await q.add({path:'/api/weight',body:{weight_kg:70}});
 while(q.running)await new Promise(r=>setImmediate(r));
 const key=(await q.read())[0].body.idempotency_key;assert.equal((await q.read())[0].state,'unknown');await q.flush();
 assert.equal(posts,1);assert.equal(lookups,1);assert.ok(key);assert.equal((await q.read()).length,0);
});

test('revision operations follow confirmed revision and stop at a conflict',async()=>{
 const {Queue}=await import('../docs/data.js');const store=new MemoryStore();await store.set('workout:w',{workout:{id:'w',revision:7}});const revisions=[];
 global.fetch=async(url,options)=>{if(options.method==='GET')return response({workout:{id:'w',revision:8}});revisions.push(JSON.parse(options.body).revision);return revisions.length===1?response({saved:true}):response({error:{code:'revision_conflict',message:'Conflict'}},409)};
 const q=new Queue(store,{url:'http://test',key:'test'},async()=>{});navigator.onLine=false;
 await q.add({path:'/api/workouts/w/edit',workoutId:'w',needsRevision:true,body:{action:'skip'}});await q.add({path:'/api/workouts/w/finish',workoutId:'w',needsRevision:true,body:{}});navigator.onLine=true;
 await q.flush();assert.deepEqual(revisions,[7,8]);assert.equal((await q.read())[0].state,'conflict');await q.flush();assert.equal(revisions.length,2);
});

test('offline projection restores facts without changing confirmed data',async()=>{
 const {project}=await import('../docs/data.js');const b={workout:{id:'w',status:'in_progress'},exercises:[{id:'e',skipped:false}],sets:[]};
 const result=project(b,[{workoutId:'w',method:'POST',path:'/api/workouts/w/sets',body:{id:'s',workout_exercise_id:'e',actual_reps:8}},{workoutId:'w',path:'/api/workouts/w/edit',body:{action:'skip',entry_id:'e'}}]);
 assert.equal(b.sets.length,0);assert.equal(result.sets.length,1);assert.equal(result.exercises[0].skipped,true);
});

test('quick exercise projection keeps stable IDs and deduplicates retries',async()=>{
 const {project}=await import('../docs/data.js');const snapshot={id:'custom-one',name:'Новое',measurement_type:'reps_seconds',note:''};
 const bundle={workout:{id:'w',revision:2,program_snapshot:{exercise_library:{}}},exercises:[],sets:[],checkins:[]};
 const attach={workoutId:'w',method:'POST',path:'/api/workouts/w/exercises',body:{idempotency_key:'op',workout_entry_id:'entry',exercise:snapshot,definition_snapshot:snapshot}};
 const set={workoutId:'w',method:'POST',path:'/api/workouts/w/sets',created:'2026-09-15T10:00:00Z',body:{id:'set',workout_exercise_id:'entry',actual_reps:5,actual_seconds:20}};
 const result=project(bundle,[attach,attach,set,set]);
 assert.equal(bundle.exercises.length,0);assert.equal(result.exercises.length,1);assert.equal(result.sets.length,1);
 assert.equal(result.exercises[0].definition_snapshot.measurement_type,'reps_seconds');
});

test('dependent set waits for quick exercise and preserves operation IDs',async()=>{
 const {Queue}=await import('../docs/data.js');const store=new MemoryStore();
 await store.set('workout:w',{workout:{id:'w',revision:2,program_snapshot:{exercise_library:{}}},exercises:[],sets:[],checkins:[]});
 const calls=[];global.fetch=async(url,options={})=>{calls.push({url,body:options.body&&JSON.parse(options.body)});if(options.method==='GET')return response({workout:{id:'w',revision:3,program_snapshot:{exercise_library:{}}},exercises:[],sets:[],checkins:[]});return response({saved:true})};
 const q=new Queue(store,{url:'http://test',key:'test'},async()=>{});navigator.onLine=false;
 await q.add({path:'/api/workouts/w/exercises',workoutId:'w',needsRevision:true,body:{idempotency_key:'attach-op',workout_entry_id:'entry',exercise:{id:'custom-one'}}});
 await q.add({path:'/api/workouts/w/sets',workoutId:'w',dependsOn:'attach-op',body:{idempotency_key:'set-op',id:'set',workout_exercise_id:'entry'}});
 assert.deepEqual((await q.read()).map(x=>x.body.idempotency_key),['attach-op','set-op']);
 navigator.onLine=true;await q.flush();
 assert.deepEqual(calls.filter(x=>x.body).map(x=>x.body.idempotency_key),['attach-op','set-op']);
 assert.equal((await q.read()).length,0);
});

test('tab lease excludes a second writer until takeover or expiration',async()=>{
 const {claimLease}=await import('../docs/data.js');const first=claimLease(null,'one',1000);
 assert.equal(claimLease(first,'two',2000).owner,'one');
 assert.equal(claimLease(first,'two',2000,true).owner,'two');
 assert.equal(claimLease(first,'two',16001).owner,'two');
});
