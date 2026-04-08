/* Network-first for same-origin assets; cache successful GETs for offline shell. Skips /api/* and WS. */
const CACHE = 'cryptochatpal-shell-v1';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          const p = url.pathname;
          if (
            p === '/' ||
            p.endsWith('.html') ||
            p.endsWith('.css') ||
            p.endsWith('.js') ||
            p.endsWith('.json') ||
            p.endsWith('.svg')
          ) {
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('/')))
  );
});
