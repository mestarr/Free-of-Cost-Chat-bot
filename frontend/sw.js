/* PWA shell: precache app assets; network-first with offline fallback. Skips /api/* and WS. */
const CACHE = 'cryptochatpal-shell-v2';
const PRECACHE = ['/', '/index.html', '/css/style.css', '/js/app.js', '/js/offline-llm.js', '/manifest.json', '/favicon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => {})).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() =>
      self.clients.claim()
    )
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
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
        .catch(() => cached || caches.match('/'));
      return cached || network;
    })
  );
});
