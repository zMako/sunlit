// "Design with AI" panel for apartment.html: budget + style -> streaming furnishing of the active room with animated placements and
// rejections, a chat box for live edits, camera presets and a high-res render button.
// Relies on: window.apartment {layout, scene, camera, renderer, apt}, window.furnishByRoom (filled by furnish.js), window.setWalk/setDoll.
import * as THREE from 'three';

const css = `#ai{position:fixed;left:12px;bottom:12px;width:340px;background:rgba(18,22,30,.92);color:#e8edf3;border:1px solid #2a3444;border-radius:12px;padding:12px;font:13px/1.4 -apple-system,Inter,sans-serif;z-index:20;backdrop-filter:blur(6px)}
#ai h3{margin:0 0 8px;font-size:14px}#ai label{display:block;color:#9aa6b5;font-size:11px;margin-top:6px}#ai input,#ai textarea{width:100%;box-sizing:border-box;background:#0f1319;color:#e8edf3;border:1px solid #2a3444;border-radius:8px;padding:6px 8px;font:13px inherit}
#ai button{background:#6ea8fe;color:#07111f;border:none;border-radius:8px;padding:6px 10px;font-weight:600;cursor:pointer;margin:4px 4px 0 0}#ai button.sec{background:#2a3444;color:#dfe7f1}#ai button:disabled{opacity:.5}
#ai .bar{height:8px;background:#1a2230;border-radius:4px;overflow:hidden;margin-top:6px}#ai .bar i{display:block;height:100%;background:linear-gradient(90deg,#7fe0b4,#6ea8fe);width:0;transition:width .4s}
#ai .log{max-height:150px;overflow:auto;margin-top:8px;font-size:12px}#ai .log div{padding:2px 0;border-bottom:1px dashed #1f2835}#ai .ok{color:#7fe0b4}#ai .bad{color:#ff8a8a}#ai .dim{color:#9aa6b5}
#ai .card{background:#13233a;border-radius:8px;padding:8px;margin-top:8px}#ai .row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}`;
const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);

const el = document.createElement('div'); el.id = 'ai'; el.innerHTML = `
<h3>Design with AI <span class="dim" id="aiRoom"></span></h3>
<div class="row"><div style="flex:1"><label>Budget (USD)</label><input id="aiBudget" type="number" value="3500" min="200" step="100"></div><div style="flex:2"><label>Style</label><input id="aiStyle" value="warm scandinavian"></div></div>
<div class="row"><button id="aiGo">Furnish this room</button><button id="aiAll" class="sec">Whole apartment</button><button id="aiStop" class="sec" style="display:none">Stop</button></div>
<div class="bar"><i id="aiBar"></i></div><div class="dim" id="aiSpent">no plan yet</div>
<div class="log" id="aiLog"></div><div id="aiCard"></div>
<label>Ask for changes</label><div class="row"><textarea id="aiChat" rows="2" placeholder="move the sofa to the window wall, swap the rug for something darker, add a plant…" style="flex:1"></textarea><button id="aiSend">Send</button></div>
<div class="row" style="margin-top:8px"><span class="dim">Views:</span><button class="sec" data-cam="overview">overview</button><button class="sec" data-cam="door">from door</button><button class="sec" data-cam="window">window corner</button><button class="sec" data-cam="sofa">sofa view</button><button class="sec" id="aiRender">Render 2×</button></div>`;
document.body.appendChild(el);
const $ = id => document.getElementById(id);

function ready() { return window.apartment && window.furnishByRoom && Object.keys(window.furnishByRoom).length; }
await new Promise(r => { const t = setInterval(() => { if (ready()) { clearInterval(t); r(); } }, 200); });
const A = window.apartment; const layout = A.layout; const camera = A.camera, renderer = A.renderer, scene = A.scene;
const Q = new URLSearchParams(location.search);

// ---------- room selection ----------
function activeRoomId() {   // the Furnish with the panel, else nearest to the camera, else first non-service room
  for (const f of Object.values(window.furnishByRoom)) if (f.active) return f.room.split('__')[1];
  let best = null, bd = Infinity; for (const [id, r] of Object.entries(A.apt.roomMeshes)) { const d = r.center.distanceTo(new THREE.Vector3(camera.position.x, 0, camera.position.z)); if (d < bd) { bd = d; best = id; } }
  return best || layout.rooms[0].id;
}
function furnOf(roomId) { return window.furnishByRoom[`${layout.unit}__${roomId}`]; }
function roomMeta(roomId) { return layout.rooms.find(r => r.id === roomId); }
function roomCenter(roomId) { return A.apt.roomMeshes[roomId]?.center || new THREE.Vector3(); }
function doorPoint(f) {   // first door of the room (in room coords = unit coords), 0.4 m inside
  if (f.doors && f.doors.length) { const d = f.doors[0]; return new THREE.Vector3(d.mid.x + d.inward.x * 0.4, 0, d.mid.y + d.inward.y * 0.4); }
  const c = roomCenter(f.room.split('__')[1]); return new THREE.Vector3(c.x, 0, c.z - 2);
}
function windowPoint(f) {
  if (f.windows && f.windows.length) { const w = f.windows[0]; const e = f.edges[w.edge]; const dir = e.b.clone().sub(e.a).normalize(); const m = e.a.clone().add(dir.multiplyScalar((w.s0 + w.s1) / 2)); const inward = e.n.clone().negate(); return new THREE.Vector3(m.x + inward.x * 0.5, 0, m.y + inward.y * 0.5); }
  return null;
}

// ---------- camera moves ----------
let tweens = [];
function tween(ms, fn, done) { const t0 = performance.now(); tweens.push({ t0, ms, fn, done }); }
(function loop() { requestAnimationFrame(loop); const now = performance.now(); tweens = tweens.filter(t => { const k = Math.min(1, (now - t.t0) / t.ms); const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; t.fn(e); if (k >= 1) { t.done && t.done(); return false; } return true; }); })();
function orbitOf() { return Object.values(window.furnishByRoom)[0]?.controls; }
function flyTo(pos, look, ms = 900, fov) {
  const orbit = orbitOf(); const p0 = camera.position.clone(), l0 = orbit ? orbit.target.clone() : look.clone(); const f0 = camera.fov, f1 = fov || camera.fov;
  tween(ms, e => { camera.position.lerpVectors(p0, pos, e); const l = l0.clone().lerp(look, e); if (orbit && orbit.enabled) { orbit.target.copy(l); orbit.update(); } else camera.lookAt(l); camera.fov = f0 + (f1 - f0) * e; camera.updateProjectionMatrix(); });
}
function topDown(roomId) {
  window.setDoll && window.setDoll(); const c = roomCenter(roomId); const r = roomMeta(roomId); const ext = Math.sqrt(r.area_m2 || 12) * 1.9 + 2;
  flyTo(new THREE.Vector3(c.x + 0.01, ext, c.z + 0.6), new THREE.Vector3(c.x, 0, c.z), 900, 42);
}
function walkAt(pos, look) { window.setWalk && window.setWalk(activeRoomId()); setTimeout(() => flyTo(new THREE.Vector3(pos.x, 1.55, pos.z), new THREE.Vector3(look.x, 1.3, look.z), 800, 68), 30); }
function camPreset(kind) {
  const id = activeRoomId(); const f = furnOf(id); const c = roomCenter(id);
  if (kind === 'overview' || !f) return topDown(id);
  if (kind === 'door') { const d = doorPoint(f); return walkAt(d, c); }
  if (kind === 'window') { const w = windowPoint(f) || doorPoint(f); const away = c.clone().sub(w).normalize(); return walkAt(w.clone().add(away.multiplyScalar(0.6)), c); }
  if (kind === 'sofa') { const sofa = f.items.find(i => ['sofa', 'bed', 'armchair'].includes(i.spec.category)); if (!sofa) return walkAt(doorPoint(f), c);
    const s = sofa.spec; const r = -s.rot_deg * Math.PI / 180; const fwd = new THREE.Vector3(Math.sin(r), 0, Math.cos(r)); const pos = new THREE.Vector3(s.x, 0, s.z).sub(fwd.clone().multiplyScalar(0.2)); const look = pos.clone().add(fwd.multiplyScalar(4)); return walkAt(pos, look); }
}
el.querySelectorAll('[data-cam]').forEach(b => b.onclick = () => camPreset(b.dataset.cam));
$('aiRender').onclick = () => { const w = renderer.domElement.width, h = renderer.domElement.height; renderer.setPixelRatio(Math.min(3, devicePixelRatio * 2)); renderer.render(scene, camera); const url = renderer.domElement.toDataURL('image/png'); renderer.setPixelRatio(devicePixelRatio); const a = document.createElement('a'); a.href = url; a.download = `${layout.unit}_${activeRoomId()}_render.png`; a.click(); };

// ---------- item animations ----------
function flash(it, color) { it.obj.traverse(o => { if (!o.isMesh || !o.material || o.isSprite) return; const ms = Array.isArray(o.material) ? o.material : [o.material]; const nm = ms.map(m => { const c = m.clone(); if ('emissive' in c) { c.emissive = new THREE.Color(color); c.emissiveIntensity = 0.9; } else if (c.color) c.color = new THREE.Color(color); return c; }); o.material = Array.isArray(o.material) ? nm : nm[0]; }); }
async function animatePlace(f, spec, from) {
  const it = await f.addItem(spec, false); const target = new THREE.Vector3(spec.x, 0, spec.z); const start = new THREE.Vector3(from.x, 1.6, from.z); it.obj.position.copy(start); it.obj.scale.setScalar(0.3);
  return new Promise(res => tween(650, e => { it.obj.position.lerpVectors(start, target, e); it.obj.position.y = (1 - e) * 1.6 * (1 - e); it.obj.scale.setScalar(0.3 + 0.7 * e); }, () => { it.obj.position.copy(target); it.obj.scale.setScalar(1); f._refresh(); res(it); }));
}
async function animateReject(f, spec, from, reason) {
  const it = await f.addItem({ ...spec, x: from.x, z: from.z }, false); it.obj.position.set(from.x, 0.05, from.z); flash(it, 0xff3b3b); f.toast && f.toast(`✗ ${reason}`);
  await new Promise(r => setTimeout(r, 700));
  await new Promise(res => tween(600, e => { it.obj.position.y = e * 3; it.obj.scale.setScalar(1 - 0.7 * e); it.obj.rotation.y += 0.08; }, () => { f.group.remove(it.obj); f.items = f.items.filter(o => o !== it); f._refresh(); res(); }));
}
async function animateMove(f, it, to) { const p0 = it.obj.position.clone(); const p1 = new THREE.Vector3(to.x, 0, to.z); const r0 = it.obj.rotation.y, r1 = -(to.rot_deg || 0) * Math.PI / 180; return new Promise(res => tween(700, e => { it.obj.position.lerpVectors(p0, p1, e); it.obj.position.y = Math.sin(e * Math.PI) * 0.4; it.obj.rotation.y = r0 + (r1 - r0) * e; }, () => { f._place(it, to.x, to.z, to.rot_deg || 0); f._refresh(); res(); })); }

// ---------- streaming furnish ----------
let es = null, budget = 3500;
function log(html, cls = '') { const d = document.createElement('div'); d.className = cls; d.innerHTML = html; $('aiLog').prepend(d); }
function setSpent(spent) { const pct = budget ? Math.min(100, spent / budget * 100) : 0; $('aiBar').style.width = pct + '%'; $('aiBar').style.background = pct > 100 ? '#ff8a8a' : ''; $('aiSpent').textContent = `$${spent.toFixed(0)} of $${budget.toFixed(0)}`; }
async function furnishRoom(roomId) {
  const f = furnOf(roomId); if (!f) return log('no furniture layer for this room', 'bad');
  budget = +$('aiBudget').value || 0; const styleTxt = $('aiStyle').value; $('aiRoom').textContent = `· ${roomMeta(roomId).name}`;
  // activate the room's panel the same way apartment.html does
  for (const o of Object.values(window.furnishByRoom)) if (o !== f && o.active) { o.setActive(false); o.panelEl = null; }
  const furnEl = document.getElementById('furn'); if (furnEl) { f.panelEl = furnEl; f.setActive(true); f._panel(); furnEl.style.display = 'block'; }
  f.clear(); topDown(roomId); $('aiLog').innerHTML = ''; $('aiCard').innerHTML = ''; setSpent(0); $('aiGo').disabled = true; $('aiAll').disabled = true; $('aiStop').style.display = '';
  const from = doorPoint(f); let queue = Promise.resolve();
  return new Promise(resolve => {
    es = new EventSource(`/api/agent/furnish?room=${encodeURIComponent(f.room)}&budget=${budget}&style=${encodeURIComponent(styleTxt)}${Q.has('drama') ? '&drama=1' : ''}`);
    es.onmessage = ev => { const e = JSON.parse(ev.data); queue = queue.catch(() => {}).then(async () => {
      if (e.event === 'shortlist') log(`<b>Palette:</b> ${e.palette || ''} · wood: ${e.wood || ''} · accent: ${e.accent || ''}`);
      else if (e.event === 'consider') log(`<span class="dim">considering</span> ${e.item.name} <span class="dim">$${e.item.price_usd}</span>`);
      else if (e.event === 'place') { await animatePlace(f, e.item, from); setSpent(e.spent); log(`<span class="ok">✓ placed</span> ${e.item.name} <span class="dim">· ${e.why || ''}</span>`, 'ok'); }
      else if (e.event === 'reject') { await animateReject(f, e.item, from, e.reason); log(`<span class="bad">✗ rejected</span> ${e.item.name}: ${e.reason}`, 'bad'); }
      else if (e.event === 'skip') log(`<span class="dim">skipped ${e.slot}: ${e.reason}</span>`);
      else if (e.event === 'error') log(`error: ${e.message}`, 'bad');
      else if (e.event === 'summary') { $('aiCard').innerHTML = `<div class="card"><b>${e.n_items} items · $${(e.total_usd || 0).toFixed(0)}</b> <span class="dim">(${e.saved_usd >= 0 ? '$' + e.saved_usd.toFixed(0) + ' under budget' : '$' + (-e.saved_usd).toFixed(0) + ' over'})</span><br><span class="dim">${e.palette || ''}</span><br>${e.notes || ''}</div>`; }
      else if (e.event === 'end') { es && es.close(); es = null; await f.loadPlan(); $('aiGo').disabled = false; $('aiAll').disabled = false; $('aiStop').style.display = 'none'; window.furnishOnChange && window.furnishOnChange(); resolve(); }
    }).catch(err => log(`ui error: ${err.message}`, 'bad')); };
    es.onerror = () => { if (!es) return; log('stream closed', 'dim'); es.close(); es = null; $('aiGo').disabled = false; $('aiAll').disabled = false; $('aiStop').style.display = 'none'; resolve(); };
  });
}
$('aiGo').onclick = () => furnishRoom(activeRoomId());
$('aiStop').onclick = () => { es && es.close(); es = null; $('aiGo').disabled = false; $('aiAll').disabled = false; $('aiStop').style.display = 'none'; };
$('aiAll').onclick = async () => { for (const r of layout.rooms) { if (['hallway', 'closet', 'bathroom', 'entry', 'laundry'].includes(r.type) || !furnOf(r.id)) continue; await furnishRoom(r.id); } };

// ---------- chat edits ----------
$('aiSend').onclick = async () => {
  const msg = $('aiChat').value.trim(); if (!msg) return; const id = activeRoomId(); const f = furnOf(id); if (!f) return;
  $('aiSend').disabled = true; log(`<b>you:</b> ${msg}`);
  try {
    const r = await fetch('/api/agent/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ room: f.room, message: msg, plan: f.toPlan(), budget: +$('aiBudget').value || null, style: $('aiStyle').value }) });
    const j = await r.json(); if (j.error) throw new Error(j.error);
    log(`<b>agent:</b> ${j.reply}`);
    // animate the diff: moved items glide, removed fly out, new ones drop in
    const next = j.plan.items || []; const byId = Object.fromEntries(next.map(i => [i.id, i])); const from = doorPoint(f);
    for (const it of [...f.items]) { const n = byId[it.spec.id]; if (!n) { await animateReject(f, it.spec, { x: it.spec.x, z: it.spec.z }, 'removed'); continue; }
      if (n.x != null && (Math.abs(n.x - it.spec.x) > 0.02 || Math.abs(n.z - it.spec.z) > 0.02 || Math.abs((n.rot_deg || 0) - it.spec.rot_deg) > 1)) await animateMove(f, it, n); }
    for (const n of next) if (n.x != null && !f.itemById(n.id)) await animatePlace(f, n, from);
    f.plan = j.plan; f._refresh(); f.save && f.save(); $('aiChat').value = ''; setSpent(j.plan.total_usd || 0);
  } catch (e) { log(`error: ${e.message}`, 'bad'); }
  $('aiSend').disabled = false;
};

// ---------- auto-start from the URL (headless demos): ?agent=r0&budget=3500&style=... ----------
if (Q.has('budget')) $('aiBudget').value = Q.get('budget'); if (Q.has('style')) $('aiStyle').value = Q.get('style');
if (Q.has('agent')) setTimeout(() => furnishRoom(Q.get('agent')), 1500);
