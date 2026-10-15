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
    dest: '',
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
      if (S.dest && s.dest !== S.dest) return false;
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

  function whereLabel() {
    var d = S.data;
    if (!d) return 'Everywhere';
    if (S.dest) return S.dest;
    var r = regionById[S.r2] || regionById[S.r1];
    return r ? r.name : 'All ' + d.name;
  }
  function renderWhere() {
    $('whereVal').textContent = whereLabel();
    $('whereBtn').disabled = !S.data;
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

  // Every place a user can narrow to: regions (both levels) plus destination names that are not
  // already a region name. Built once per country file.
  var whereCache = {};
  function whereOptions() {
    var d = S.data;
    if (whereCache[S.cc]) return whereCache[S.cc];
    var opts = [], seen = {};
    (d.regions || []).forEach(function (r) {
      var p = r.level === 2 ? regionById[r.parent] : null;
      opts.push({ name: r.name, sub: p ? p.name : 'Region', n: r.count || 0,
        r1: r.level === 2 ? r.parent : r.id, r2: r.level === 2 ? r.id : '', dest: '' });
      seen[norm(r.name)] = true;
    });
    var dests = {};
    (d.spots || []).forEach(function (s) {
      if (!s.dest || seen[norm(s.dest)]) return;
      var e = dests[s.dest] || (dests[s.dest] = { n: 0, r: regionName(s) });
      e.n++;
    });
    Object.keys(dests).forEach(function (k) {
      opts.push({ name: k, sub: dests[k].r || 'Place', n: dests[k].n, r1: '', r2: '', dest: k });
    });
    whereCache[S.cc] = opts;
    return opts;
  }

  function openWhereSheet() {
    if (!S.data) return;
    openSheet('Where in ' + S.data.name + '?', function (body) {
      var box = el('input', 'where-q');
      box.type = 'search';
      box.placeholder = 'Type a city or region';
      box.setAttribute('aria-label', 'Filter places');
      box.autocomplete = 'off';
      var list = el('div', 'where-list');
      body.appendChild(box);
      body.appendChild(list);
      function pick(o) {
        closeSheet();
        S.r1 = o ? o.r1 : ''; S.r2 = o ? o.r2 : ''; S.dest = o ? o.dest : '';
        refresh();
      }
      function row(label, sub, n, cur, o) {
        var b = el('button', 'crow');
        b.type = 'button';
        var cn = el('span', 'cn', label);
        if (sub) cn.appendChild(el('small', 'cs', sub));
        b.appendChild(cn);
        if (n !== null) b.appendChild(el('span', 'cm', n + ' spots'));
        if (cur) b.setAttribute('aria-current', 'true');
        b.addEventListener('click', function () { pick(o); });
        return b;
      }
      function paint() {
        var q = norm(box.value.trim());
        list.textContent = '';
        var all = !S.r1 && !S.r2 && !S.dest;
        if (!q) list.appendChild(row('All ' + S.data.name, '', (S.data.spots || []).length, all, null));
        var opts = whereOptions().filter(function (o) { return !q || norm(o.name).indexOf(q) >= 0; });
        if (!q) opts = opts.filter(function (o) { return !o.dest; });
        opts.sort(function (a, b) {
          var as = q && norm(a.name).indexOf(q) === 0 ? 0 : 1, bs = q && norm(b.name).indexOf(q) === 0 ? 0 : 1;
          return as - bs || b.n - a.n;
        });
        opts.slice(0, 50).forEach(function (o) {
          var cur = o.dest ? S.dest === o.dest : (o.r2 ? S.r2 === o.r2 : (!S.r2 && !S.dest && S.r1 === o.r1));
          list.appendChild(row(o.name, o.sub, o.n, cur, o));
        });
        if (q && !opts.length) list.appendChild(el('p', 'meta', 'No place matches "' + box.value.trim() + '".'));
      }
      box.addEventListener('input', paint);
      paint();
    });
  }

  /* ---------- feed ---------- */
  function refresh() {
    var saved = S.view === 'saved';
    $('filters').hidden = saved;
    $('toolbar').hidden = saved;
    $('savedBtn').setAttribute('aria-pressed', saved ? 'true' : 'false');
    $('savedCount').textContent = String(savedCount());
    if (!saved) { renderWhere(); renderCats(); }
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
  // A photo card keeps a capped photo; everything else is a compact row with no media block.
  function buildMedia(spot, card, item) {
    var src = safeImg(spot.img);
    if (!src) return null;
    var wrap = el('div', 'media');
    var img = document.createElement('img');
    img.loading = 'lazy';
    img.decoding = 'async';
    img.alt = '';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', function () {
      wrap.remove();
      card.classList.add('compact');
      kmInMeta(card.querySelector('.meta'), item);
    });
    img.src = src;
    wrap.appendChild(img);
    return wrap;
  }
  function kmInMeta(meta, item) {
    if (!meta || typeof item.km !== 'number' || meta.querySelector('.dist')) return;
    meta.appendChild(el('span', 'dist', fmtKm(item.km)));
  }

  function linkEl(p, cls) {
    var a = el('a', cls, p.name);
    a.href = p.href;
    // an app link in a new window leaves a blank tab behind (or nothing, in a standalone PWA)
    if (!p.app) { a.target = '_blank'; a.rel = 'noopener'; }
    return a;
  }

  function buildCard(item) {
    var spot = item.spot;
    var card = el('article', 'card cat-' + spot.cat);
    var hit = el('button', 'card-hit');
    hit.type = 'button';
    hit.setAttribute('aria-expanded', 'false');

    var media = buildMedia(spot, card, item);
    if (media) {
      if (typeof item.km === 'number') media.appendChild(el('span', 'photo-dist', fmtKm(item.km)));
      hit.appendChild(media);
    } else {
      card.classList.add('compact');
    }

    var body = el('div', 'body');
    var top = el('div', 'topline');
    top.appendChild(el('span', 'catlabel', catLabel(spot.cat)));
    var areaText = [spot.dest, item.rn].filter(function (x, i, a) { return x && a.indexOf(x) === i; }).join(' \u00b7 ');
    var meta = el('span', 'meta', areaText);
    top.appendChild(meta);
    if (!media) kmInMeta(meta, item);
    top.appendChild(el('span', 'more', 'Details'));
    body.appendChild(top);
    body.appendChild(el('h3', 'name', spot.name));
    if (spot.local) body.appendChild(el('p', 'local', spot.local));
    if (spot.desc) body.appendChild(el('p', 'desc', spot.desc));
    hit.appendChild(body);
    card.appendChild(hit);

    // One tap to the local platform, no need to open Details first (the core action).
    var data = S.cache[item.cc];
    if (data) {
      var first = platformLinks(spot, data, {})[0];
      if (first) card.appendChild(linkEl(first, 'qlink'));
    }

    var more = top.querySelector('.more');
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
        var a = linkEl(p, 'plat' + (i === 0 ? ' primary' : ''));
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

  function openCountrySheet(first) {
    openSheet(first === true ? 'Where are you going?' : 'Choose a country', function (body) {
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
    S.r1 = ''; S.r2 = ''; S.dest = ''; S.cat = '';
    S.data = null;
    renderWhere();
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
      renderWhere(); renderCats();
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
    $('countryBtn').addEventListener('click', function () { openCountrySheet(); });
    $('whereBtn').addEventListener('click', openWhereSheet);
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
      var pick = enabled.filter(function (c) { return c.cc === want; })[0];
      if (pick) { loadCountry(pick.cc); return; }
      // First open (or a stored country that no longer exists): ask, never assume.
      $('countryName').textContent = 'Choose';
      $('status').textContent = 'Pick a country to start.';
      openCountrySheet(true);
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
