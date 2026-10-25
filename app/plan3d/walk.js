// First-person walk physics for apartment.html: collisions with walls, closed doors, windows, furniture and fixtures
// (per-axis sweep so you slide along walls), doors that open/close on E or click with a hinge animation and block
// while closed, head bob, bump feedback, and a HUD with the current room and action prompt. Reads the builder's
// window.apartment and the per-room Furnish instances; exposes window.walk for other modules and headless tests.
import * as THREE from 'three';

const R = 0.30, EYE = 1.6, SPEED = 1.7, RUN = 3.2, ACCEL = 10, FRICTION = 9, DOOR_TIME = 0.5, REACH = 1.2;
const until = (f) => new Promise(res => { const t = () => (f() ? res() : setTimeout(t, 60)); t(); });
await until(() => window.apartment && window.apartment.layout && window.apartment.apt);
const { layout, apt, camera, renderer } = window.apartment;

// ---------- geometry helpers ----------
const v2 = (p) => new THREE.Vector2(p[0], p[1]);
function wallFrame(w) {   // same convention as build.js: n is the "in" side (left normal of a->b)
  const a = v2(w.a), b = v2(w.b), d = b.clone().sub(a); const len = d.length(); d.normalize();
  return { id: w.id, a, b, d, n: new THREE.Vector2(-d.y, d.x), len, t: w.thickness_m || 0.15 };
}
const frames = Object.fromEntries(layout.walls.map(w => [w.id, wallFrame(w)]));
const UB = (() => { const xs = layout.walls.flatMap(w => [w.a[0], w.b[0]]), zs = layout.walls.flatMap(w => [w.a[1], w.b[1]]); const m = 2.5; return { minX: Math.min(...xs) - m, maxX: Math.max(...xs) + m, minZ: Math.min(...zs) - m, maxZ: Math.max(...zs) + m }; })();
// an oriented box collider: centre c (Vector2), unit axis u, half extents hu (along u) and hv (across)
function obb(c, u, hu, hv, tag) { return { c, u, v: new THREE.Vector2(-u.y, u.x), hu, hv, tag }; }
function obbAlong(fr, s0, s1, offN = 0, thick = null) {
  const c = fr.a.clone().add(fr.d.clone().multiplyScalar((s0 + s1) / 2)).add(fr.n.clone().multiplyScalar(offN));
  return obb(c, fr.d, (s1 - s0) / 2, (thick ?? fr.t) / 2, fr.id);
}
function pointInPoly(p, poly) { let inside = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, zi] = poly[i], [xj, zj] = poly[j]; if ((zi > p.y) !== (zj > p.y) && p.x < (xj - xi) * (p.y - zi) / (zj - zi + 1e-12) + xi) inside = !inside; } return inside; }

// ---------- doors ----------
// state per door opening; the builder's leaf pivot carries userData {kind:'door', opening}
const doors = new Map();
for (const o of layout.openings) {
  if (!(o.type === 'door' || o.type === 'closet_door')) continue;
  const fr = frames[o.wall]; if (!fr) continue;
  const sw = o.swing || 'in_left'; const side = sw.startsWith('out') ? -1 : 1; const dir = sw.endsWith('left') ? 1 : -1;
  const hingeS = sw.endsWith('left') ? o.s0 + 0.02 : o.s1 - 0.02; const lw = (o.s1 - o.s0) - 0.05;
  const hinge = fr.a.clone().add(fr.d.clone().multiplyScalar(hingeS)); const centre = fr.a.clone().add(fr.d.clone().multiplyScalar((o.s0 + o.s1) / 2));
  let pivot = null; apt.group.traverse(obj => { if (obj.userData && obj.userData.kind === 'door' && obj.userData.opening === o.id) pivot = obj; });
  const closedAngle = -Math.atan2(fr.d.y, fr.d.x);   // fr.angle in build.js
  const d = { id: o.id, o, fr, side, dir, hinge, centre, lw, pivot, closedAngle, openDelta: -dir * side * Math.PI / 2, open: false, t: 0, anim: null, closet: o.type === 'closet_door' };
  if (pivot) pivot.rotation.y = closedAngle;   // start closed (the builder leaves it 9 deg ajar)
  doors.set(o.id, d);
}
function doorAngle(d) { const k = d.t; return d.closedAngle + d.openDelta * (1 - Math.cos(Math.PI * k)) / 2; }   // eased 0..1
function toggleDoor(id) { const d = doors.get(id); if (!d) return false; d.open = !d.open; d.anim = { from: d.t, to: d.open ? 1 : 0, start: performance.now() }; dirty = true; click(d.open ? 520 : 380); return d.open; }
function animateDoors(now) {
  for (const d of doors.values()) {
    if (d.anim) { const k = Math.min(1, (now - d.anim.start) / (DOOR_TIME * 1000)); d.t = d.anim.from + (d.anim.to - d.anim.from) * k; if (k >= 1) { d.anim = null; dirty = true; } if (d.pivot) d.pivot.rotation.y = doorAngle(d); }
  }
}

// ---------- colliders ----------
function wallColliders() {   // every wall as a box; open doors and cased openings carve gaps out of ANY parallel wall collider they overlap
  let out = [];
  for (const w of layout.walls) { const fr = frames[w.id]; out.push(obbAlong(fr, -fr.t / 2, fr.len + fr.t / 2)); }
  const gaps = [];
  for (const o of layout.openings) {
    const fr = frames[o.wall]; if (!fr) continue;
    const passable = o.type === 'opening' || ((o.type === 'door' || o.type === 'closet_door') && (doors.get(o.id)?.t ?? 0) > 0.85);
    if (!passable) { out.push(obbAlong(fr, o.s0, o.s1)); continue; }   // closed door / window: a blocker across the span (layouts may leave the wall itself gapped there)
    const g0 = fr.a.clone().add(fr.d.clone().multiplyScalar(o.s0)), g1 = fr.a.clone().add(fr.d.clone().multiplyScalar(o.s1)); gaps.push({ c: g0.clone().add(g1).multiplyScalar(0.5), u: fr.d, hu: (o.s1 - o.s0) / 2 });
  }
  for (const g of gaps) {
    const next = [];
    for (const b of out) {
      const parallel = Math.abs(b.u.dot(g.u)) > 0.9; const rel = g.c.clone().sub(b.c);
      if (!parallel || Math.abs(rel.dot(b.v)) > b.hv + 0.08) { next.push(b); continue; }
      const gs = rel.dot(b.u); const lo = gs - g.hu, hi = gs + g.hu;   // gap interval along the box axis, relative to the box centre
      if (hi <= -b.hu || lo >= b.hu) { next.push(b); continue; }        // no overlap along the wall
      if (lo > -b.hu + 0.02) next.push(obb(b.c.clone().add(b.u.clone().multiplyScalar((-b.hu + lo) / 2)), b.u, (lo + b.hu) / 2, b.hv, b.tag));
      if (hi < b.hu - 0.02) next.push(obb(b.c.clone().add(b.u.clone().multiplyScalar((hi + b.hu) / 2)), b.u, (b.hu - hi) / 2, b.hv, b.tag));
    }
    out = next;
  }
  // the leaf of an open (or opening) door stands into the room from its hinge
  for (const d of doors.values()) {
    if (d.t <= 0.05) continue;
    const ang = doorAngle(d) - d.closedAngle; const leafDir = d.fr.d.clone().multiplyScalar(d.dir);
    const rot = new THREE.Vector2(leafDir.x * Math.cos(-ang) - leafDir.y * Math.sin(-ang), leafDir.x * Math.sin(-ang) + leafDir.y * Math.cos(-ang));
    const c = d.hinge.clone().add(rot.clone().multiplyScalar(d.lw / 2)); out.push(obb(c, rot.clone().normalize(), d.lw / 2, 0.03, 'leaf'));
  }
  return out;
}
function itemColliders() {
  const out = []; const byRoom = window.furnishByRoom || {};
  for (const f of Object.values(byRoom)) for (const it of (f.items || [])) {
    const s = it.spec || {}; if (+s.h_m < 0.12 || s.category === 'rug') continue;   // rugs are walkable
    const rot = -THREE.MathUtils.degToRad(+s.rot_deg || 0); const u = new THREE.Vector2(Math.cos(rot), -Math.sin(rot));   // local x after yaw rot_deg (rotation.y = -rot)
    out.push(obb(new THREE.Vector2(+s.x || 0, +s.z || 0), u, (+s.w_m || 0.5) / 2, (+s.d_m || 0.5) / 2, 'item'));
  }
  for (const fx of layout.fixtures || []) {   // fixtures from the layout (counters, tub...) in case no Furnish instance carries them
    const r = fx.rect || {}; if (fx.type === 'closet_rod') continue;
    const rot = -THREE.MathUtils.degToRad(+r.rot_deg || 0); const u = new THREE.Vector2(Math.cos(rot), -Math.sin(rot));
    out.push(obb(new THREE.Vector2(+r.x || 0, +r.z || 0), u, (+r.w || 0.5) / 2, (+r.d || 0.5) / 2, 'fixture'));
  }
  return out;
}
function resolve(p, cols) {   // push a disc of radius R out of every box; a few passes so corners settle
  let hit = false;
  for (let pass = 0; pass < 3; pass++) {
    let moved = false;
    for (const b of cols) {
      const rel = p.clone().sub(b.c); const ls = rel.dot(b.u), ln = rel.dot(b.v);
      const ps = b.hu + R - Math.abs(ls), pn = b.hv + R - Math.abs(ln);
      if (ps <= 0 || pn <= 0) continue;
      if (pn < ps) p.add(b.v.clone().multiplyScalar(Math.sign(ln || 1) * pn)); else p.add(b.u.clone().multiplyScalar(Math.sign(ls || 1) * ps));
      hit = moved = true;
    }
    if (!moved) break;
  }
  return hit;
}

// ---------- player ----------
const keys = {}; addEventListener('keydown', e => { keys[e.code] = true; if (e.code === 'KeyE' && enabled()) tryToggle(); }); addEventListener('keyup', e => keys[e.code] = false);
renderer.domElement.addEventListener('click', () => { if (enabled() && document.pointerLockElement) tryToggle(); });
const player = { pos: new THREE.Vector2(camera.position.x, camera.position.z), vel: new THREE.Vector2(), radius: R, eye: EYE, bob: 0, nudge: 0, moving: false, room: null, prompt: null };
let lastPos = player.pos.clone(); let wallCols = wallColliders(); let dirty = false;
function enabled() { const b = document.getElementById('bWalk'); return !!(b && b.classList.contains('on')); }
function forward() { const f = new THREE.Vector3(); camera.getWorldDirection(f); return new THREE.Vector2(f.x, f.z).normalize(); }
function wish(k) { const f = (k.KeyW ? 1 : 0) - (k.KeyS ? 1 : 0), s = (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0); if (!f && !s) return new THREE.Vector2(); const fw = forward(); const rt = new THREE.Vector2(-fw.y, fw.x); return fw.multiplyScalar(f).add(rt.multiplyScalar(s)).normalize(); }
function step(dt, k = keys) {
  animateDoors(performance.now()); if (dirty || [...doors.values()].some(d => d.anim)) { wallCols = wallColliders(); dirty = false; }
  const target = wish(k).multiplyScalar(k.ShiftLeft || k.ShiftRight ? RUN : SPEED);
  const a = target.lengthSq() > 0 ? ACCEL : FRICTION; player.vel.lerp(target, 1 - Math.exp(-a * dt));
  const cols = wallCols.concat(itemColliders()); const p = player.pos.clone(); let hit = false;
  p.x += player.vel.x * dt; hit = resolve(p, cols) || hit;         // per-axis sweep: x, then z, so you slide along walls
  p.y += player.vel.y * dt; hit = resolve(p, cols) || hit;
  // soft world bound: the unit's bounding box plus 2.5 m (balconies/patios are drawn outside the walls)
  const cx = Math.min(Math.max(p.x, UB.minX), UB.maxX), cz = Math.min(Math.max(p.y, UB.minZ), UB.maxZ); if (cx !== p.x || cz !== p.y) { p.set(cx, cz); hit = true; }
  const blocked = hit && p.distanceTo(player.pos.clone().add(player.vel.clone().multiplyScalar(dt))) > 0.004 && player.vel.length() > 0.4;
  if (blocked && player.nudge <= 0) { player.nudge = 0.12; click(140, 0.05); player.vel.multiplyScalar(0.3); }
  player.pos.copy(p); player.moving = player.vel.length() > 0.2;
  player.bob += dt * (player.moving ? player.vel.length() * 5.5 : 0); if (!player.moving) player.bob *= 0.9;
  player.nudge = Math.max(0, player.nudge - dt);
  camera.position.x = p.x; camera.position.z = p.y;
  camera.position.y = EYE + (player.moving ? Math.sin(player.bob) * 0.03 : 0) + (player.nudge > 0 ? -player.nudge * 0.15 : 0);
  lastPos.copy(p);
}
function nearestDoor() {
  const fw = forward(); let best = null;
  for (const d of doors.values()) {
    const to = d.centre.clone().sub(player.pos); const dist = to.length(); if (dist > REACH + 0.3) continue;
    const facing = to.clone().normalize().dot(fw); if (facing < 0.25) continue;
    const score = dist - facing * 0.5; if (!best || score < best.score) best = { d, dist, score };
  }
  return best ? best.d : null;
}
function tryToggle() { const d = nearestDoor(); if (d) { toggleDoor(d.id); dirty = true; } }
function roomAt(p) { for (const r of layout.rooms) if (pointInPoly(p, r.polygon)) return r; return null; }

// ---------- HUD + feedback ----------
const hud = document.createElement('div'); hud.id = 'walkhud';
hud.style.cssText = 'position:fixed;left:50%;bottom:64px;transform:translateX(-50%);padding:6px 12px;border-radius:8px;background:rgba(10,14,20,.72);color:#e8edf3;font:13px/1.4 -apple-system,Inter,sans-serif;display:none;pointer-events:none;text-align:center;z-index:30';
document.body.appendChild(hud);
let audio = null;
function click(freq = 440, dur = 0.04) { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); const o = audio.createOscillator(), g = audio.createGain(); o.frequency.value = freq; o.type = 'triangle'; g.gain.setValueAtTime(0.08, audio.currentTime); g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + dur); o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + dur); } catch (e) { /* no audio in headless */ } }

// ---------- main loop: runs after the builder's loop in the same frame; the builder's own bounded movement is overridden ----------
let wasEnabled = false; let lastT = performance.now();
(function loop() {
  requestAnimationFrame(loop); const now = performance.now(); const dt = Math.min((now - lastT) / 1000, 0.05); lastT = now;
  const on = enabled();
  if (on && !wasEnabled) { player.pos.set(camera.position.x, camera.position.z); player.vel.set(0, 0); lastPos.copy(player.pos); hud.style.display = 'block'; }
  if (!on && wasEnabled) hud.style.display = 'none';
  wasEnabled = on; if (!on) return;
  animateDoors(now); if (dirty || [...doors.values()].some(d => d.anim)) { wallCols = wallColliders(); dirty = false; }
  if (!window.walk?.manual) { camera.position.x = lastPos.x; camera.position.z = lastPos.y; step(dt); }   // undo the builder's move, then ours
  const r = roomAt(player.pos); const d = nearestDoor(); player.room = r ? r.name : null; player.prompt = d ? `E · ${d.open ? 'close' : 'open'} the ${d.closet ? 'closet' : 'door'}` : null;
  hud.innerHTML = `${r ? `<b>${r.name}</b>` : ''}${d ? ` &nbsp;·&nbsp; <span style="color:#9fc6ff">${player.prompt}</span>` : ''}` || 'walk: WASD · Shift run · E doors';
})();

// ---------- public API (agent/render workers, headless tests) ----------
window.walk = {
  player, doors, layout,
  manual: false,                                  // when true the loop does not move the player; use step() yourself
  setEnabled: (on) => on ? window.setWalk?.() : window.setDoll?.(),
  step: (dt, k) => { step(dt, k || {}); lastPos.copy(player.pos); },   // single physics step for tests (velocity persists between calls)
  teleport: (x, z) => { player.pos.set(x, z); player.vel.set(0, 0); lastPos.copy(player.pos); camera.position.set(x, EYE, z); },
  look: (yawDeg) => { const y = THREE.MathUtils.degToRad(yawDeg); camera.rotation.set(0, 0, 0); camera.lookAt(camera.position.x + Math.sin(y), EYE - 0.05, camera.position.z + Math.cos(y)); },
  lookAt: (x, z) => { camera.rotation.set(0, 0, 0); camera.lookAt(x, EYE - 0.1, z); },
  toggleDoor, nearestDoor: () => nearestDoor()?.id || null, doorList: () => [...doors.values()].map(d => ({ id: d.id, open: d.open, centre: [d.centre.x, d.centre.y], wall: d.fr.id, closet: d.closet })),
  colliders: () => wallCols.concat(itemColliders()).length,
  near: (x, z, r = 1.0) => wallCols.concat(itemColliders()).filter(b => { const rel = new THREE.Vector2(x, z).sub(b.c); return Math.abs(rel.dot(b.u)) < b.hu + r && Math.abs(rel.dot(b.v)) < b.hv + r; }).map(b => ({ tag: b.tag, c: [+b.c.x.toFixed(2), +b.c.y.toFixed(2)], hu: +b.hu.toFixed(2), hv: +b.hv.toFixed(2), u: [+b.u.x.toFixed(2), +b.u.y.toFixed(2)] })), roomAt: (x, z) => roomAt(new THREE.Vector2(x, z))?.name || null,
};
