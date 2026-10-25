// First-person walk physics for apartment.html: collisions with walls, closed doors, windows, furniture and fixtures
// (per-axis sweep so you slide along walls), doors that open/close on E or click with a hinge animation and block
// while closed, head bob, bump feedback, and a HUD with the current room and action prompt. Reads the builder's
// window.apartment and the per-room Furnish instances; exposes window.walk for other modules and headless tests.
import * as THREE from 'three';

const R = 0.30, EYE = 1.6, SPEED = 1.7, RUN = 3.2, ACCEL = 10, FRICTION = 9, DOOR_TIME = 0.5, REACH = 1.2;
const G = 9.8, JUMP = 4.4, STEP = 0.32, HEAD = 1.75;   // gravity, jump speed (~1 m: onto beds, tables, counters), auto step-up (stairs), body height
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
// ---------- levels (townhouses): each wall / room / fixture has a level; level k sits at elevation_m ----------
const LEVELS = (layout.levels && layout.levels.length > 1) ? layout.levels : [{ id: 0, elevation_m: 0 }]; const CEIL = layout.ceiling_m || 2.6;
const elev = (k) => (LEVELS.find(v => v.id === (k || 0)) || LEVELS[0]).elevation_m;
const wallLevel = Object.fromEntries(layout.walls.map(w => [w.id, w.level || 0])); const roomLevel = Object.fromEntries(layout.rooms.map(r => [r.id, r.level || 0]));
const levelAt = (feet) => { let k = LEVELS[0].id; for (const v of LEVELS) if (feet >= v.elevation_m - 0.3) k = v.id; return k; };
const STAIRS = (layout.stairs || []).map(st => ({ st, steps: apt.stairSteps ? apt.stairSteps(st) : [], rails: apt.stairRails ? apt.stairRails(st) : [], base: elev(st.from_level), r: st.rect }));
const inRect = (p, r, m = 0) => Math.abs(p.x - r.x) <= r.w / 2 + m && Math.abs(p.y - r.z) <= r.d / 2 + m;
const inStairwell = (p, toLevel) => STAIRS.some(S => S.st.to_level === toLevel && inRect(p, S.r));
const inRings = (p, rings) => rings.some(rg => pointInPoly(p, rg.outer) && !(rg.holes || []).some(h => pointInPoly(p, h)));
// a level's floor: its slab (footprint minus stairwells, levels.py) or, without one, its rooms
const onFloor = (p, v) => v.floor_slab && v.floor_slab.length ? inRings(p, v.floor_slab) : (!inStairwell(p, v.id) && layout.rooms.some(r => (r.level || 0) === v.id && pointInPoly(p, r.polygon)));
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
  const pair = pivot && pivot.userData.pair ? pivot.userData.pair : null;   // two leaves (doors.py): hinged at both jambs
  const d = { id: o.id, o, fr, side, dir, hinge, centre, lw, pivot, pair, closedAngle, openDelta: -dir * side * Math.PI / 2, open: false, t: 0, anim: null, closet: o.type === 'closet_door' };
  if (pair) for (const pv of pair) pv.rotation.y = closedAngle; else if (pivot) pivot.rotation.y = closedAngle;   // start closed (the builder leaves it 9 deg ajar)
  doors.set(o.id, d);
}
function doorAngle(d) { const k = d.t; return d.closedAngle + d.openDelta * (1 - Math.cos(Math.PI * k)) / 2; }   // eased 0..1
function toggleDoor(id) { const d = doors.get(id); if (!d) return false; d.open = !d.open; d.anim = { from: d.t, to: d.open ? 1 : 0, start: performance.now() }; dirty = true; click(d.open ? 520 : 380); return d.open; }
function animateDoors(now) {
  for (const d of doors.values()) {
    if (d.anim) { const k = Math.min(1, (now - d.anim.start) / (DOOR_TIME * 1000)); d.t = d.anim.from + (d.anim.to - d.anim.from) * k; if (k >= 1) { d.anim = null; dirty = true; }
      if (d.pair) { const e = (1 - Math.cos(Math.PI * d.t)) / 2; d.pair[0].rotation.y = d.closedAngle - d.side * Math.PI / 2 * e; d.pair[1].rotation.y = d.closedAngle + d.side * Math.PI / 2 * e; }
      else if (d.pivot) d.pivot.rotation.y = doorAngle(d); }
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
    const g0 = fr.a.clone().add(fr.d.clone().multiplyScalar(o.s0)), g1 = fr.a.clone().add(fr.d.clone().multiplyScalar(o.s1)); gaps.push({ c: g0.clone().add(g1).multiplyScalar(0.5), u: fr.d, hu: (o.s1 - o.s0) / 2, level: wallLevel[o.wall] ?? 0 });
  }
  for (const g of gaps) {
    const next = [];
    for (const b of out) {
      const parallel = Math.abs(b.u.dot(g.u)) > 0.9 && (wallLevel[b.tag] ?? 0) === g.level; const rel = g.c.clone().sub(b.c);
      if (!parallel || Math.abs(rel.dot(b.v)) > b.hv + 0.08) { next.push(b); continue; }
      const gs = rel.dot(b.u); const lo = gs - g.hu, hi = gs + g.hu;   // gap interval along the box axis, relative to the box centre
      if (hi <= -b.hu || lo >= b.hu) { next.push(b); continue; }        // no overlap along the wall
      if (lo > -b.hu + 0.02) next.push(obb(b.c.clone().add(b.u.clone().multiplyScalar((-b.hu + lo) / 2)), b.u, (lo + b.hu) / 2, b.hv, b.tag));
      if (hi < b.hu - 0.02) next.push(obb(b.c.clone().add(b.u.clone().multiplyScalar((hi + b.hu) / 2)), b.u, (b.hu - hi) / 2, b.hv, b.tag));   // (a gap only carves walls of its own level)
    }
    out = next;
  }
  // the leaf of an open (or opening) door stands into the room from its hinge
  for (const d of doors.values()) {
    if (d.t <= 0.05 || d.pair) continue;   // two-leaf doors fold back to the jambs: no leaf in the way
    const ang = doorAngle(d) - d.closedAngle; const leafDir = d.fr.d.clone().multiplyScalar(d.dir);
    const rot = new THREE.Vector2(leafDir.x * Math.cos(-ang) - leafDir.y * Math.sin(-ang), leafDir.x * Math.sin(-ang) + leafDir.y * Math.cos(-ang));
    const c = d.hinge.clone().add(rot.clone().multiplyScalar(d.lw / 2)); out.push(obb(c, rot.clone().normalize(), d.lw / 2, 0.03, d.fr.id));
  }
  for (const b of out) { const k = wallLevel[b.tag] ?? 0; b.base = elev(k); b.top = elev(k) + CEIL + 0.03; }   // every box keeps its wall's level band (leaves are tagged 'leaf': see below)
  return out;
}
const FIX_H = { counter: 0.9, island: 0.9, vanity: 0.85, sink: 0.9, stove: 0.9, fridge: 1.8, dishwasher: 0.86, tub: 0.55, shower: 2.0, toilet: 0.75, fireplace: 1.1, washer: 0.9 };
function itemColliders() {   // furniture, fixtures and stair steps as boxes with a base and a top (world y): low enough -> stand on it, else a wall
  const out = []; const byRoom = window.furnishByRoom || {};
  for (const [rid, f] of Object.entries(byRoom)) for (const it of (f.items || [])) {
    const s = it.spec || {}; if (+s.h_m < 0.12 || s.category === 'rug') continue;   // rugs are walkable
    const rot = -THREE.MathUtils.degToRad(+s.rot_deg || 0); const u = new THREE.Vector2(Math.cos(rot), -Math.sin(rot));   // local x after yaw rot_deg (rotation.y = -rot)
    const b = obb(new THREE.Vector2(+s.x || 0, +s.z || 0), u, (+s.w_m || 0.5) / 2, (+s.d_m || 0.5) / 2, 'item'); b.base = elev(roomLevel[rid.split('__').pop()]); b.top = b.base + (+s.h_m || 0.8);
    if (s.category === 'bed') { b.bed = true; b.top = b.base + (it._sleepTop ?? (it.mattress ? +s.h_m + 0.16 : Math.min(+s.h_m || 0.5, 0.55))); }   // a bed is stood on at its duvet, not its headboard (props.js measures it)
    out.push(b);
  }
  for (const fx of layout.fixtures || []) {   // fixtures from the layout (counters, tub...) in case no Furnish instance carries them
    const r = fx.rect || {}; if (fx.type === 'closet_rod') continue;
    const rot = -THREE.MathUtils.degToRad(+r.rot_deg || 0); const u = new THREE.Vector2(Math.cos(rot), -Math.sin(rot));
    const b = obb(new THREE.Vector2(+r.x || 0, +r.z || 0), u, (+r.w || 0.5) / 2, (+r.d || 0.5) / 2, 'fixture'); b.base = elev(fx.level); b.top = b.base + (fx.height_m || FIX_H[fx.type] || 0.8); out.push(b);
  }
  for (const S of STAIRS) for (const st of S.steps) { const b = obb(new THREE.Vector2(st.x, st.z), new THREE.Vector2(1, 0), st.w / 2, st.d / 2, 'stair'); b.base = S.base + (st.base || 0); b.top = S.base + st.top; out.push(b); }

  return out;
}
function insideBox(p, b, m = 0) { const rel = p.clone().sub(b.c); return Math.abs(rel.dot(b.u)) <= b.hu + m && Math.abs(rel.dot(b.v)) <= b.hv + m; }
function groundAt(p, feet, items) {   // the highest surface under p that the feet can reach (step-up), else the highest below
  let g = 0;   // level 0 floor and the ground around the building
  for (const v of LEVELS) if (v.elevation_m > 0 && v.elevation_m <= feet + STEP && onFloor(p, v)) g = Math.max(g, v.elevation_m);
  for (const b of items) if (b.top <= feet + STEP && b.top > g && insideBox(p, b, 0.08)) g = b.top;
  return g;
}
function ceilingAt(p, feet) {   // the underside above the head: the next level's floor, unless the stairwell is open there
  for (const v of LEVELS) if (v.elevation_m > feet + 0.3 && onFloor(p, v)) return v.elevation_m - 0.02;
  const k = levelAt(feet); return (LEVELS.length > 1 && LEVELS.some(v => v.elevation_m > elev(k))) ? Infinity : elev(k) + CEIL;   // top floor: its own ceiling
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
const keys = {}; addEventListener('keydown', e => { keys[e.code] = true; if (e.code === 'KeyE' && enabled()) tryToggle(); if (e.code === 'Space' && enabled()) { e.preventDefault(); document.activeElement?.blur?.(); } }); addEventListener('keyup', e => keys[e.code] = false);
renderer.domElement.addEventListener('click', () => { if (enabled() && document.pointerLockElement) tryToggle(); });
const player = { pos: new THREE.Vector2(camera.position.x, camera.position.z), vel: new THREE.Vector2(), radius: R, eye: EYE, bob: 0, nudge: 0, moving: false, room: null, prompt: null, feet: Math.max(0, camera.position.y - EYE), vy: 0, onGround: true, eyeY: camera.position.y, jumps: 0 };
let lastPos = player.pos.clone(); let wallCols = wallColliders(); let dirty = false;
function enabled() { const b = document.getElementById('bWalk'); return !!(b && b.classList.contains('on')); }
function forward() { const f = new THREE.Vector3(); camera.getWorldDirection(f); return new THREE.Vector2(f.x, f.z).normalize(); }
function wish(k) { const f = (k.KeyW ? 1 : 0) - (k.KeyS ? 1 : 0), s = (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0); if (!f && !s) return new THREE.Vector2(); const fw = forward(); const rt = new THREE.Vector2(-fw.y, fw.x); return fw.multiplyScalar(f).add(rt.multiplyScalar(s)).normalize(); }
function step(dt, k = keys) {
  animateDoors(performance.now()); if (dirty || [...doors.values()].some(d => d.anim)) { wallCols = wallColliders(); dirty = false; }
  const target = wish(k).multiplyScalar(k.ShiftLeft || k.ShiftRight ? RUN : SPEED);
  const a = target.lengthSq() > 0 ? ACCEL : FRICTION; player.vel.lerp(target, 1 - Math.exp(-a * dt));
  const items = itemColliders(); const feet = player.feet;
  // standing on a stair: the walls of the level below inside that stairwell are under you (rooms under a stair keep them)
  const onStair = STAIRS.find(S => player.feet > S.base + 0.1 && inRect(player.pos, S.r, 0.35) && items.some(b => b.tag === 'stair' && Math.abs(b.top - player.feet) < 0.05 && insideBox(player.pos, b, 0.1)));
  // horizontal blockers: walls of the levels the body overlaps; furniture / steps taller than a step-up
  // stair steps only block when far above the feet: the body (radius R) overlaps two or three treads of a steep stair before its
  // centre stands on the first, while the height comes from the step under the centre (groundAt)
  const cols = wallCols.filter(b => feet + STEP < b.top && feet + HEAD > b.base && !(onStair && (wallLevel[b.tag] ?? 0) === onStair.st.from_level && inRect(b.c, onStair.r, 0.4))).concat(items.filter(b => b.top > feet + (b.tag === 'stair' ? STEP + 0.45 : STEP) && b.base < feet + HEAD && !(b.tag === 'stair' && b.base > feet + 1.1)));   // a stair overhead (the next flight up) is not in the way
  const p = player.pos.clone(); let hit = false;
  // per-axis sweep: x, then z, so you slide along walls. Edge guard: on a stair or landing a move that would drop you more than
  // 0.45 m is refused (the open side of a flight), on a floor one that would drop you over 1 m (the stairwell's edge)
  const guard = player.onGround ? (STAIRS.some(S => inRect(player.pos, S.r, 0.3)) && feet > 0.05 + Math.min(...LEVELS.map(v => Math.abs(feet - v.elevation_m))) * 0 && !LEVELS.some(v => Math.abs(feet - v.elevation_m) < 0.03) ? 0.45 : 1.0) : Infinity;
  const tryAxis = (ax, dv) => { const q = p.clone(); q[ax] += dv; let h = resolve(q, cols); if (guard < Infinity && groundAt(q, feet, items) < feet - guard) return true; p.copy(q); return h; };
  hit = tryAxis('x', player.vel.x * dt) || hit;
  hit = tryAxis('y', player.vel.y * dt) || hit;
  // soft world bound: the unit's bounding box plus 2.5 m (balconies/patios are drawn outside the walls)
  const cx = Math.min(Math.max(p.x, UB.minX), UB.maxX), cz = Math.min(Math.max(p.y, UB.minZ), UB.maxZ); if (cx !== p.x || cz !== p.y) { p.set(cx, cz); hit = true; }
  const blocked = hit && p.distanceTo(player.pos.clone().add(player.vel.clone().multiplyScalar(dt))) > 0.004 && player.vel.length() > 0.4;
  if (blocked && player.nudge <= 0) { player.nudge = 0.12; click(140, 0.05); player.vel.multiplyScalar(0.3); }
  player.pos.copy(p); player.moving = player.vel.length() > 0.2;
  // vertical: jump, gravity, land on the highest reachable surface, bump the ceiling
  if ((k.Space) && player.onGround) { player.vy = JUMP; player.onGround = false; player.jumps++; click(300, 0.05); }
  player.vy -= G * dt; let nf = player.feet + player.vy * dt;
  const ground = groundAt(p, Math.max(player.feet, nf), items);
  if (nf <= ground) {   // landing; on a bed you bounce (as in Minecraft): ~70% of the impact back, Space held keeps it going, the head never quite reaches the ceiling
    const impact = -player.vy; const bed = impact > 1.2 && items.find(b => b.bed && Math.abs(b.top - ground) < 0.02 && insideBox(p, b, 0.08));
    const vMax = Math.sqrt(2 * G * Math.max(0.12, ceilingAt(p, ground) - HEAD - ground - 0.03)); const bv = bed ? Math.min(vMax, Math.max(impact * 0.7, k.Space ? JUMP : 0)) : 0;
    nf = ground;
    if (bv > 1.3) { player.vy = bv; player.onGround = false; player.nudge = 0.16; player.bounces = (player.bounces || 0) + 1; boing(bv / vMax); }
    else { const landed = !player.onGround && player.vy < -2; player.vy = 0; player.onGround = true; if (landed) click(180, 0.04); } }
  else player.onGround = nf - ground < 0.02;
  const ceil = ceilingAt(p, player.feet); if (nf + HEAD > ceil) { nf = Math.max(ground, ceil - HEAD); player.vy = Math.min(player.vy, 0); }
  player.feet = nf;
  // eye: follows step-ups smoothly, falls and jumps directly
  const eyeT = player.feet + EYE; player.eyeY = Math.abs(eyeT - player.eyeY) < 0.4 && player.onGround ? player.eyeY + (eyeT - player.eyeY) * (1 - Math.exp(-22 * dt)) : eyeT;
  player.bob += dt * (player.moving ? player.vel.length() * 5.5 : 0); if (!player.moving) player.bob *= 0.9;
  player.nudge = Math.max(0, player.nudge - dt);
  camera.position.x = p.x; camera.position.z = p.y;
  camera.position.y = player.eyeY + (player.moving && player.onGround ? Math.sin(player.bob) * 0.03 : 0) + (player.nudge > 0 ? -player.nudge * 0.15 : 0);
  lastPos.copy(p);
}
function nearestDoor() {
  const fw = forward(); let best = null;
  const lv = levelAt(player.feet);
  for (const d of doors.values()) {
    if ((wallLevel[d.fr.id] ?? 0) !== lv) continue;
    const to = d.centre.clone().sub(player.pos); const dist = to.length(); if (dist > REACH + 0.3) continue;
    const facing = to.clone().normalize().dot(fw); if (facing < 0.25) continue;
    const score = dist - facing * 0.5; if (!best || score < best.score) best = { d, dist, score };
  }
  return best ? best.d : null;
}
function tryToggle() { const d = nearestDoor(); if (d) { toggleDoor(d.id); dirty = true; } }
function roomAt(p) { const lv = levelAt(player.feet); for (const r of layout.rooms) if ((r.level || 0) === lv && pointInPoly(p, r.polygon)) return r; return null; }

// ---------- HUD + feedback ----------
const hud = document.createElement('div'); hud.id = 'walkhud';
hud.style.cssText = 'position:fixed;left:50%;bottom:64px;transform:translateX(-50%);padding:6px 12px;border-radius:8px;background:rgba(10,14,20,.72);color:#e8edf3;font:13px/1.4 -apple-system,Inter,sans-serif;display:none;pointer-events:none;text-align:center;z-index:30';
document.body.appendChild(hud);
let audio = null;
function boing(k = 1) {   // a rising springy note, brighter for a bigger bounce
  try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); const t = audio.currentTime, o = audio.createOscillator(), g = audio.createGain(); o.type = 'sine';
    o.frequency.setValueAtTime(150 + 60 * k, t); o.frequency.exponentialRampToValueAtTime(380 + 180 * k, t + 0.14); g.gain.setValueAtTime(0.09, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.22); o.connect(g).connect(audio.destination); o.start(t); o.stop(t + 0.24); } catch (e) {}
}
function click(freq = 440, dur = 0.04) { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); const o = audio.createOscillator(), g = audio.createGain(); o.frequency.value = freq; o.type = 'triangle'; g.gain.setValueAtTime(0.08, audio.currentTime); g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + dur); o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + dur); } catch (e) { /* no audio in headless */ } }

// ---------- main loop: runs after the builder's loop in the same frame; the builder's own bounded movement is overridden ----------
let wasEnabled = false; let lastT = performance.now();
(function loop() {
  requestAnimationFrame(loop); const now = performance.now(); const dt = Math.min((now - lastT) / 1000, 0.05); lastT = now;
  const on = enabled();
  if (on && !wasEnabled) { player.pos.set(camera.position.x, camera.position.z); player.vel.set(0, 0); player.feet = Math.max(0, camera.position.y - EYE); player.vy = 0; player.eyeY = camera.position.y; lastPos.copy(player.pos); hud.style.display = 'block'; }
  if (!on && wasEnabled) hud.style.display = 'none';
  wasEnabled = on; if (!on) return;
  animateDoors(now); if (dirty || [...doors.values()].some(d => d.anim)) { wallCols = wallColliders(); dirty = false; }
  if (!window.walk?.manual) { camera.position.x = lastPos.x; camera.position.z = lastPos.y; step(dt); }   // undo the builder's move, then ours
  const r = roomAt(player.pos); const d = nearestDoor(); player.room = r ? r.name : null; player.prompt = d ? `E · ${d.open ? 'close' : 'open'} the ${d.closet ? 'closet' : 'door'}` : null;
  const lvName = LEVELS.length > 1 ? (LEVELS.find(v => v.id === levelAt(player.feet)) || {}).name : null;
  hud.innerHTML = `${lvName ? `<span style="color:#9aa6b5">${lvName}</span> &nbsp;` : ''}${r ? `<b>${r.name}</b>` : ''}${d ? ` &nbsp;·&nbsp; <span style="color:#9fc6ff">${player.prompt}</span>` : ''}` || 'walk: WASD · Shift run · Space jump · E doors';
})();

// ---------- public API (agent/render workers, headless tests) ----------
window.walk = {
  player, doors, layout,
  manual: false,                                  // when true the loop does not move the player; use step() yourself
  setEnabled: (on) => on ? window.setWalk?.() : window.setDoll?.(),
  step: (dt, k) => { step(dt, k || {}); lastPos.copy(player.pos); },   // single physics step for tests (velocity persists between calls)
  teleport: (x, z, feet = player.feet) => { player.pos.set(x, z); player.vel.set(0, 0); player.feet = feet; player.vy = 0; player.eyeY = feet + EYE; lastPos.copy(player.pos); camera.position.set(x, feet + EYE, z); },
  probe: (x, z, feet = player.feet) => { const p = new THREE.Vector2(x, z); return { ground: groundAt(p, feet, itemColliders()), ceiling: ceilingAt(p, feet), floors: LEVELS.map(v => [v.id, onFloor(p, v)]) }; },
  levelAt: () => levelAt(player.feet), stairs: () => STAIRS.map(S => ({ rect: S.r, climb: S.st.climb, steps: S.steps.length })),
  look: (yawDeg, pitch = -0.05) => { const y = THREE.MathUtils.degToRad(yawDeg); camera.rotation.set(0, 0, 0); camera.lookAt(camera.position.x + Math.sin(y), camera.position.y + pitch, camera.position.z + Math.cos(y)); },
  lookAt: (x, z) => { camera.rotation.set(0, 0, 0); camera.lookAt(x, EYE - 0.1, z); },
  toggleDoor, nearestDoor: () => nearestDoor()?.id || null, doorList: () => [...doors.values()].map(d => ({ id: d.id, open: d.open, centre: [d.centre.x, d.centre.y], wall: d.fr.id, closet: d.closet })),
  colliders: () => wallCols.concat(itemColliders()).length,
  near: (x, z, r = 1.0) => wallCols.concat(itemColliders()).filter(b => { const rel = new THREE.Vector2(x, z).sub(b.c); return Math.abs(rel.dot(b.u)) < b.hu + r && Math.abs(rel.dot(b.v)) < b.hv + r; }).map(b => ({ tag: b.tag, c: [+b.c.x.toFixed(2), +b.c.y.toFixed(2)], hu: +b.hu.toFixed(2), hv: +b.hv.toFixed(2), u: [+b.u.x.toFixed(2), +b.u.y.toFixed(2)] })), roomAt: (x, z) => roomAt(new THREE.Vector2(x, z))?.name || null,
};
