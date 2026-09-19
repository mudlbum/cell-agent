// Only public app shell files; never cache chat text or proxy model requests here.
const CACHE='cell-shell-mobile-v1';
const FILES=['chat.html','chat-web.js','chat-core.mjs','chat-web.css','inference-worker.js','cell.webmanifest','mobile.html','assets/cell-mark.svg','assets/cell-app-192.png','assets/cell-app-512.png'];
const urls=FILES.map(p=>new URL(p,self.registration.scope).href);
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(urls))));
self.addEventListener('activate',e=>e.waitUntil((async()=>{for(const k of await caches.keys())if(k.startsWith('cell-shell-')&&k!==CACHE)await caches.delete(k);await self.clients.claim();})()));
self.addEventListener('fetch',e=>{
 if(e.request.method!=='GET'||!urls.includes(e.request.url))return;
 e.respondWith((async()=>{const c=await caches.open(CACHE);try{const r=await fetch(e.request);if(r.ok)await c.put(e.request,r.clone());return r;}catch(err){const saved=await c.match(e.request);if(saved)return saved;throw err;}})());
});
