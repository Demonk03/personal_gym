const CACHE='personal-gym-shell-v2';
const SHELL=['./','./index.html','./style.css','./app.js','./data.js','./config.js','./icon.svg','./manifest.json','./fonts/Onest-400.ttf','./fonts/Onest-500.ttf','./fonts/Onest-600.ttf','./fonts/Onest-700.ttf'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('personal-gym-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const url=new URL(e.request.url);if(e.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.includes('/api/')||e.request.headers.has('Authorization'))return;
 if(!SHELL.some(p=>new URL(p,self.registration.scope).pathname===url.pathname))return;
 e.respondWith(fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return r}).catch(()=>caches.match(e.request).then(r=>r||caches.match('./index.html'))))});
self.addEventListener('push',e=>{let data={};try{data=e.data.json()}catch{}e.waitUntil(self.registration.showNotification('Personal Gym',{body:'В приложении есть обновление.',icon:'./icon.svg',tag:data.tag||'gym',data:{url:self.registration.scope}}))});
self.addEventListener('notificationclick',e=>{e.notification.close();e.waitUntil(self.clients.matchAll({type:'window'}).then(async clients=>{const client=clients.find(c=>c.url.startsWith(self.registration.scope));if(client)return client.focus();return self.clients.openWindow(self.registration.scope)}))});
