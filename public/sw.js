const CACHE = 'ulu-v1';
const IMG_CACHE = 'ulu-img-v1';
const IMG_MAX = 200;
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
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== IMG_CACHE).map((k) => caches.delete(k))))
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

async function trimImages(cache) {
  const keys = await cache.keys();
  const extra = keys.length - IMG_MAX;
  for (let i = 0; i < extra; i++) await cache.delete(keys[i]);
}

async function imageCacheFirst(req) {
  const cache = await caches.open(IMG_CACHE);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  // Opaque (no-cors) responses have ok === false and status 0; cache them too.
  if (res && (res.ok || res.type === 'opaque')) {
    await cache.put(req, res.clone()).catch(() => {});
    await trimImages(cache);
  }
  return res;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.hostname === 'commons.wikimedia.org' || url.hostname === 'upload.wikimedia.org') {
    e.respondWith(imageCacheFirst(req));
    return;
  }
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
