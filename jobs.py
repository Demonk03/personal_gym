"""Run once per minute as a separate worker: python3 jobs.py. No real data in logs."""
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo


def due_events(workouts,checkins,now,tz_name):
    local=now.astimezone(ZoneInfo(tz_name));events=[]
    if local.isoweekday()==1 and local.hour>=9:
        week=(local.date()-timedelta(days=7)).isoformat()
        events.append({'key':'review:'+week,'kind':'review','tag':'weekly-review','week_start':week})
    return events


def deliver(subscription,private_key,subject,tag,sender=None):
    if sender is None:
        from pywebpush import webpush
        sender=webpush
    return sender(subscription_info={'endpoint':subscription['endpoint'],'keys':{'p256dh':subscription['p256dh'],'auth':subscription['auth']}},
        data=json.dumps({'tag':tag}),vapid_private_key=private_key,vapid_claims={'sub':subject},ttl=86400,timeout=15)


def run_once(repository=None,now=None,sender=None):
    import db
    from app import create_app
    from integration import rows
    r=repository or db.SupabaseRepository();now=now or datetime.now(timezone.utc)
    if not all(os.getenv(k) for k in ('VAPID_PRIVATE_KEY','VAPID_PUBLIC_KEY','VAPID_SUBJECT','API_KEY')):return {'configured':False}
    profile=r.bootstrap().get('profile') or {}
    events=due_events(r.list_history(),rows(r,'checkins'),now,profile.get('timezone','Europe/Belgrade'))
    subscriptions=r.client.table('push_subscriptions').select('*').eq('active',True).execute().data
    sent=0
    for event in events:
        if event['kind']=='review':
            response=create_app(repository=r).test_client().post('/api/weekly-reviews/generate',json={'idempotency_key':str(uuid5(NAMESPACE_URL,event['key'])),'week_start':event['week_start']},headers={'Authorization':'Bearer '+os.environ['API_KEY']})
            if response.status_code not in (200,201):continue
        for sub in subscriptions:
            if not sub.get('preferences',{}).get(event['kind']):continue
            logical=event['key']+':'+sub['id']
            claim=r._rpc('gym_claim_notification',{'p_key':logical,'p_kind':'weekly_review'})
            if not claim.get('claimed'):continue
            try:
                deliver(sub,os.environ['VAPID_PRIVATE_KEY'],os.environ['VAPID_SUBJECT'],event['tag'],sender)
                r.client.table('scheduled_jobs').update({'status':'succeeded','updated_at':now.isoformat()}).eq('id',claim['id']).eq('attempts',claim['attempts']).execute()
                sent+=1
            except Exception as e:
                code=getattr(getattr(e,'response',None),'status_code',None)
                if code in (404,410):r.client.table('push_subscriptions').update({'active':False}).eq('id',sub['id']).execute()
                r.client.table('scheduled_jobs').update({'status':'failed','last_error':'push_delivery_failed','updated_at':now.isoformat()}).eq('id',claim['id']).eq('attempts',claim['attempts']).execute()
    return {'configured':True,'sent':sent}


if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv()
    print(json.dumps(run_once()))
