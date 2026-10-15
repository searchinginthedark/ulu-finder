const CACHE = 'ulu-v8';
const ASSETS = [
  './',
  'app.js',
  'styles.css',
  'manifest.webmanifest',
  'data/index.json',
  'icon-192.png',
  'icon-512.png',
  'apple-touch-icon.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => Promise.all(ASSETS.map((a) => c.add(a).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(req, fallbackKey) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
    return res;
  } catch (err) {
    const hit = await cache.match(req);
    if (hit) return hit;
    if (fallbackKey) {
      const fb = await cache.match(fallbackKey);
      if (fb) return fb;
    }
    throw err;
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Cross-origin (Commons photos) is left to the browser: a fetch made BY the worker is bound
  // by the CSP connect-src 'self' and was blocked live, and opaque cache entries bloat quota.
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    e.respondWith(networkFirst(req, './'));
    return;
  }
  if (url.pathname.includes('/data/') && url.pathname.endsWith('.json')) {
    e.respondWith(networkFirst(req, null));
    return;
  }
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return res;
    }))
  );
});
