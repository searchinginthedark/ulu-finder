// Runs the REAL public/sw.js fetch handler in a ServiceWorkerGlobalScope shim and checks the
// network-first-with-timeout contract. Run by tests/test_sw.py; exits 1 on the first failure.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC = readFileSync(fileURLToPath(new URL('../public/sw.js', import.meta.url)), 'utf8');
const ORIGIN = 'https://ulu.test';
const FAST_MS = 40; // TIMEOUT_MS is shrunk to this so the suite runs in well under a second

if (!/const TIMEOUT_MS = 3000;/.test(SRC)) throw new Error('sw.js no longer declares TIMEOUT_MS = 3000');
const src = SRC.replace('const TIMEOUT_MS = 3000;', `const TIMEOUT_MS = ${FAST_MS};`);

function makeCache(entries) {
  const store = new Map(Object.entries(entries).map(([k, v]) => [new URL(k, ORIGIN + '/').href, v]));
  const key = (r) => new URL(typeof r === 'string' ? r : r.url, ORIGIN + '/').href;
  const c = {
    puts: [],
    async match(r) { const v = store.get(key(r)); return v ? new Response(v) : undefined; },
    async put(r, res) { const body = await res.text(); store.set(key(r), body); c.puts.push(key(r)); },
    async add() {}
  };
  return c;
}

// network: { body, ms } resolves after ms; { fail: true, ms } rejects; { hang: true } never settles
function load(cacheEntries, network) {
  const handlers = {};
  const cache = makeCache(cacheEntries);
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (t, fn) => { handlers[t] = fn; },
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() }
  };
  const caches = { open: async () => cache, match: (r) => cache.match(r), keys: async () => [], delete: async () => true };
  const fetch = () => new Promise((res, rej) => {
    if (network.hang) return;
    setTimeout(() => (network.fail ? rej(new TypeError('offline')) : res(new Response(network.body))), network.ms || 0);
  });
  new Function('self', 'caches', 'fetch', src)(self, caches, fetch);
  return { handlers, cache };
}

async function run(path, mode, cacheEntries, network) {
  const { handlers, cache } = load(cacheEntries, network);
  let responded = null;
  const waits = [];
  const req = { method: 'GET', url: ORIGIN + path, mode };
  handlers.fetch({ request: req, respondWith: (p) => { responded = p; }, waitUntil: (p) => waits.push(p) });
  if (!responded) throw new Error('handler did not respondWith for ' + path);
  const t0 = Date.now();
  const out = await Promise.race([
    responded.then((r) => r.text()).then((t) => ({ text: t }), (e) => ({ error: e })),
    new Promise((r) => setTimeout(() => r({ pending: true }), 1000))
  ]);
  const ms = Date.now() - t0;
  // let a slow background refresh land; a hung network never settles, so cap the wait
  await Promise.race([Promise.all(waits), new Promise((r) => setTimeout(r, 500))]);
  return { ...out, ms, cache };
}

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log('ok   ' + name); return; }
  failed++; console.log('FAIL ' + name + ' ' + JSON.stringify(detail));
}

const DATA = '/data/TH.json';
let r;

r = await run(DATA, 'cors', { [DATA]: 'old' }, { body: 'new', ms: 5 });
check('fast network wins over a cache hit (PWA-011 shape)', r.text === 'new', r);
check('fast network refreshes the cache', r.cache.puts.length === 1, r.cache.puts);

r = await run(DATA, 'cors', { [DATA]: 'old' }, { body: 'new', ms: 300 });
check('slow network + cache hit serves the cache at the timeout', r.text === 'old' && r.ms < 200, r);
check('slow network still refreshes the cache afterwards', r.cache.puts.length === 1, r.cache.puts);

r = await run(DATA, 'cors', {}, { body: 'new', ms: 150 });
check('slow network + cache miss waits for the network', r.text === 'new', r);

r = await run(DATA, 'cors', { [DATA]: 'old' }, { hang: true });
check('hung network + cache hit serves the cache', r.text === 'old', r);

r = await run(DATA, 'cors', { [DATA]: 'old' }, { fail: true, ms: 5 });
check('network failure + cache hit serves the cache at once', r.text === 'old' && r.ms < FAST_MS, r);

r = await run(DATA, 'cors', {}, { fail: true, ms: 5 });
check('network failure + no cache rejects', !!r.error, r);

r = await run('/some/deep/link', 'navigate', { './': 'shell' }, { fail: true, ms: 5 });
check('navigation offline falls back to the cached shell', r.text === 'shell', r);

r = await run('/', 'navigate', { './': 'shell' }, { body: 'fresh', ms: 300 });
check('slow navigation serves the cached shell at the timeout', r.text === 'shell' && r.ms < 200, r);

process.exit(failed ? 1 : 0);
