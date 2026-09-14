from copy import deepcopy
from uuid import uuid4
from test_training import base_checkin


def post(client,auth,path,body):
    return client.post(path,json={'idempotency_key':str(uuid4()),**body},headers=auth)


def prepared(client,auth):
    r=post(client,auth,'/api/workouts/prepare',{'checkin':base_checkin(),'is_extra':True})
    assert r.status_code==201
    return r.json


def test_reprepare_preserves_identity_and_blocks_without_second_workout(client,auth,repository):
    b=prepared(client,auth);wid=b['workout']['id'];c=base_checkin();c['back_pain']=7
    r=post(client,auth,f'/api/workouts/{wid}/edit',{'action':'reprepare','revision':1,'checkin':c})
    assert r.status_code==200 and r.json['workout']['checkin_mode']=='yellow'
    assert len(repository.workouts)==1
    assert r.json['exercises'][0]['planned_sets']==2
    c['systemic_symptoms']['fainting']=True
    r=post(client,auth,f'/api/workouts/{wid}/edit',{'action':'reprepare','revision':2,'checkin':c})
    assert r.status_code==200 and r.json['workout']['checkin_mode']=='red'
    assert repository.get_active_workout() is None
    assert client.get('/api/today',headers=auth).json['blocked_checkin']['evaluation']['blocks_workout']


def test_remove_restore_skip_undo_and_revision_conflict(client,auth):
    b=prepared(client,auth);wid=b['workout']['id'];eid=b['exercises'][0]['id']
    r=post(client,auth,f'/api/workouts/{wid}/edit',{'action':'remove','entry_id':eid,'revision':1})
    assert r.json['exercises'][0]['removed']
    assert post(client,auth,f'/api/workouts/{wid}/edit',{'action':'restore','entry_id':eid,'revision':1}).status_code==409
    assert post(client,auth,f'/api/workouts/{wid}/edit',{'action':'restore','entry_id':eid,'revision':2}).status_code==200
    assert post(client,auth,f'/api/workouts/{wid}/start',{'revision':3}).status_code==200
    sid=str(uuid4());payload={'idempotency_key':str(uuid4()),'id':sid,'workout_exercise_id':eid,'set_number':1,'actual_reps':6}
    for _ in range(2):assert client.post(f'/api/workouts/{wid}/sets',json=payload,headers=auth).status_code==201
    assert post(client,auth,f'/api/workouts/{wid}/edit',{'action':'remove','entry_id':eid,'revision':4}).status_code==409
    r=post(client,auth,f'/api/workouts/{wid}/edit',{'action':'undo_set','set_id':sid,'set_revision':1,'revision':4})
    assert r.status_code==200 and not r.json['sets']
    r=post(client,auth,f'/api/workouts/{wid}/edit',{'action':'skip','entry_id':eid,'revision':5})
    assert r.json['exercises'][0]['skipped']
    assert post(client,auth,f'/api/workouts/{wid}/sets',{'id':str(uuid4()),'workout_exercise_id':eid,'set_number':1,'actual_reps':6}).status_code==409


def test_measurement_idempotency_validation_and_export(client,auth):
    p={'idempotency_key':str(uuid4()),'measured_at':'2026-09-13T08:00:00+02:00','waist_cm':96,'chest_cm':104,'hips_cm':103,'thigh_cm':60}
    for _ in range(2):assert client.post('/api/measurements',json=p,headers=auth).status_code==201
    assert len(client.get('/api/measurements',headers=auth).json['entries'])==1
    assert len(client.get('/api/export.json',headers=auth).json['data']['body_measurements'])==1
    assert b'measurement' in client.get('/api/export.csv',headers=auth).data
    assert post(client,auth,'/api/measurements',{**p,'waist_cm':-1}).status_code==400


def test_extra_date_and_full_bootstrap(client,auth):
    b=prepared(client,auth)
    assert b['workout']['is_extra'] is True and b['workout']['scheduled_date']
    boot=client.get('/api/bootstrap',headers=auth).json
    assert boot['sessions'] and boot['contract_version']==1


def test_incomplete_session_must_finish_early(client,auth):
    b=prepared(client,auth);wid=b['workout']['id']
    post(client,auth,f'/api/workouts/{wid}/start',{'revision':1})
    body={'revision':2,'status':'completed','post_checkin':{'overall_difficulty':5,'back_pain':3,'leg_symptoms_change':'same'}}
    assert post(client,auth,f'/api/workouts/{wid}/finish',body).status_code==409
    body.update(status='stopped_early',stop_reason='Нет времени')
    assert post(client,auth,f'/api/workouts/{wid}/finish',body).status_code==200
