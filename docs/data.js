export const uuid=()=>crypto.randomUUID();
export function nextScheduledSession(sessions,workouts,today,dayChoices=[],alternateSessions=[]){
 const byId=new Map([...sessions,...alternateSessions].map(s=>[s.session_id,s]));
 const choices=new Map(dayChoices.map(c=>[c.scheduled_date,c]));
 for(let days=0;days<35;days++){
  const date=new Date(today+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+days);
  const day=date.toISOString().slice(0,10),choice=choices.get(day);
  if(workouts.some(w=>w&&!w.is_extra&&w.scheduled_date===day&&['completed','stopped_early'].includes(w.status)))continue;
  if(choice?.choice==='skipped')continue;
  const session=choice?.choice==='session'?byId.get(choice.session_id):sessions.find(s=>s.weekday===(date.getUTCDay()||7));
  if(session)return {session,date:day,isToday:days===0};
 }
 return null;
}
export class APIError extends Error{constructor(message,status=0,code='network'){super(message);this.status=status;this.code=code}}
export async function request(config,path,{method='GET',body,timeout=60000}={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{const response=await fetch(config.url.replace(/\/$/,'')+path,{method,headers:{Authorization:`Bearer ${config.key}`,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,signal:controller.signal,cache:'no-store'});
 let data;try{data=await response.json()}catch{throw new APIError('Сервер вернул неожиданный ответ',response.status,'invalid_response')}
 if(!response.ok)throw new APIError(data.error?.message||'Ошибка сервера',response.status,data.error?.code);
 return data;
 }catch(e){if(e instanceof APIError)throw e;throw new APIError(e.name==='AbortError'?'Результат неизвестен. Проверим сохранение.':'Нет связи с сервером',0,e.name==='AbortError'?'timeout':'network')}finally{clearTimeout(timer)}
}
export class Store{
 constructor(name){this.name=name}
 async open(){this.db=await new Promise((resolve,reject)=>{const r=indexedDB.open(this.name,1);r.onupgradeneeded=()=>r.result.createObjectStore('data');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});return this}
 async get(key){return new Promise((resolve,reject)=>{const t=this.db.transaction('data'),r=t.objectStore('data').get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
 async update(key,fn){return new Promise((resolve,reject)=>{const t=this.db.transaction('data','readwrite'),o=t.objectStore('data'),r=o.get(key);let value;r.onsuccess=()=>{try{value=fn(r.result);o.put(value,key)}catch(e){t.abort();reject(e)}};t.oncomplete=()=>resolve(value);t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error)})}
 async updateOwned(key,owner,generation,fn){return new Promise((resolve,reject)=>{
  const t=this.db.transaction('data','readwrite'),o=t.objectStore('data');let value,failed=false;
  o.get('writer').onsuccess=event=>{const lease=event.target.result;
   if(lease?.owner!==owner||lease.generation!==generation||lease.expires<=Date.now()){
    failed=true;t.abort();reject(new Error('Запись открыта в другой вкладке'));return;
   }
   o.get(key).onsuccess=row=>{try{value=fn(row.target.result);o.put(value,key)}catch(error){failed=true;t.abort();reject(error)}};
  };
  t.oncomplete=()=>resolve(value);t.onerror=()=>{if(!failed)reject(t.error)};t.onabort=()=>{if(!failed)reject(t.error)};
 })}
 async set(key,value){return new Promise((resolve,reject)=>{const t=this.db.transaction('data','readwrite');t.objectStore('data').put(value,key);t.oncomplete=()=>resolve();t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error)})}
}
export function project(bundle,queue){
 if(!bundle)return null;const b=structuredClone(bundle);
 for(const op of queue.filter(o=>o.workoutId===b.workout.id)){
 const p=op.body;
 if(op.path.endsWith('/exercises')&&op.method==='POST'){
  const d=p.definition_snapshot||p.exercise;
  b.workout.program_snapshot.exercise_library ||= {};
  if(!b.workout.program_snapshot.exercise_library[p.exercise.id])b.workout.program_snapshot.exercise_library[p.exercise.id]={...d};
  if(!b.exercises.some(e=>e.id===p.workout_entry_id))b.exercises.push({
   id:p.workout_entry_id,workout_id:b.workout.id,original_exercise_id:p.exercise.id,exercise_id:p.exercise.id,
   position:Math.max(0,...b.exercises.map(e=>e.position||0))+1,planned_sets:null,planned_reps:null,
   planned_seconds:null,planned_weight_kg:null,definition_snapshot:{...d},is_ad_hoc:true,
   removed:false,skipped:false,revision:1
  });
 }
 if(op.path.endsWith('/sets')&&op.method==='POST'&&!b.sets.some(s=>s.id===p.id))b.sets.push({...p,revision:1,completed_at:op.created});
 if(p.action==='undo_set')b.sets=b.sets.filter(s=>s.id!==p.set_id);
 if(['remove','restore','skip','unskip'].includes(p.action)){const e=b.exercises.find(e=>e.id===p.entry_id);if(e)e[['remove','restore'].includes(p.action)?'removed':'skipped']=['remove','skip'].includes(p.action)}
 if(op.path.endsWith('/finish'))Object.assign(b.workout,{status:p.status,finished_at:p.finished_at});
 }
 return b;
}
export class Queue{
 constructor(store,config,onChange){Object.assign(this,{store,config,onChange});this.running=false}
 async read(){return await this.store.get('queue')||[]}
 async add(op){const item={...op,id:uuid(),created:new Date().toISOString(),state:'local',body:{...op.body,idempotency_key:op.body?.idempotency_key||uuid()}};await this.store.update('queue',items=>[...(items||[]),item]);await this.onChange();void this.flush();return item}

 async flush(){
 if(this.running||!navigator.onLine||(this.canFlush&&!this.canFlush()))return;this.running=true;
 const run=async()=>{let items=await this.read();while(items.length){let op=items[0];if(op.state==='conflict')break;
 if(op.dependsOn&&items.some(parent=>parent.body?.idempotency_key===op.dependsOn))break;
 try{
  let result;
  if(op.sent){try{const status=await request(this.config,`/api/operations/${op.body.idempotency_key}`);if(status.status==='succeeded')result=status.result;if(status.status==='pending')break}catch(e){if(e.status!==404)throw e}}
  if(result===undefined){
   if(op.needsRevision&&!op.sent){const bundle=await this.store.get('workout:'+op.workoutId);op.body.revision=bundle?.workout.revision;if(!op.body.revision)throw new APIError('Нужно восстановить тренировку',409,'revision_conflict')}
   op.sent=true;op.state='sending';await this.store.update('queue',list=>list.map(x=>x.id===op.id?op:x));await this.onChange();
   result=await request(this.config,op.path,{method:op.method||'POST',body:op.body});
  }
  // Keep the committed operation until its read model has also been recovered.
  if(op.workoutId){const bundle=await request(this.config,`/api/workouts/${op.workoutId}`);await this.store.set('workout:'+op.workoutId,bundle);if((await this.store.get('bundle'))?.workout.id===op.workoutId)await this.store.set('bundle',bundle)}
  items=await this.store.update('queue',list=>list.filter(x=>x.id!==op.id));await this.onChange();
 }catch(e){await this.store.update('queue',list=>list.map(item=>item.id!==op.id?item:{...item,state:e.status===409?'conflict':e.code==='timeout'?'unknown':'retry',error:e.message}));await this.onChange();break}
 }};
 try{if(navigator.locks)await navigator.locks.request(`${this.store.name}:sync`,run);else await run()}finally{this.running=false}
 }
}

export function claimLease(current,owner,now,takeover=false){
 if(takeover||!current||current.expires<=now||current.owner===owner)return {owner,expires:now+15000,generation:current?.owner===owner&&!takeover?(current.generation||1):(current?.generation||0)+1};return current;
}
export class TabLease{
 constructor(store,onLost){this.store=store;this.owner=uuid();this.onLost=onLost;this.owned=false}
 async acquire(takeover=false){const row=await this.store.update('writer',old=>claimLease(old,this.owner,Date.now(),takeover));const owned=row.owner===this.owner;if(this.owned&&!owned)this.onLost();this.owned=owned;this.generation=owned?row.generation:null;return owned}
 start(){this.timer=setInterval(()=>{if(this.owned)void this.acquire()},5000)}
 stop(){clearInterval(this.timer);this.owned=false}
}
