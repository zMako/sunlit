// Move-in map front door: SF rental listings on a map + card feed -> detail drawer -> 3D / walk / furnish / checkout.
// Data: /api/listings (app/map/listings.json, built by listings_index.py). Tiles: /tiles/{z}/{x}/{y}.png (OSM, cached by proxy.py).
'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt$ = n => '$' + Math.round(n).toLocaleString('en-US');
const fmtN = n => Math.round(n).toLocaleString('en-US');
const movein = new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10);
const P = new URLSearchParams(location.search);
let ALL = [], SHOWN = [], MARK = new Map(), BYID = new Map(), CMP = [], map;

// ---------- formatting ----------
const bedTxt = (a, b) => a == null ? null : (a === b || b == null ? (a === 0 ? 'studio' : `${a} bd`) : `${a === 0 ? 'studio' : a}–${b} bd`);
const bathTxt = (a, b) => a == null ? null : (a === b || b == null ? `${a} ba` : `${a}–${b} ba`);
const sqftTxt = l => l.sqft_min == null ? null : (l.sqft_min === l.sqft_max ? `${fmtN(l.sqft_min)} sqft` : `${fmtN(l.sqft_min)}–${fmtN(l.sqft_max)} sqft`) + (l.sqft_from === '3D model' ? ' (from plan)' : '');
const priceHtml = l => l.price ? `<span class="price" title="${esc(l.price_note || '')}">${l.price_note && l.price_note.startsWith('from') ? '<span class="meta">from </span>' : ''}${fmt$(l.price)}<span class="meta">/mo</span></span>` : `<span class="price req">pricing on request</span>`;
function badges(l) {
  const b = [];
  if (l.can_rebuild) b.push(['ok', `3D ready · ${l.units.length} unit type${l.units.length > 1 ? 's' : ''}`]);
  if (l.has_plan) b.push(['acc', `floor plan${l.plans.length > 1 ? 's' : ''} · ${l.plans.length}`]);
  if (l.n_photos) b.push(['', `photos · ${l.n_photos}`]);
  const SRC = { greystar: 'Greystar', rentsfnow: 'RentSFNow', udr: 'UDR', avalonbay: 'AvalonBay' }; if (SRC[l.source]) b.push(['', SRC[l.source]]);
  return b.map(([c, t]) => `<span class="bd ${c}">${esc(t)}</span>`).join('');
}
function unitLinks(u) {
  const a = `../plan3d/apartment.html?unit=${encodeURIComponent(u.unit)}`;
  return { open: a, walk: `${a}&view=walk`, furnish: `${a}&agent=${u.agent_room}&budget=3500&style=warm%20scandinavian&drama=1` };
}
const checkoutLink = rooms => rooms && rooms.length ? `../checkout/checkout.html?rooms=${rooms.join(',')}&budget=3500&movein=${movein}` : '';
const unitBeds = u => u.beds ?? (u.rooms.filter(r => r.type === 'bedroom').length || null);

// ---------- filters ----------
function matches(l) {
  const q = $('q').value.trim().toLowerCase(), pmin = +$('pmin').value || 0, pmax = +$('pmax').value || 0, beds = $('beds').value;
  if (!l.in_sf || l.lat == null) return false;
  if ($('fplan').checked && !l.has_plan) return false;
  if ($('f3d').checked && !l.can_rebuild) return false;
  if ((pmin || pmax) && !l.price) return false;
  if (pmin && l.price < pmin) return false;
  if (pmax && l.price > pmax) return false;
  if (beds !== '') { const want = +beds, lo = l.beds_min, hi = l.beds_max ?? lo; if (lo == null) return false;
    if (want === 3 ? hi < 3 : !(lo <= want && want <= hi)) return false; }
  if (q && !l._text.includes(q)) return false;
  return true;
}
function sortKey(l) {
  const s = $('sort').value;
  if (s === 'plo') return l.price || 1e9;
  if (s === 'phi') return -(l.price || 0);
  if (s === 'size') return -(l.sqft_max || 0);
  return -((l.can_rebuild ? 1e6 : 0) + (l.has_plan ? 1e5 : 0) + Math.min(l.units.length, 60) * 1000 + Math.min(l.n_photos, 20) * 10) + (l.price || 0) / 1e5;
}

// ---------- map ----------
function pinStyle(l, hot) {
  const c = l.can_rebuild ? '#7fe0b4' : '#6ea8fe';
  return { radius: hot ? 11 : (l.can_rebuild ? 8 : 6.5), color: hot ? '#ffffff' : '#0b0f16', weight: hot ? 3 : 2, fillColor: c, fillOpacity: hot ? 1 : .9 };
}
function initMap() {
  map = L.map('map', { zoomControl: true, minZoom: 11, maxZoom: 18, preferCanvas: false }).setView([37.776, -122.43], 13);
  L.tileLayer('/tiles/{z}/{x}/{y}.png', { maxZoom: 18, maxNativeZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors' }).addTo(map);
  map.setMaxBounds([[37.60, -122.70], [37.92, -122.20]]);
  map.on('moveend', () => { if ($('fbounds').checked) renderFeed(); });
}
function drawPins() {
  for (const l of ALL) {
    if (!l.in_sf || l.lat == null) continue;
    const m = L.circleMarker([l.lat, l.lon], pinStyle(l, false)).addTo(map);
    m.bindTooltip(`<b>${esc(l.building || l.title.split(':')[0])}</b><br>${esc(l.price ? fmt$(l.price) + '/mo' : 'pricing on request')}${l.can_rebuild ? ' · 3D ready' : ''}`, { className: 'tip', direction: 'top', offset: [0, -8] });
    m.on('mouseover', () => hot(l.id, true, 'map')); m.on('mouseout', () => hot(l.id, false, 'map'));
    m.on('click', () => openDrawer(l.id));
    MARK.set(l.id, m);
  }
}
function hot(id, on, from) {
  const l = BYID.get(id), m = MARK.get(id); if (!l) return;
  if (m) { m.setStyle(pinStyle(l, on || id === SEL)); if (on) m.bringToFront(); if (from === 'card') on ? m.openTooltip() : m.closeTooltip(); }
  const c = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  if (c) { c.classList.toggle('hl', on); if (on && from === 'map') c.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
}
function applyVisibility() {
  const ok = new Set(ALL.filter(matches).map(l => l.id));
  for (const [id, m] of MARK) { const vis = ok.has(id); if (vis && !map.hasLayer(m)) m.addTo(map); else if (!vis && map.hasLayer(m)) m.remove(); }
  return ok;
}

// ---------- feed ----------
function stripHtml(l) {
  const ph = l.photos.slice(0, 3).map(p => `<img src="${esc(p)}" loading="lazy" alt="">`);
  const pl = l.plans.slice(0, l.photos.length ? 1 : 3).map(p => `<img class="plan" src="${esc(p.src)}" loading="lazy" alt="plan">`);
  const all = [...ph, ...pl].slice(0, 4);
  return `<div class="strip">${all.join('') || '<div class="none">no photos published</div>'}</div>`;
}
function cardHtml(l) {
  const name = l.building || l.title.split(':')[0];
  const sub = l.source === 'rentsfnow' ? (l.title.split(':').slice(1).join(':').trim()) : `${l.units.length ? l.units.length + ' unit types rebuilt in 3D' : (l.plans.length ? l.plans.length + ' floor plans' : 'building gallery')}`;
  const facts = [bedTxt(l.beds_min, l.beds_max), bathTxt(l.baths_min, l.baths_max), sqftTxt(l)].filter(Boolean).map(t => `<span>${esc(t)}</span>`).join('');
  return `<div class="card" data-id="${esc(l.id)}">${stripHtml(l)}<div class="cbody">
    <div class="crow"><div class="ctitle" title="${esc(l.title)}">${esc(name)}</div>${priceHtml(l)}</div>
    <div class="meta">${esc(l.address.replace(/, San Francisco.*$/, ''))}${l.neighborhood ? ' · ' + esc(l.neighborhood) : ''}${sub ? ' · ' + esc(sub) : ''}</div>
    <div class="facts">${facts || '<span class="meta">size not published</span>'}</div><div class="badges">${badges(l)}</div></div></div>`;
}
function renderFeed() {
  const ok = applyVisibility(); const b = map.getBounds();
  let list = ALL.filter(l => ok.has(l.id)); const total = list.length;
  if ($('fbounds').checked) list = list.filter(l => b.contains([l.lat, l.lon]));
  list.sort((a, b) => sortKey(a) - sortKey(b)); SHOWN = list;
  const n3d = list.filter(l => l.can_rebuild).length, nu = list.reduce((s, l) => s + l.units.length, 0);
  $('count').textContent = `${list.length} listing${list.length === 1 ? '' : 's'}`;
  $('count2').textContent = `${$('fbounds').checked && list.length < total ? `in view (of ${total})` : ''} · ${n3d} with 3D, ${nu} unit types`;
  $('feed').innerHTML = list.map(cardHtml).join('') || '<div class="empty">No listing matches. Zoom out, or clear a filter.</div>';
}
$('feed').addEventListener('mouseover', e => { const c = e.target.closest('.card'); if (c && !c.contains(e.relatedTarget)) hot(c.dataset.id, true, 'card'); });
$('feed').addEventListener('mouseout', e => { const c = e.target.closest('.card'); if (c && !c.contains(e.relatedTarget)) hot(c.dataset.id, false, 'card'); });
$('feed').addEventListener('click', e => { const c = e.target.closest('.card'); if (c) openDrawer(c.dataset.id); });
for (const id of ['q', 'pmin', 'pmax', 'beds', 'fplan', 'f3d', 'fbounds', 'sort']) $(id).addEventListener('input', renderFeed);

// ---------- drawer ----------
let CUR = null, SEL = null;
function unitRow(l, u) {
  const L = unitLinks(u), co = checkoutLink(u.furnished_rooms), bd = unitBeds(u);
  const rooms = u.rooms.filter(r => r.area_m2 > 2).sort((a, b) => b.area_m2 - a.area_m2).slice(0, 7).map(r => `${esc(r.name)} ${r.area_m2} m²`).join(' · ');
  const sz = u.size_typical && !u.sqft_listed ? `typical size ≈${u.area_m2} m²` : [u.area_m2 ? `${u.area_m2} m²` : null, u.sqft_listed ? `${fmtN(u.sqft_listed)} sqft listed` : (u.sqft_model ? `≈${fmtN(u.sqft_model)} sqft` : null)].filter(Boolean).join(' · ');
  const inCmp = CMP.some(c => c.key === u.unit);
  return `<div class="unit" id="u-${esc(u.unit)}"><img src="${esc(u.plan_image)}" loading="lazy" alt="plan" data-zoom="${esc(u.plan_image)}"><div class="ub">
    <div class="crow"><div class="ctitle">${esc(u.plan_name || u.unit)}</div><span class="meta">${esc(u.unit)}</span></div>
    <div class="facts">${[bd != null ? (bd === 0 ? 'studio' : bd + ' bd') : null, u.baths != null ? u.baths + ' ba' : null, sz, u.n_rooms + ' rooms'].filter(Boolean).map(t => `<span>${esc(t)}</span>`).join('')}</div>
    <div class="badges"><span class="bd ok">3D ready</span>${u.size_source ? `<span class="bd ${u.size_typical ? 'warn' : u.size_source.startsWith('plan dim') ? 'ok' : (u.size_source.startsWith('Claude') ? 'acc' : '')}">size: ${esc(u.size_source)}</span>` : ''}${u.annotated ? '<span class="bd acc">annotated · rooms named by Claude</span>' : ''}${u.materials ? '<span class="bd acc">materials from photos</span>' : ''}${u.n_fixtures ? `<span class="bd">${u.n_fixtures} fixtures</span>` : ''}</div>
    <div class="rooms">${rooms}</div>
    <div class="row"><a class="btn" href="${L.open}" target="_blank">Open 3D</a><a class="btn sec" href="${L.walk}" target="_blank">Walk</a><a class="btn sec" href="${L.furnish}" target="_blank">Furnish</a>
      <a class="btn go ${co ? '' : 'off'}" data-co="${esc(u.unit)}" href="${co || '#'}" target="_blank" title="${co ? u.furnished_rooms.length + ' furnished room(s)' : 'furnish a room first'}">Checkout</a>
      <button class="btn ${inCmp ? 'on' : 'ghost'}" data-cmp="${esc(u.unit)}">${inCmp ? '✓ comparing' : '+ compare'}</button>${annBtn(u)}</div></div></div>`;
}
// ---------- on-demand annotation (POST /api/annotate -> plan3d/annotate_on_demand.py, spend through the ledger) ----------
const ANN = {};
function annBtn(u) { if (u.annotated) return '';
  const st = ANN[u.unit];
  if (st === 'running') return `<button class="btn ann" data-ann="${esc(u.unit)}" disabled><span class="spin"></span>Claude is reading the plan…</button>`;
  if (st) return `<button class="btn ann err" data-ann="${esc(u.unit)}" title="${esc(st)}">${esc(st)}</button>`;
  return `<button class="btn ann" data-ann="${esc(u.unit)}" title="Claude names the rooms and places kitchen/bath fixtures (~5 cents, within the spend cap)">Name rooms &amp; fixtures with Claude</button>`; }
function redrawUnit(l, u) { const el = document.getElementById('u-' + u.unit); if (el && CUR === l) el.outerHTML = unitRow(l, u); }
async function annotateUnit(unit) {
  const l = CUR, u = l && l.units.find(x => x.unit === unit); if (!u || ANN[unit] === 'running') return;
  ANN[unit] = 'running'; redrawUnit(l, u);
  let res; try { res = await (await fetch(`/api/annotate?unit=${encodeURIComponent(unit)}`, { method: 'POST' })).json(); } catch (e) { res = { error: 'server unreachable' }; }
  if (res.ok) { delete ANN[unit];
    try { const idx = await (await fetch('../plan3d/layouts/index.json', { cache: 'no-store' })).json(); const n = idx.find(x => x.unit === unit);
      if (n) { u.rooms = n.rooms.map(r => ({ id: r.id, name: r.name, type: r.type, area_m2: r.area_m2 })); u.n_fixtures = n.n_fixtures; u.area_m2 = n.area_m2; u.n_rooms = n.rooms.filter(r => r.area_m2 > 2).length;
        const liv = u.rooms.find(r => r.type === 'living'); if (liv) u.agent_room = liv.id; } } catch (e) {}
    u.annotated = true; }
  else ANN[unit] = res.error === 'budget cap reached' ? 'Claude budget cap reached' : res.error === 'busy' ? 'busy: another unit is being annotated, retry' : (res.error || 'failed');
  redrawUnit(l, u); }
function openDrawer(id, focusUnit) {
  const l = BYID.get(id); if (!l) return; CUR = l;
  if (SEL && SEL !== id) { const o = BYID.get(SEL), om = MARK.get(SEL); if (o && om) om.setStyle(pinStyle(o, false)); }
  SEL = id; const mk = MARK.get(id);
  if (mk) { mk.setStyle(pinStyle(l, true)); mk.bringToFront();   // centre the pin in the part of the map the drawer leaves visible
    const dw = Math.min(880, innerWidth), mw = map.getSize().x, z = Math.max(map.getZoom(), 15), side = innerWidth - mw;
    const shift = Math.max(0, (dw - side) / 2); const pt = map.project([l.lat, l.lon], z).add([shift, 0]); map.setView(map.unproject(pt, z), z, { animate: true }); }
  const name = l.building || l.title.split(':')[0];
  const facts = [bedTxt(l.beds_min, l.beds_max), bathTxt(l.baths_min, l.baths_max), sqftTxt(l)].filter(Boolean).join(' · ');
  $('dhead').innerHTML = `<div><div class="meta">${esc({ greystar: 'Greystar building', udr: 'UDR building · true sizes from the landlord', avalonbay: 'AvalonBay building' }[l.source] || 'RentSFNow unit')}${l.neighborhood ? ' · ' + esc(l.neighborhood) : ''}</div><h2>${esc(l.title)}</h2>
    <div class="meta">${esc(l.address)}</div><div class="badges" style="margin-top:6px">${badges(l)}</div></div>
    <div style="text-align:right;margin-left:auto;white-space:nowrap">${priceHtml(l)}<div class="meta">${esc(facts)}</div>${l.url ? `<a class="meta" href="${esc(l.url)}" target="_blank" rel="noopener">landlord's listing ↗</a>` : ''}</div>
    <button class="x" id="dx" title="close (Esc)">×</button>`;
  const photos = l.photos;
  const gal = photos.length ? `<section><h3>Photos <span class="meta">${l.n_photos}${l.source === 'greystar' ? ' · building gallery, several units' : ''}</span></h3><div class="gal"><img class="main" id="gmain" src="${esc(photos[0])}" alt="" data-zoom="${esc(photos[0])}">
    <div class="thumbs">${photos.map((p, i) => `<img src="${esc(p)}" loading="lazy" class="${i ? '' : 'on'}" data-ph="${esc(p)}" alt="">`).join('')}</div></div></section>` : '';
  const plans = l.plans.length ? `<section><h3>Floor plans <span class="meta">${l.plans.length} published · ${l.units.length} rebuilt in 3D</span></h3><div class="plans">${l.plans.map(p =>
    `<div class="plan" data-plan="${esc(p.unit || '')}" data-zoom="${esc(p.src)}"><img src="${esc(p.src)}" loading="lazy" alt="">${p.unit ? '<span class="d3">3D</span>' : ''}<div class="cap">${esc(p.name || '')}${p.beds != null ? ' · ' + (p.beds === 0 ? 'studio' : p.beds + ' bd') : ''}${p.baths != null ? ' / ' + p.baths + ' ba' : ''}</div></div>`).join('')}</div></section>` : '';
  const desc = `<section><h3>Description</h3>${l.body ? `<div class="desc">${esc(l.body)}</div>` : `<div class="desc none">The landlord's page has no description for this building; the plans and photos above are what it publishes.</div>`}</section>`;
  const units = l.units.length ? `<section><h3>Unit types in 3D <span class="meta">open the dollhouse, walk it, let the agent furnish it, check out</span></h3><div class="units" id="ulist">${[...l.units].sort((a, b) => (b.annotated - a.annotated) || (b.materials - a.materials) || a.unit.localeCompare(b.unit)).map(u => unitRow(l, u)).join('')}</div></section>`
    : `<section><h3>3D</h3><div class="desc none">${l.has_plan ? 'Floor plans are published but none has been rebuilt yet.' : 'No floor plan is published for this listing, so it cannot be rebuilt in 3D yet. Photos and size only.'}</div>
       <div class="row" style="margin-top:8px"><button class="btn ${CMP.some(c => c.key === l.id) ? 'on' : 'ghost'}" data-cmp="${esc(l.id)}">${CMP.some(c => c.key === l.id) ? '✓ comparing' : '+ compare'}</button></div></section>`;
  $('dbody').innerHTML = gal + (l.units.length ? units + plans : plans + units) + desc;
  $('drawer').classList.add('open'); $('dbody').scrollTop = 0;
  history.replaceState(null, '', `?open=${encodeURIComponent(id)}${focusUnit ? '&unit=' + encodeURIComponent(focusUnit) : ''}`);
  if (focusUnit) setTimeout(() => flashUnit(focusUnit), 60);
  refreshCheckout(l);
}
function flashUnit(uid) { const el = document.getElementById('u-' + uid); if (!el) return; el.scrollIntoView({ block: 'center' }); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 2200); }
function closeDrawer() { $('drawer').classList.remove('open'); CUR = null; if (SEL && MARK.get(SEL)) MARK.get(SEL).setStyle(pinStyle(BYID.get(SEL), false)); SEL = null; history.replaceState(null, '', location.pathname); }
async function refreshCheckout(l) {   // live: which rooms already have a furnishing plan (same check as plan3d/index.html)
  for (const u of l.units) {
    const ok = await Promise.all(u.rooms.filter(r => r.area_m2 > 2).map(async r => { const room = `${u.unit}__${r.id}`;
      try { const res = await fetch(`/api/furnish?room=${encodeURIComponent(room)}`, { cache: 'no-store' }); return res.status === 200 ? room : null; } catch (e) { return null; } }));
    if (CUR !== l) return; u.furnished_rooms = ok.filter(Boolean);
    const a = document.querySelector(`a[data-co="${CSS.escape(u.unit)}"]`); const co = checkoutLink(u.furnished_rooms);
    if (a) { a.href = co || '#'; a.classList.toggle('off', !co); a.title = co ? `${u.furnished_rooms.length} furnished room(s)` : 'furnish a room first'; }
  }
}
$('drawer').addEventListener('click', e => {
  if (e.target.id === 'dx') return closeDrawer();
  const ph = e.target.closest('[data-ph]'); if (ph) { const m = $('gmain'); m.src = ph.dataset.ph; m.dataset.zoom = ph.dataset.ph; document.querySelectorAll('.thumbs img').forEach(i => i.classList.toggle('on', i === ph)); return; }
  const cb = e.target.closest('[data-cmp]'); if (cb) { toggleCompare(cb.dataset.cmp); return; }
  const ab = e.target.closest('[data-ann]'); if (ab) { if (!ab.disabled && !(ANN[ab.dataset.ann] || '').startsWith('Claude budget')) { delete ANN[ab.dataset.ann]; annotateUnit(ab.dataset.ann); } return; }
  const pl = e.target.closest('[data-plan]'); if (pl && pl.dataset.plan) { flashUnit(pl.dataset.plan); return; }
  const z = e.target.closest('[data-zoom]'); if (z) { $('lbimg').src = z.dataset.zoom; $('lb').classList.add('open'); }
});
$('lb').addEventListener('click', () => $('lb').classList.remove('open'));
addEventListener('keydown', e => { if (e.key === 'Escape') { if ($('lb').classList.contains('open')) $('lb').classList.remove('open'); else if ($('cmp').classList.contains('show')) $('cmp').classList.remove('show'); else closeDrawer(); } });
addEventListener('focus', () => { if (CUR) refreshCheckout(CUR); });   // back from furnishing in another tab

// ---------- compare ----------
function cmpItem(key) {
  for (const l of ALL) {
    if (l.id === key) return { key, l, u: null, name: l.title.split(':')[0], img: l.photos[0], isPlan: false, m2: l.sqft_min ? l.sqft_min / 10.7639 : null, sqft: l.sqft_min, rooms: null, beds: l.beds_min, baths: l.baths_min, price: l.price };
    const u = l.units.find(x => x.unit === key);
    if (u) return { key, l, u, name: `${l.building} · ${u.plan_name || u.unit}`, img: u.plan_image, isPlan: true, typical: u.size_typical && !u.sqft_listed, m2: u.area_m2, sqft: u.sqft_listed || u.sqft_model, rooms: u.rooms.filter(r => r.area_m2 > 2), beds: unitBeds(u), baths: u.baths, price: null };
  }
  return null;
}
function toggleCompare(key) {
  const i = CMP.findIndex(c => c.key === key);
  if (i >= 0) CMP.splice(i, 1); else { const it = cmpItem(key); if (!it) return; if (CMP.length >= 3) CMP.shift(); CMP.push(it); }
  drawTray(); if (CUR) document.querySelectorAll('[data-cmp]').forEach(b => { const on = CMP.some(c => c.key === b.dataset.cmp); b.className = `btn ${on ? 'on' : 'ghost'}`; b.textContent = on ? '✓ comparing' : '+ compare'; });
  if ($('cmp').classList.contains('show')) drawCompare();
}
function drawTray() {
  $('tray').classList.toggle('show', CMP.length > 0);
  $('tray').innerHTML = `<b style="font-size:12.5px">Compare</b>${CMP.map(c => `<div class="chip"><img src="${esc(c.img || '')}" alt=""><span title="${esc(c.name)}">${esc(c.name)}</span><button data-rm="${esc(c.key)}" title="remove">×</button></div>`).join('')}
    <span class="hint">${CMP.length}/3</span><button class="btn" id="cmpgo" ${CMP.length < 2 ? 'disabled style="opacity:.5"' : ''}>Compare side by side</button>`;
}
$('tray').addEventListener('click', e => { const r = e.target.closest('[data-rm]'); if (r) return toggleCompare(r.dataset.rm); if (e.target.id === 'cmpgo' && CMP.length) { $('cmp').classList.toggle('show'); drawCompare(); } });
function drawCompare() {
  const best = (f, dir) => { const v = CMP.map(f).filter(x => x != null); return v.length > 1 ? (dir > 0 ? Math.max(...v) : Math.min(...v)) : null; };
  const bm2 = best(c => c.m2, 1), bpr = best(c => c.price, -1), bpm = best(c => c.price && c.m2 ? c.price / c.m2 : null, -1);
  const col = c => { const ppm = c.price && c.m2 ? c.price / c.m2 : null; const L = c.u ? unitLinks(c.u) : null;
    return `<div class="col"><img class="${c.isPlan ? '' : 'photo'}" src="${esc(c.img || '')}" alt="" data-zoom="${esc(c.img || '')}"><table>
    <tr><td>listing</td><td><b>${esc(c.name)}</b><div class="meta">${esc(c.l.address)}</div></td></tr>
    <tr><td>size</td><td class="${c.m2 && c.m2 === bm2 ? 'best' : ''}">${c.typical ? 'typical ≈' : ''}${c.m2 ? `${c.m2.toFixed(1)} m²` : '–'}${c.sqft ? ` · ${fmtN(c.sqft)} sqft${c.u && !c.u.sqft_listed ? ' (from plan)' : ''}` : ''}</td></tr>
    <tr><td>beds / baths</td><td>${c.beds != null ? (c.beds === 0 ? 'studio' : c.beds + ' bd') : '–'} / ${c.baths ?? '–'} ba</td></tr>
    <tr><td>rooms</td><td>${c.rooms ? `${c.rooms.length}: <span class="meta">${c.rooms.sort((a, b) => b.area_m2 - a.area_m2).map(r => `${esc(r.name)} ${r.area_m2}`).join(' · ')}</span>` : '<span class="meta">no plan published</span>'}</td></tr>
    <tr><td>price</td><td class="${c.price && c.price === bpr ? 'best' : ''}">${c.price ? fmt$(c.price) + '/mo' : '<span class="meta">pricing on request</span>'}</td></tr>
    <tr><td>$ per m²</td><td class="${ppm && ppm === bpm ? 'best' : ''}">${ppm ? fmt$(ppm) : '–'}</td></tr>
    <tr><td>size from</td><td class="meta">${esc(c.u ? (c.u.size_source || '–') : (c.sqft ? 'listing sqft' : '–'))}</td></tr>
    <tr><td></td><td>${L ? `<a class="btn" href="${L.open}" target="_blank">Open 3D</a> <a class="btn sec" href="${L.furnish}" target="_blank">Furnish</a>` : `<button class="btn sec" data-open="${esc(c.l.id)}">details</button>`}</td></tr></table></div>`; };
  $('cmp').innerHTML = `<div class="crow" style="margin-bottom:10px"><b>Side by side</b><button class="btn ghost" id="cmpx">close</button></div><div class="cols" style="grid-template-columns:repeat(${CMP.length},minmax(0,1fr))">${CMP.map(col).join('')}</div>`;
}
$('cmp').addEventListener('click', e => { if (e.target.id === 'cmpx') return $('cmp').classList.remove('show'); const o = e.target.closest('[data-open]'); if (o) { $('cmp').classList.remove('show'); openDrawer(o.dataset.open); }
  const z = e.target.closest('[data-zoom]'); if (z && z.dataset.zoom) { $('lbimg').src = z.dataset.zoom; $('lb').classList.add('open'); } });

// ---------- boot ----------
initMap();
fetch('/api/listings', { cache: 'no-store' }).then(r => r.json()).then(doc => {
  ALL = doc.listings;
  for (const l of ALL) { BYID.set(l.id, l);
    l._text = [l.title, l.address, l.building, l.neighborhood, l.id, ...l.units.map(u => u.plan_name), ...l.plans.map(p => p.name)].join(' ').toLowerCase(); }
  drawPins();
  const pts = ALL.filter(l => l.in_sf && l.lat != null).map(l => [l.lat, l.lon]);
  if (pts.length && !P.get('open')) map.fitBounds(pts, { padding: [30, 30], maxZoom: 14 });
  renderFeed();
  if (P.get('open')) openDrawer(P.get('open'), P.get('unit'));
  for (const k of (P.get('compare') || '').split(',').filter(Boolean)) toggleCompare(k);
  if (P.get('compare') && CMP.length > 1 && P.get('cmpopen')) { $('cmp').classList.add('show'); drawCompare(); }
}).catch(e => { $('feed').innerHTML = `<div class="empty">listings index missing: run app/map/listings_index.py (${esc(e)})</div>`; });
