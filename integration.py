"""Handoff integration: explicit edit operations and read models for the PWA."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import db
from operations import execute_operation
from training import build_workout, evaluate_checkin


def rows(repo, table):
    if hasattr(repo, 'client'):
        return repo.client.table(table).select('*').execute().data
    mapping = {'checkins': repo.checkins, 'body_measurements': repo.measurements}
    return list(deepcopy(mapping[table]).values())


def edit(repo, operation, digest, workout_id, revision, action, data):
    if hasattr(repo, 'client'):
        result = repo._rpc('gym_edit', dict(p_operation_id=operation, p_body_hash=digest,
            p_workout_id=workout_id, p_revision=revision, p_action=action, p_data=data))
        return repo.get_workout(result['workout_id'])
    def mutate():
        w = repo.workouts.get(workout_id)
        if not w: raise db.NotFound('workout_not_found')
        if w['revision'] != revision: raise db.RevisionConflict('revision_conflict')
        if action == 'reprepare':
            if w['status'] != 'preparing': raise db.Conflict('invalid_workout_state')
            for key in [k for k,v in repo.exercises.items() if v['workout_id'] == workout_id]: del repo.exercises[key]
            for e in data['exercises']:
                repo.exercises[e['id']] = {**deepcopy(e), 'workout_id': workout_id, 'revision': 1, 'skipped': False, 'removed': False}
            w.update(checkin_mode=data['evaluation']['mode'], checkin_reasons=data['evaluation']['reasons'], program_snapshot=data['snapshot'])
            for c in repo.checkins.values():
                if c.get('workout_id') == workout_id and c['kind'] == 'pre':
                    c.update(payload=data['checkin'], evaluation=data['evaluation'], revision=c['revision']+1, updated_at=db.utc_now())
            if data['evaluation']['blocks_workout']: w.update(status='cancelled', finished_at=db.utc_now())
        elif action in {'remove', 'restore', 'skip', 'unskip'}:
            if w['status'] not in {'preparing','in_progress'}: raise db.Conflict('invalid_workout_state')
            e = repo.exercises.get(data['entry_id'])
            if not e or e['workout_id'] != workout_id: raise db.NotFound('workout_exercise_not_found')
            if action == 'remove' and any(s['workout_exercise_id'] == e['id'] for s in repo.sets.values()): raise db.Conflict('exercise_has_sets')
            e['removed' if action in {'remove','restore'} else 'skipped'] = action in {'remove','skip'}
            e['skip_reason'] = data.get('reason', '')
            e['revision'] += 1
        elif action == 'undo_set':
            if w['status'] != 'in_progress': raise db.Conflict('invalid_workout_state')
            item = repo.sets.get(data['set_id'])
            if not item or item['workout_id'] != workout_id: raise db.NotFound('set_not_found')
            if item['revision'] != data['set_revision']: raise db.RevisionConflict('revision_conflict')
            del repo.sets[item['id']]
        elif action == 'edit_post':
            if w['status'] not in {'completed','stopped_early'}: raise db.Conflict('invalid_workout_state')
            c = next(c for c in repo.checkins.values() if c.get('workout_id') == workout_id and c['kind'] == 'post')
            c.update(payload=data['post_checkin'], revision=c['revision']+1, updated_at=db.utc_now())
            w['edited_at'] = db.utc_now()
        else: raise db.Conflict('invalid_edit')
        w.update(revision=revision+1, updated_at=db.utc_now())
        repo.edits.append({'workout_id': workout_id, 'action': action, 'data': deepcopy(data), 'created_at': db.utc_now()})
        return repo.get_workout(workout_id)
    return execute_operation(repo, operation, action, workout_id, data, mutate, digest)


def register_integration(app, repo, auth):
    from flask import jsonify, request
    from app import _json, _operation, _integer, _uuid, _number, _timestamp, _post_checkin, APIError
    from operations import body_hash

    @app.get('/api/today')
    @auth
    def today():
        r = repo(); boot = r.bootstrap()
        tz = ZoneInfo((boot.get('profile') or {}).get('timezone', 'Europe/Belgrade'))
        day = datetime.now(tz).date()
        return jsonify({'date': day.isoformat(), 'active': r.get_active_workout(),
            'scheduled': [s for s in boot.get('sessions', []) if s.get('weekday') == day.isoweekday()]})

    @app.post('/api/workouts/<workout_id>/edit')
    @auth
    def edit_workout(workout_id):
        p = _json(); op = _operation(p); wid = _uuid(workout_id,'workout_id')
        revision = _integer(p,'revision',1,1000000); action = p.get('action'); data = {}
        if action == 'reprepare':
            current = repo().get_workout(wid)['workout']
            program = current['program_snapshot']
            evaluation = evaluate_checkin(p.get('checkin'), program['rules'])
            if not evaluation['complete']: raise APIError('Заполни все ответы',422,'checkin_incomplete')
            plan = build_workout(program,evaluation,p['checkin']['equipment'])
            data = {'checkin':p['checkin'],'evaluation':evaluation, 'snapshot':{**program,'omitted':plan['omitted'] if plan else []},'exercises':plan['exercises'] if plan else []}
        elif action in {'remove','restore','skip','unskip'}:
            data = {'entry_id':_uuid(p.get('entry_id'),'entry_id')}
        elif action == 'undo_set':
            data = {'set_id':_uuid(p.get('set_id'),'set_id'),'set_revision':_integer(p,'set_revision',1,1000000)}
        elif action == 'edit_post': data = {'post_checkin':_post_checkin(p.get('post_checkin'))}
        else: raise APIError('Неизвестное действие')
        return jsonify(edit(repo(),op,body_hash(p),wid,revision,action,data))

    @app.get('/api/measurements')
    @auth
    def measurements():
        return jsonify({'entries': sorted(rows(repo(),'body_measurements'),key=lambda r:r['measured_at'])})

    @app.post('/api/measurements')
    @auth
    def save_measurement():
        p = _json(); op = _operation(p)
        data = {'id':op,'measured_at':_timestamp(p,'measured_at')}
        for field in ('waist_cm','chest_cm','hips_cm','thigh_cm'): data[field] = _number(p,field,10,300,required=True)
        r=repo()
        if hasattr(r,'client'): result=r._rpc('gym_measurement',{'p_operation_id':op,'p_body_hash':body_hash(p),'p_data':data})
        else:
            def save():
                r.measurements[op]={**data,'revision':1}
                return r.measurements[op]
            result=execute_operation(r,op,'measurement',op,p,save,body_hash(p))
        return jsonify(result),201
