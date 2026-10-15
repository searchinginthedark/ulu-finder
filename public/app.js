'use strict';
(function () {
  var PAGE = 24;
  var K_COUNTRY = 'ulu.country';
  var K_SAVED = 'ulu.saved.v1';
  var K_OPENS = 'ulu.opens.v1';
  var DINE_CATS = ['dine', 'markets', 'cafes'];

  var $ = function (id) { return document.getElementById(id); };

  /* ---------- storage (every access guarded) ---------- */
  function read(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  }
  function write(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* storage unavailable */ }
  }
  function readStr(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function writeStr(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* ignore */ }
  }

  /* ---------- local-only open counter (calendar days foregrounded, 60 days kept) ---------- */
  var OPEN_GAP_MS = 30 * 60 * 1000;
  var lastOpenCount = 0;
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function dateKey(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function countOpen() {
    var now = Date.now();
    if (now - lastOpenCount < OPEN_GAP_MS) return;
    lastOpenCount = now;
    var opens = read(K_OPENS, {});
    if (!opens || typeof opens !== 'object') opens = {};
    var today = dateKey(new Date(now));
    opens[today] = (opens[today] || 0) + 1;
    var cutoff = dateKey(new Date(now - 60 * 86400000));
    Object.keys(opens).forEach(function (k) { if (k < cutoff) delete opens[k]; });
    write(K_OPENS, opens);
  }
  // exposed for console inspection: ulu.openedDays(30)
  function openedDays(days) {
    var opens = read(K_OPENS, {});
    var n = 0;
    for (var i = 0; i < days; i++) if (opens[dateKey(new Date(Date.now() - i * 86400000))]) n++;
    return n;
  }
  window.ulu = { openedDays: openedDays };
  document.addEventListener('visibilitychange', function () { if (!document.hidden) countOpen(); });
  countOpen();

  /* ---------- helpers ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = text;
    return n;
  }
  function safeHttp(u) {
    if (typeof u !== 'string') return null;
    return /^https?:\/\//i.test(u) ? u : null;
  }
  // App deep links a platform's `mobile` template may use; anything else non-http is dropped.
  var APP_LINK = /^xhsdiscover:\/\//i;
  // Platforms serve phones different (often broken) search pages, so the choice follows the UA,
  // like their servers do. iPadOS reports a Mac UA; touch points give it away.
  var IS_PHONE = (function () {
    try { if (navigator.userAgentData && navigator.userAgentData.mobile) return true; } catch (e) {}
    var ua = navigator.userAgent || '';
    return /Android|iPhone|iPad|iPod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  })();
  // TikTok /discover/{slug}: lowercase, every run of non-letters to '-'. \p{M} keeps Thai and
  // Vietnamese marks attached to their letters.
  function slugify(s) {
    return String(s).toLowerCase().replace(/[^\p{L}\p{M}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '');
  }
  function safeImg(u) {
    var s = safeHttp(u);
    if (!s) return null;
    try {
      var h = new URL(s).hostname;
      return h === 'commons.wikimedia.org' ? s : null;
    } catch (e) { return null; }
  }
  function fmtDate(iso) {
    if (!iso) return 'unknown';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 10);
    return d.toISOString().slice(0, 10);
  }
  function debounce(fn, ms) {
    var t;
    return function () {
      var a = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(null, a); }, ms);
    };
  }
  function haversine(lat1, lon1, lat2, lon2) {
    var R = 6371, rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }
  function fmtKm(km) {
    return km < 10 ? km.toFixed(1) + ' km' : Math.round(km) + ' km';
  }

  /* ---------- state ---------- */
  var S = {
    index: null,
    cats: [],
    cc: null,
    data: null,          // current country file
    cache: {},           // cc -> country file
    r1: '',
    r2: '',
    cat: '',
    q: '',
    sort: 'local',       // local | top | near
    pos: null,           // {lat, lon}
    view: 'feed',        // feed | saved
    saved: read(K_SAVED, {}),
    list: [],
    shown: 0,
    gen: 0
  };
  if (!S.saved || typeof S.saved !== 'object' || Array.isArray(S.saved)) S.saved = {};

  var regionById = {};
  var io = null;

  function catLabel(id) {
    for (var i = 0; i < S.cats.length; i++) if (S.cats[i].id === id) return S.cats[i].label;
    return id;
  }
  function savedKey(cc, id) { return cc + ':' + id; }
  function savedCount() { return Object.keys(S.saved).length; }

  /* ---------- data loading ---------- */
  function fetchJson(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function ensureCountry(cc) {
    if (S.cache[cc]) return Promise.resolve(S.cache[cc]);
    var c = null;
    (S.index.countries || []).forEach(function (x) { if (x.cc === cc) c = x; });
    if (!c || !c.enabled || !c.file) return Promise.reject(new Error('not available'));
    return fetchJson(c.file).then(function (d) {
      S.cache[cc] = d;
      return d;
    });
  }

  /* ---------- filtering ---------- */
  function norm(s) { return (s || '').toLowerCase(); }

  function baseFiltered(spots) {
    var q = norm(S.q.trim());
    return spots.filter(function (s) {
      if (S.r1 && s.r1 !== S.r1) return false;
      if (S.r2 && s.r2 !== S.r2) return false;
      if (q) {
        if (norm(s.name).indexOf(q) < 0 && norm(s.local).indexOf(q) < 0 && norm(s.dest).indexOf(q) < 0) return false;
      }
      return true;
    });
  }

  function computeList() {
    var spots;
    if (S.view === 'saved') {
      spots = Object.keys(S.saved).map(function (k) { return S.saved[k]; });
      var q = norm(S.q.trim());
      var items = spots.filter(function (e) {
        if (!q) return true;
        var s = e.spot;
        return norm(s.name).indexOf(q) >= 0 || norm(s.local).indexOf(q) >= 0 || norm(s.dest).indexOf(q) >= 0;
      }).map(function (e) { return { spot: e.spot, cc: e.cc, rn: e.rn || '' }; });
      return items;
    }
    if (!S.data) return [];
    var base = baseFiltered(S.data.spots || []);
    if (S.cat) base = base.filter(function (s) { return s.cat === S.cat; });
    var out = base.map(function (s) { return { spot: s, cc: S.cc, rn: regionName(s) }; });
    if (S.sort === 'local') {
      // Unscored spots keep the file's own (Famous) order after the scored ones; sort is stable.
      out.sort(function (a, b) {
        var x = typeof a.spot.ulu === 'number' ? a.spot.ulu : -1;
        var y = typeof b.spot.ulu === 'number' ? b.spot.ulu : -1;
        return y - x;
      });
    } else if (S.sort === 'near' && S.pos) {
      out.forEach(function (it) {
        var s = it.spot;
        it.km = (typeof s.lat === 'number' && typeof s.lon === 'number')
          ? haversine(S.pos.lat, S.pos.lon, s.lat, s.lon) : null;
      });
      out.sort(function (a, b) {
        if (a.km === null && b.km === null) return 0;
        if (a.km === null) return 1;
        if (b.km === null) return -1;
        return a.km - b.km;
      });
    }
    return out;
  }

  function regionName(s) {
    var r = regionById[s.r2] || regionById[s.r1];
    return r ? r.name : '';
  }

  /* ---------- tabs ---------- */
  function makeTab(label, count, selected, onClick) {
    var b = el('button', 'tab');
    b.type = 'button';
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', selected ? 'true' : 'false');
    b.appendChild(document.createTextNode(label));
    if (count !== null && count !== undefined) b.appendChild(el('span', 'n', String(count)));
    b.addEventListener('click', onClick);
    return b;
  }
  function keepScroll(row, build) {
    var left = row.scrollLeft;
    row.textContent = '';
    build();
    row.scrollLeft = left;
  }

  function renderRegions() {
    var d = S.data;
    var r1Row = $('r1Row'), r2Row = $('r2Row');
    if (!d) { r1Row.textContent = ''; r2Row.hidden = true; return; }
    var lvl1 = (d.regions || []).filter(function (r) { return r.level === 1; });
    keepScroll(r1Row, function () {
      r1Row.appendChild(makeTab('All', (d.spots || []).length, !S.r1, function () { selectRegion('', ''); }));
      lvl1.forEach(function (r) {
        r1Row.appendChild(makeTab(r.name, r.count, S.r1 === r.id, function () { selectRegion(r.id, ''); }));
      });
    });
    r1Row.hidden = lvl1.length === 0;
    var kids = S.r1 ? (d.regions || []).filter(function (r) { return r.level === 2 && r.parent === S.r1; }) : [];
    if (!kids.length) { r2Row.hidden = true; r2Row.textContent = ''; return; }
    r2Row.hidden = false;
    keepScroll(r2Row, function () {
      var parent = regionById[S.r1];
      r2Row.appendChild(makeTab('All ' + (parent ? parent.name : ''), parent ? parent.count : null, !S.r2, function () { selectRegion(S.r1, ''); }));
      kids.forEach(function (r) {
        r2Row.appendChild(makeTab(r.name, r.count, S.r2 === r.id, function () { selectRegion(S.r1, r.id); }));
      });
    });
  }

  function renderCats() {
    var row = $('catRow');
    var base = S.data ? baseFiltered(S.data.spots || []) : [];
    var counts = {};
    base.forEach(function (s) { counts[s.cat] = (counts[s.cat] || 0) + 1; });
    if (S.cat && !counts[S.cat]) S.cat = '';
    keepScroll(row, function () {
      row.appendChild(makeTab('All', base.length, !S.cat, function () { S.cat = ''; refresh(); }));
      S.cats.forEach(function (c) {
        if (!counts[c.id]) return;
        row.appendChild(makeTab(c.label, counts[c.id], S.cat === c.id, function () { S.cat = c.id; refresh(); }));
      });
    });
  }

  function selectRegion(r1, r2) {
    S.r1 = r1; S.r2 = r2;
    refresh();
  }

  /* ---------- feed ---------- */
  function refresh() {
    var saved = S.view === 'saved';
    $('filters').hidden = saved;
    $('toolbar').hidden = saved;
    $('savedBtn').setAttribute('aria-pressed', saved ? 'true' : 'false');
    $('savedCount').textContent = String(savedCount());
    if (!saved) { renderRegions(); renderCats(); }
    $('sortLocal').setAttribute('aria-pressed', S.sort === 'local' ? 'true' : 'false');
    $('sortTop').setAttribute('aria-pressed', S.sort === 'top' ? 'true' : 'false');
    $('sortNear').setAttribute('aria-pressed', S.sort === 'near' ? 'true' : 'false');
    S.list = computeList();
    S.shown = 0;
    S.gen++;
    $('feed').textContent = '';
    var st = $('status');
    if (!S.list.length) {
      st.textContent = saved
        ? (savedCount() ? 'No saved spots match your search.' : 'Nothing saved yet. Open a spot and tap Save.')
        : (S.data ? 'No spots match these filters.' : st.textContent);
    } else {
      st.textContent = '';
    }
    renderMore();
    window.scrollTo(0, 0);
  }

  function renderMore() {
    var feed = $('feed');
    var end = Math.min(S.list.length, S.shown + PAGE);
    var frag = document.createDocumentFragment();
    for (var i = S.shown; i < end; i++) frag.appendChild(buildCard(S.list[i]));
    feed.appendChild(frag);
    S.shown = end;
    watchSentinel();
  }

  function watchSentinel() {
    var sent = $('sentinel');
    if (S.shown >= S.list.length) {
      if (io) io.disconnect();
      return;
    }
    if (!('IntersectionObserver' in window)) {
      // no observer: fall back to a scroll check
      return;
    }
    if (!io) {
      io = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) {
          if (S.shown < S.list.length) renderMore();
        }
      }, { rootMargin: '600px 0px' });
    }
    io.disconnect();
    io.observe(sent);
  }
  window.addEventListener('scroll', debounce(function () {
    if ('IntersectionObserver' in window) return;
    var doc = document.documentElement;
    if (S.shown < S.list.length && window.innerHeight + window.scrollY > doc.scrollHeight - 800) renderMore();
  }, 100), { passive: true });

  /* ---------- card ---------- */
  function buildMedia(spot) {
    var wrap = el('div', 'media cat-' + spot.cat);
    var src = safeImg(spot.img);
    function placeholder() {
      wrap.className = 'media ph cat-' + spot.cat;
      wrap.textContent = catLabel(spot.cat);
    }
    if (src) {
      var img = document.createElement('img');
      img.loading = 'lazy';
      img.decoding = 'async';
      img.alt = '';
      img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', function () { wrap.textContent = ''; placeholder(); });
      img.src = src;
      wrap.appendChild(img);
    } else {
      placeholder();
    }
    return wrap;
  }

  function buildCard(item) {
    var spot = item.spot;
    var card = el('article', 'card cat-' + spot.cat);
    var hit = el('button', 'card-hit');
    hit.type = 'button';
    hit.setAttribute('aria-expanded', 'false');

    var media = buildMedia(spot);
    if (typeof item.km === 'number') media.appendChild(el('span', 'dist', fmtKm(item.km)));
    hit.appendChild(media);

    var body = el('div', 'body');
    body.appendChild(el('span', 'catlabel', catLabel(spot.cat)));
    body.appendChild(el('h3', 'name', spot.name));
    if (spot.local) body.appendChild(el('p', 'local', spot.local));
    var meta = [spot.dest, item.rn].filter(function (x, i, a) { return x && a.indexOf(x) === i; }).join(' · ');
    if (meta) body.appendChild(el('p', 'meta', meta));
    if (spot.desc) body.appendChild(el('p', 'desc', spot.desc));
    var more = el('div', 'more', 'Details');
    body.appendChild(more);
    hit.appendChild(body);
    card.appendChild(hit);

    var detail = null;
    hit.addEventListener('click', function () {
      var open = hit.getAttribute('aria-expanded') !== 'true';
      hit.setAttribute('aria-expanded', open ? 'true' : 'false');
      card.classList.toggle('open', open);
      more.textContent = open ? 'Hide' : 'Details';
      if (open && !detail) {
        detail = el('div', 'detail');
        card.appendChild(detail);
        fillDetail(detail, item);
      }
      if (detail) detail.hidden = !open;
    });
    return card;
  }

  function fact(dl, label, value) {
    if (!value) return;
    dl.appendChild(el('dt', '', label));
    dl.appendChild(el('dd', '', value));
  }

  function fmtInt(n) { return Number(n).toLocaleString('en'); }

  // Measurements only, in plain words; never a verdict like "locals love this" (docs/contract.md).
  function evidenceLines(spot, cc) {
    var sig = (spot.signals && typeof spot.signals === 'object') ? spot.signals : {};
    var data = S.cache[cc];
    var lang = (data && data.lookup_lang) || 'the local language';
    var lines = [];
    if (sig.local_only && typeof sig.local_views === 'number') {
      lines.push('Only on ' + lang + ' Wikipedia, no English article (' + fmtInt(sig.local_views) + ' ' + lang + ' lookups in the past year)');
    } else if (typeof sig.local_share === 'number') {
      lines.push(Math.round(sig.local_share * 100) + '% of Wikipedia lookups are in ' + lang +
        ' (' + fmtInt(sig.local_views || 0) + ' in the past year)');
    } else if (typeof sig.local_views === 'number') {
      lines.push('Too few Wikipedia lookups to compare languages');
    }
    if (typeof sig.osm_local === 'number') {
      var asOf = data && data.signals_as_of && data.signals_as_of.osm;
      var when = asOf ? ' (as of ' + fmtDate(asOf) + ')' : '';
      var named = (data && data.lookup_lang) || 'the local language';
      if (sig.osm_chain) {
        lines.push('Part of a chain brand on OpenStreetMap' + when);
      } else if (sig.osm_local === 1) {
        lines.push('Named in ' + named + ' on OpenStreetMap' + when);
      } else {
        lines.push('No ' + named + ' name on OpenStreetMap' + when);
      }
    }
    if (typeof sig.sitelinks === 'number' && sig.sitelinks > 0) {
      lines.push('Covered by ' + sig.sitelinks + ' Wikimedia site' + (sig.sitelinks === 1 ? '' : 's'));
    }
    if (spot.listed_by === 'wikivoyage') lines.push('Listed by Wikivoyage travellers');
    return lines;
  }

  function hasLocality(spot) {
    var sig = (spot.signals && typeof spot.signals === 'object') ? spot.signals : {};
    return ['local_share', 'mentions', 'osm_local'].some(function (k) { return typeof sig[k] === 'number'; });
  }

  function buildEvidence(item) {
    var spot = item.spot;
    var box = el('div', 'evidence');
    box.appendChild(el('h4', 'ev-head', 'Why it ranks here'));
    var data = S.cache[item.cc];
    if (typeof spot.ulu === 'number') {
      box.appendChild(el('p', 'ev-score', 'Ulu score ' + spot.ulu + ' of 100, against other ' +
        catLabel(spot.cat) + ' in ' + ((data && data.name) || 'this country')));
    } else if (hasLocality(spot)) {
      // the build nulls a score when too few comparable spots have evidence (MIN_POOL in ulu/score.py)
      box.appendChild(el('p', 'ev-score', 'Too few ' + catLabel(spot.cat) + ' in ' +
        ((data && data.name) || 'this country') + ' have local evidence to rank this one fairly, so no Ulu score yet.'));
    } else {
      box.appendChild(el('p', 'ev-score', 'No local evidence for this spot yet, so it has no Ulu score.'));
    }
    var lines = evidenceLines(spot, item.cc);
    if (lines.length) {
      var ul = el('ul', 'ev-list');
      lines.forEach(function (t) { ul.appendChild(el('li', '', t)); });
      box.appendChild(ul);
    }
    return box;
  }

  function fillDetail(box, item) {
    var spot = item.spot;
    var dl = el('dl', 'facts');
    fact(dl, 'Hours', spot.hours);
    fact(dl, 'Price', spot.price);
    fact(dl, 'Address', spot.addr);
    if (dl.childNodes.length) box.appendChild(dl);

    box.appendChild(buildEvidence(item));

    var links = el('div', 'links');
    box.appendChild(links);
    fillLinks(links, item);

    var actions = el('div', 'actions');
    var srcUrl = safeHttp(spot.src);
    if (srcUrl) {
      var a = el('a', 'srcl', 'Source: Wikivoyage');
      a.href = srcUrl;
      a.target = '_blank';
      a.rel = 'noopener';
      actions.appendChild(a);
    } else {
      actions.appendChild(el('span'));
    }
    var key = savedKey(item.cc, spot.id);
    var save = el('button', 'save');
    save.type = 'button';
    function paintSave() {
      var on = !!S.saved[key];
      save.setAttribute('aria-pressed', on ? 'true' : 'false');
      save.textContent = on ? 'Saved' : 'Save';
    }
    paintSave();
    save.addEventListener('click', function () {
      if (S.saved[key]) delete S.saved[key];
      else S.saved[key] = { cc: item.cc, spot: spot, rn: item.rn || '' };
      write(K_SAVED, S.saved);
      paintSave();
      $('savedCount').textContent = String(savedCount());
    });
    actions.appendChild(save);
    box.appendChild(actions);
  }

  function fillLinks(box, item) {
    ensureCountry(item.cc).then(function (data) {
      var regs = {};
      (data.regions || []).forEach(function (r) { regs[r.id] = r; });
      var built = platformLinks(item.spot, data, regs);
      if (!built.length) { box.appendChild(el('p', 'meta', 'No local platform links for this spot.')); return; }
      built.forEach(function (p, i) {
        var a = el('a', 'plat' + (i === 0 ? ' primary' : ''), p.name);
        a.href = p.href;
        // an app link in a new window leaves a blank tab behind (or nothing, in a standalone PWA)
        if (!p.app) { a.target = '_blank'; a.rel = 'noopener'; }
        if (p.app) a.appendChild(el('small', '', 'app'));
        else if (p.verified === 'login') a.appendChild(el('small', '', 'sign-in'));
        box.appendChild(a);
      });
    }).catch(function () {
      box.appendChild(el('p', 'meta', 'Platform links need this country to be loaded once online.'));
    });
  }

  // Contract: "Building a platform link"
  function platformLinks(spot, data, regs) {
    var plats = data.platforms || {};
    var list = DINE_CATS.indexOf(spot.cat) >= 0 ? plats.dine : plats.any;
    var out = [];
    (list || []).forEach(function (p) {
      if (!p || typeof p.url !== 'string') return;
      var query = (p.query === 'local' && spot.local) ? spot.local : spot.name;
      var url = (IS_PHONE && typeof p.mobile === 'string') ? p.mobile : p.url;
      var hasCity = url.indexOf('{city}') >= 0;
      if (p.query === 'en' && !hasCity && spot.dest) query += ' ' + spot.dest;
      if (hasCity) {
        var cities = p.cities || {};
        var names = [spot.dest].concat(Array.isArray(spot.up) ? spot.up : []);
        var city = null;
        for (var i = 0; i < names.length; i++) {
          if (names[i] && Object.prototype.hasOwnProperty.call(cities, names[i])) { city = cities[names[i]]; break; }
        }
        if (city === null || city === undefined) return;
        url = url.split('{city}').join(encodeURIComponent(String(city)));
      }
      url = url.split('{q}').join(encodeURIComponent(query));
      url = url.split('{slug}').join(encodeURIComponent(slugify(query)));
      var href = safeHttp(url);
      var app = !href && APP_LINK.test(url);
      if (app) href = url;
      if (!href) return;
      out.push({ name: p.name || p.id, href: href, verified: p.verified, app: app });
    });
    return out;
  }

  /* ---------- sheets ---------- */
  var lastFocus = null;
  function openSheet(title, build) {
    lastFocus = document.activeElement;
    $('sheetTitle').textContent = title;
    var body = $('sheetBody');
    body.textContent = '';
    build(body);
    $('sheet').hidden = false;
    $('sheetClose').focus();
  }
  function closeSheet() {
    $('sheet').hidden = true;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $('sheetClose').addEventListener('click', closeSheet);
  $('sheetBackdrop').addEventListener('click', closeSheet);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !$('sheet').hidden) closeSheet();
  });

  function openCountrySheet() {
    openSheet('Choose a country', function (body) {
      ((S.index && S.index.countries) || []).forEach(function (c) {
        var b = el('button', 'crow');
        b.type = 'button';
        b.appendChild(el('span', 'fl', c.flag || ''));
        b.appendChild(el('span', 'cn', c.name));
        if (!c.enabled) {
          b.disabled = true;
          b.appendChild(el('span', 'cm', 'coming soon'));
        } else {
          b.appendChild(el('span', 'cm', c.count + ' spots'));
          if (c.cc === S.cc) b.setAttribute('aria-current', 'true');
          b.addEventListener('click', function () {
            closeSheet();
            S.view = 'feed';
            loadCountry(c.cc);
          });
        }
        body.appendChild(b);
      });
    });
  }

  function openSourcesSheet() {
    if (!S.data) return;
    openSheet('Local sources: ' + S.data.name, function (body) {
      if (S.data.why) body.appendChild(el('p', '', S.data.why));
      var plats = S.data.platforms || {};
      [['Food, markets and cafes', plats.dine], ['Everything else', plats.any]].forEach(function (g) {
        if (!g[1] || !g[1].length) return;
        body.appendChild(el('h3', '', g[0]));
        var ul = el('ul');
        g[1].forEach(function (p) {
          var t = p.name + (p.verified === 'login' ? ' (sign-in needed)' : '');
          ul.appendChild(el('li', '', t));
        });
        body.appendChild(ul);
      });
    });
  }

  /* ---------- sort / nearby ---------- */
  function showNote(msg) {
    var n = $('note');
    if (!msg) { n.hidden = true; n.textContent = ''; return; }
    n.textContent = msg;
    n.hidden = false;
  }
  function setSortLocal() { S.sort = 'local'; showNote(''); refresh(); }
  function setSortTop() { S.sort = 'top'; showNote(''); refresh(); }
  function setSortNear() {
    showNote('');
    if (S.pos) { S.sort = 'near'; refresh(); return; }
    if (!navigator.geolocation) { showNote('Location is not available on this device.'); return; }
    showNote('Finding your location...');
    navigator.geolocation.getCurrentPosition(function (p) {
      S.pos = { lat: p.coords.latitude, lon: p.coords.longitude };
      S.sort = 'near';
      showNote('');
      refresh();
    }, function (err) {
      S.sort = 'local';
      showNote(err && err.code === 1
        ? 'Location permission was denied, so Nearby is off. Allow location for this site to use it.'
        : 'Could not get your location. Showing Most local instead.');
      refresh();
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  }

  /* ---------- country load ---------- */
  function loadCountry(cc) {
    var c = null;
    (S.index.countries || []).forEach(function (x) { if (x.cc === cc) c = x; });
    if (!c) return;
    S.cc = cc;
    writeStr(K_COUNTRY, cc);
    $('countryFlag').textContent = c.flag || '';
    $('countryName').textContent = c.name;
    S.r1 = ''; S.r2 = ''; S.cat = '';
    S.data = null;
    $('feed').textContent = '';
    $('status').textContent = 'Loading ' + c.name + '...';
    var mine = cc;
    ensureCountry(cc).then(function (d) {
      if (S.cc !== mine) return;
      S.data = d;
      regionById = {};
      (d.regions || []).forEach(function (r) { regionById[r.id] = r; });
      $('status').textContent = '';
      refresh();
    }).catch(function () {
      if (S.cc !== mine) return;
      $('status').textContent = 'Could not load ' + c.name + '. Open it once while online and it will work offline after that.';
      renderRegions(); renderCats();
    });
  }

  /* ---------- boot ---------- */
  function renderFooter() {
    var idx = S.index;
    var att = idx.attribution || {};
    var p = $('attrib');
    p.textContent = '';
    p.appendChild(document.createTextNode((att.text || 'Listings from Wikivoyage') + ' '));
    var u = safeHttp(att.url);
    if (u) {
      var a = el('a', '', u.replace(/^https?:\/\//i, '').replace(/\/$/, ''));
      a.href = u; a.target = '_blank'; a.rel = 'noopener';
      p.appendChild(a);
    }
    // ODbL 4.3 notice: shown whenever the build says some country carries OpenStreetMap signals
    var o = att.osm;
    if (o && o.text) {
      p.appendChild(document.createTextNode('. ' + o.text + ': '));
      [[safeHttp(o.url), 'openstreetmap.org/copyright'], [safeHttp(o.licence_url), 'ODbL']].forEach(function (pair, i) {
        if (!pair[0]) return;
        if (i) p.appendChild(document.createTextNode(', '));
        var l = el('a', '', pair[1]);
        l.href = pair[0]; l.target = '_blank'; l.rel = 'noopener';
        p.appendChild(l);
      });
    }
    $('refreshed').textContent = 'Spots data refreshed ' + fmtDate(idx.generated);
  }

  function boot() {
    $('countryBtn').addEventListener('click', openCountrySheet);
    $('srcBtn').addEventListener('click', openSourcesSheet);
    $('sortLocal').addEventListener('click', setSortLocal);
    $('sortTop').addEventListener('click', setSortTop);
    $('sortNear').addEventListener('click', setSortNear);
    $('savedBtn').addEventListener('click', function () {
      S.view = S.view === 'saved' ? 'feed' : 'saved';
      refresh();
    });
    $('search').addEventListener('input', debounce(function () {
      S.q = $('search').value;
      refresh();
    }, 200));
    $('savedCount').textContent = String(savedCount());

    fetchJson('data/index.json').then(function (idx) {
      S.index = idx;
      S.cats = idx.categories || [];
      renderFooter();
      var countries = idx.countries || [];
      var enabled = countries.filter(function (c) { return c.enabled; });
      if (!enabled.length) { $('status').textContent = 'No countries are available yet.'; return; }
      var want = readStr(K_COUNTRY);
      var pick = enabled.filter(function (c) { return c.cc === want; })[0] || enabled[0];
      loadCountry(pick.cc);
    }).catch(function () {
      $('status').textContent = 'Could not load Ulu data. Check your connection and reopen the app.';
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () { /* unreliable in some contexts */ });
    });
  }

  boot();
})();
