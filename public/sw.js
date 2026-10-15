const CACHE = 'ulu-v13';
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

// Network-first, but on flaky roaming data a fetch can hang for a minute before failing. After
// TIMEOUT_MS a cached copy is served instead; with nothing cached the network is still awaited.
// The slow fetch keeps running and refreshes the cache for next time.
const TIMEOUT_MS = 3000;

async function networkFirst(req, fallbackKey, event) {
  const cache = await caches.open(CACHE);
  const cached = async () => (await cache.match(req)) || (fallbackKey ? cache.match(fallbackKey) : undefined);
  const net = fetch(req);
  // Registered before the response is handed out, so the clone is taken while the body is unread.
  const update = net.then((res) => (res && res.ok ? cache.put(req, res.clone()) : null)).catch(() => {});
  if (event) event.waitUntil(update);

  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, v) => { if (!settled) { settled = true; clearTimeout(timer); fn(v); } };
    const timer = setTimeout(() => {
      cached().then((hit) => { if (hit) finish(resolve, hit); }, () => {});
    }, TIMEOUT_MS);
    net.then((res) => finish(resolve, res), (err) => {
      cached().then((hit) => (hit ? finish(resolve, hit) : finish(reject, err)), () => finish(reject, err));
    });
  });
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Cross-origin (Commons photos) is left to the browser: a fetch made BY the worker is bound
  // by the CSP connect-src 'self' and was blocked live, and opaque cache entries bloat quota.
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    e.respondWith(networkFirst(req, './', e));
    return;
  }
  if (url.pathname.includes('/data/') && url.pathname.endsWith('.json')) {
    e.respondWith(networkFirst(req, null, e));
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
