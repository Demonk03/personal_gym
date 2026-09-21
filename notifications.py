"""Private push subscription endpoints. No health details in notification payloads."""
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5


def register_notifications(app, repo, auth):
    from flask import jsonify
    from app import _json, APIError

    @app.get('/api/push/config')
    @auth
    def config():
        key=os.getenv('VAPID_PUBLIC_KEY','')
        enabled=bool(key and os.getenv('VAPID_PRIVATE_KEY') and os.getenv('VAPID_SUBJECT'))
        return jsonify({'enabled':enabled,'public_key':key if enabled else None})

    @app.post('/api/push/subscription')
    @auth
    def subscribe():
        p=_json();sub=p.get('subscription');prefs=p.get('preferences')
        if not isinstance(sub,dict) or not isinstance(prefs,dict):raise APIError('Некорректная подписка')
        url=sub.get('endpoint','');keys=sub.get('keys',{})
        if not isinstance(url,str) or len(url)>2048 or not isinstance(keys,dict):raise APIError('Некорректная подписка')
        u=urlparse(url)
        allowed={'fcm.googleapis.com','updates.push.services.mozilla.com','push.services.mozilla.com','web.push.apple.com'}
        if u.scheme!='https' or u.hostname not in allowed or u.username or u.password or u.port not in {None,443}:raise APIError('Неизвестный сервер push')
        for k in ('p256dh','auth'):
            if not isinstance(keys.get(k),str) or not re.fullmatch(r'[A-Za-z0-9_=-]{16,200}',keys[k]):raise APIError('Некорректный ключ подписки')
        if set(prefs) != {'review'} or not isinstance(prefs.get('review'),bool):raise APIError('Некорректные настройки')
        row={'id':str(uuid5(NAMESPACE_URL,url)),'endpoint':url,'p256dh':keys['p256dh'],'auth':keys['auth'],
             'active':prefs['review'],'preferences':{'review':prefs['review']}}
        r=repo()
        if hasattr(r,'client'):r.client.table('push_subscriptions').upsert(row,on_conflict='endpoint').execute()
        else:
            if not hasattr(r,'subscriptions'):r.subscriptions={}
            r.subscriptions[row['id']]=row
        return jsonify({'saved':True})
