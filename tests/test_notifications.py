from datetime import datetime,timezone
from jobs import due_events,deliver


def test_next_day_timezone_and_answer_suppress_notification():
    w={'id':'w','status':'completed','finished_at':'2026-09-12T22:30:00Z'}
    assert not due_events([w],[],datetime(2026,9,13,9,tzinfo=timezone.utc),'Europe/Belgrade')
    events=due_events([w],[],datetime(2026,9,14,7,tzinfo=timezone.utc),'Europe/Belgrade')
    assert any(e['kind']=='next_day' for e in events)
    answered=due_events([w],[{'workout_id':'w','kind':'next_day'}],datetime(2026,9,14,7,tzinfo=timezone.utc),'Europe/Belgrade')
    assert not any(e['kind']=='next_day' for e in answered)


def test_delivery_is_neutral_and_uses_short_timeout():
    sent=[]
    deliver({'endpoint':'https://fcm.googleapis.com/test','p256dh':'fake','auth':'fake'},'fake','mailto:test@example.com','next-day',lambda **kw:sent.append(kw))
    assert sent[0]['data']=='{"tag": "next-day"}'
    assert sent[0]['timeout']==15


def test_push_subscription_rejects_arbitrary_fetch_targets(client,auth):
    p={'subscription':{'endpoint':'https://127.0.0.1/private','keys':{'auth':'x'*22,'p256dh':'x'*80}},'preferences':{'next_day':True,'review':True}}
    assert client.post('/api/push/subscription',json=p,headers=auth).status_code==400
    p['subscription']['endpoint']='https://fcm.googleapis.com/test'
    assert client.post('/api/push/subscription',json=p,headers=auth).status_code==200
