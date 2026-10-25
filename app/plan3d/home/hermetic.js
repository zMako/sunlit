// Make the apartment read as one sealed volume once the city is outside the windows.
//  - exterior doors (on the unit's perimeter walls): entrance = solid wood slab, balcony/patio = aluminium-framed glass;
//    both closed and locked in walk view (they lead out of the unit)
//  - seal: the plan rasterised at 5 cm (rooms + wall bodies), closed by 30 cm (dilate, erode) and hole-filled, so cracks
//    between walls, floors and corners disappear while the outline stays put; from it a continuous floor slab just under
//    the room floors (holes show floor, not the street), a ceiling slab just above the ceilings, and an outer skin along
//    the outline with gaps exactly at windows and exterior doors. Ceiling and skin are walk-only (the dollhouse is cut open).
import * as THREE from 'three';

const CELL = 0.05, CLOSE = 6, LIVE = ['living', 'dining', 'bedroom', 'kitchen', 'office', 'den', 'studio'];

function frame(w) { const a = new THREE.Vector2(...w.a), b = new THREE.Vector2(...w.b), d = b.clone().sub(a); const len = d.length(); d.normalize(); return { a, b, d, n: new THREE.Vector2(-d.y, d.x), len, t: w.thickness_m || 0.15, angle: -Math.atan2(d.y, d.x) }; }
function inPoly(x, z, P) { let k = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const [xi, zi] = P[i], [xj, zj] = P[j]; if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi) k = !k; } return k; }
const centroid = P => P.reduce((s, p) => [s[0] + p[0] / P.length, s[1] + p[1] / P.length], [0, 0]);

/** before the Apartment is built: style exterior doors (entrance wood slab, balcony glass) and return them.
 *  Exterior = one side of the door lands outside the sealed footprint (room-polygon gaps do not count). Balcony vs entrance:
 *  a balcony door sits on a facade line that also carries windows (or is wide / double / next to a balcony room); an entrance
 *  sits on a corridor line without windows. Every unit has an entrance: failing the pattern, the least-windowed one is it. */
export function classifyExteriorDoors(layout) {
  const F = footprint(layout), walls = new Map(layout.walls.map(w => [w.id, w])), out = [];
  const inside = (x, z) => { const i = Math.floor((x - F.x0) / CELL), j = Math.floor((z - F.z0) / CELL); return i >= 0 && j >= 0 && i < F.nx && j < F.nz && F.S[j * F.nx + i] === 1; };
  const windowOnLine = f => {   // window width on this wall's line (same or collinear walls overlapping it)
    let sum = 0; for (const o of layout.openings) { if (o.type !== 'window') continue; const w = walls.get(o.wall); if (!w) continue; const g = frame(w);
      if (Math.abs(g.d.x * f.d.y - g.d.y * f.d.x) > 0.05) continue; const off = (g.a.x - f.a.x) * f.n.x + (g.a.y - f.a.y) * f.n.y; if (Math.abs(off) > 0.3) continue;
      const m = g.a.clone().add(g.d.clone().multiplyScalar((o.s0 + o.s1) / 2)), s = (m.x - f.a.x) * f.d.x + (m.y - f.a.y) * f.d.y; if (s > -1.5 && s < f.len + 1.5) sum += o.s1 - o.s0; }
    return sum; };
  for (const o of layout.openings) {
    if (o.type !== 'door') continue; const w = walls.get(o.wall); if (!w) continue;
    const f = frame(w), mid = f.a.clone().add(f.d.clone().multiplyScalar((o.s0 + o.s1) / 2)), probe = sg => mid.clone().add(f.n.clone().multiplyScalar(sg * (f.t / 2 + 0.35)));
    const pa = probe(1), pb = probe(-1), ia = inside(pa.x, pa.y), ib = inside(pb.x, pb.y); if (ia === ib) continue;
    const pin = ia ? pa : pb, room = layout.rooms.find(r => inPoly(pin.x, pin.y, r.polygon)) || null;
    const toOutdoor = layout.rooms.some(r => /balcony|patio|deck|terrace/i.test(`${r.type} ${r.name}`) && r !== room && r.polygon.some(p => Math.hypot(p[0] - mid.x, p[1] - mid.y) < 3));
    const nOut = (ia ? pb : pa).clone().sub(mid).normalize(), wide = (o.s1 - o.s0) > 1.25 || (o.leaves || 1) >= 2;
    // facade score: windows that look the same way as this door, by width and closeness (balcony doors open onto the facade)
    let facade = windowOnLine(f);
    for (const wo of layout.openings) { if (wo.type !== 'window') continue; const ww = walls.get(wo.wall); if (!ww) continue; const g = frame(ww);
      const wm = g.a.clone().add(g.d.clone().multiplyScalar((wo.s0 + wo.s1) / 2)), q1 = wm.clone().add(g.n.clone().multiplyScalar(g.t / 2 + 0.35)), q2 = wm.clone().sub(g.n.clone().multiplyScalar(g.t / 2 + 0.35));
      const o1 = inside(q1.x, q1.y), o2 = inside(q2.x, q2.y); if (o1 === o2) continue; const wn = (o1 ? q2 : q1).clone().sub(wm).normalize();
      facade += (wo.s1 - wo.s0) * Math.max(0, wn.dot(nOut)) * Math.exp(-wm.distanceTo(mid) / 5); }
    out.push({ o, facade, forced: toOutdoor || wide, room: room?.name });
  }
  // exactly one entrance: the exterior door facing furthest from the windows (ties: the one opening from an entry or hall);
  // every other exterior door opens onto a balcony or patio. A lone exterior door is the entrance unless it plainly faces windows.
  const entryish = d => /entry|hall|foyer|corridor/i.test(d.room || '') ? 0 : 1;
  const ent = out.filter(d => !d.forced).sort((p, q) => p.facade - q.facade || entryish(p) - entryish(q))[0];
  for (const d of out) d.kind = d === ent && !(out.length === 1 && d.facade > 2.5) ? 'entrance' : 'balcony';
  layout._exteriorDoors = out.map(d => ({ id: d.o.id, kind: d.kind, facade: +d.facade.toFixed(2), room: d.room }));
  for (const d of out) { d.o.style = d.kind === 'balcony' ? 'glass' : 'wood'; d.o.exterior_kind = d.kind; }
  return out.map(d => d.o);
}

/** after build: entrance hardware, doors shut; returns the opening ids to lock in walk view */
export function dressExteriorDoors(apt, doors) {
  const steel = apt.lib.plain('steel'), ids = new Set(doors.map(o => o.id));
  apt.group.traverse(g => {
    if (!g.userData || g.userData.kind !== 'door' || !ids.has(g.userData.opening)) return;
    const o = doors.find(d => d.id === g.userData.opening), w = apt.walls.get(o.wall), f = frame(w);
    for (const pv of g.userData.pair || [g]) pv.rotation.y = f.angle;   // fully shut (the builder leaves interior doors ajar)
    if (o.exterior_kind !== 'entrance') return;
    const leaf = g.children.find(c => c.isGroup); if (!leaf) return; const lh = (o.height_m ?? 2.03) - 0.03;
    const hx = leaf.position.x > 0 ? 1 : -1, lw = Math.abs(leaf.position.x) * 2;
    for (const zs of [1, -1]) {   // peephole and deadbolt read as a front door
      const eye = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.012, 16), steel); eye.rotation.x = Math.PI / 2; eye.position.set(0, 1.55 - lh / 2, zs * 0.026); leaf.add(eye);
      const bolt = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.014, 20), steel); bolt.rotation.x = Math.PI / 2; bolt.position.set(hx * (lw / 2 - 0.08), 1.18 - lh / 2, zs * 0.027); leaf.add(bolt);
    }
  });
  return [...ids];
}

/** the plan's sealed footprint: rooms + wall bodies at 5 cm, closed by 30 cm, holes filled (memoised on the layout) */
export function footprint(layout) {
  if (layout._footprint) return layout._footprint; const walls = layout.walls;
  let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
  for (const w of walls) for (const p of [w.a, w.b]) { x0 = Math.min(x0, p[0]); z0 = Math.min(z0, p[1]); x1 = Math.max(x1, p[0]); z1 = Math.max(z1, p[1]); }
  x0 -= 1; z0 -= 1; x1 += 1; z1 += 1;
  const nx = Math.ceil((x1 - x0) / CELL), nz = Math.ceil((z1 - z0) / CELL), A = new Uint8Array(nx * nz);
  const cx = i => x0 + (i + 0.5) * CELL, cz = j => z0 + (j + 0.5) * CELL, idx = (i, j) => j * nx + i;
  for (const r of layout.rooms) {   // rooms
    const P = r.polygon, xs = P.map(p => p[0]), zs = P.map(p => p[1]);
    const i0 = Math.max(0, Math.floor((Math.min(...xs) - x0) / CELL)), i1 = Math.min(nx - 1, Math.ceil((Math.max(...xs) - x0) / CELL));
    const j0 = Math.max(0, Math.floor((Math.min(...zs) - z0) / CELL)), j1 = Math.min(nz - 1, Math.ceil((Math.max(...zs) - z0) / CELL));
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) if (inPoly(cx(i), cz(j), P)) A[idx(i, j)] = 1;
  }
  for (const w of walls) {   // wall bodies
    const f = frame(w), h = f.t / 2 + 0.02, pad = h + 0.1;
    const i0 = Math.max(0, Math.floor((Math.min(w.a[0], w.b[0]) - pad - x0) / CELL)), i1 = Math.min(nx - 1, Math.ceil((Math.max(w.a[0], w.b[0]) + pad - x0) / CELL));
    const j0 = Math.max(0, Math.floor((Math.min(w.a[1], w.b[1]) - pad - z0) / CELL)), j1 = Math.min(nz - 1, Math.ceil((Math.max(w.a[1], w.b[1]) + pad - z0) / CELL));
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) { const px = cx(i) - f.a.x, pz = cz(j) - f.a.y, s = px * f.d.x + pz * f.d.y, q = px * f.n.x + pz * f.n.y; if (s >= -h && s <= f.len + h && Math.abs(q) <= h) A[idx(i, j)] = 1; }
  }
  const D = morph(morph(A, nx, nz, CLOSE, 1), nx, nz, CLOSE, 0);   // closing: cracks under ~60 cm vanish, the outline stays
  const out = new Uint8Array(nx * nz), st = [];   // hole fill: whatever the outside cannot reach is inside
  for (let i = 0; i < nx; i++) st.push(idx(i, 0), idx(i, nz - 1)); for (let j = 0; j < nz; j++) st.push(idx(0, j), idx(nx - 1, j));
  while (st.length) { const c = st.pop(); if (out[c] || D[c]) continue; out[c] = 1; const i = c % nx, j = (c - i) / nx; if (i > 0) st.push(c - 1); if (i < nx - 1) st.push(c + 1); if (j > 0) st.push(c - nx); if (j < nz - 1) st.push(c + nx); }
  const S = new Uint8Array(nx * nz); for (let c = 0; c < S.length; c++) S[c] = out[c] ? 0 : 1;
  return (layout._footprint = { S, nx, nz, x0, z0 });
}

/** the seal: floor slab (always), ceiling slab and outer skin (walk view) */
export function sealApartment(apt, layout) {
  if (layout.levels && layout.levels.length > 1) return null;   // townhouses: per-level seals not done yet
  const ceil = apt.ceil, { S, nx, nz, x0, z0 } = footprint(layout);

  // materials: the largest room's floor, the ceiling's paint, the walls' paint (double-sided for the skin)
  const big = [...layout.rooms].sort((a, b) => (b.area_m2 || 0) - (a.area_m2 || 0))[0], rm = big && apt.roomMeshes[big.id];
  const floorMat = rm?.floor?.material || new THREE.MeshStandardMaterial({ color: 0xb3804d, roughness: 0.6 });
  const ceilMat = apt.ceilingMeshes.find(m => m.material && !m.material.emissive?.getHex())?.material || new THREE.MeshStandardMaterial({ color: 0xfafaf7, roughness: 0.9 });
  const wallMat = (apt.wallMeshes[0]?.material || new THREE.MeshStandardMaterial({ color: 0xece8e1, roughness: 0.92 })).clone(); wallMat.side = THREE.DoubleSide;
  const group = new THREE.Group(); group.name = 'seal';
  const floor = new THREE.Mesh(rects(S, nx, nz, x0, z0, -0.012, 1), floorMat); floor.receiveShadow = true; floor.userData.kind = 'seal';
  const ceiling = new THREE.Mesh(rects(S, nx, nz, x0, z0, ceil + 0.012, -1), ceilMat); ceiling.userData.kind = 'seal';
  const skin = new THREE.Mesh(skinGeo(S, nx, nz, x0, z0, ceil, layout, apt), wallMat); skin.castShadow = true; skin.receiveShadow = true; skin.userData.kind = 'seal';
  group.add(floor, ceiling, skin); apt.group.add(group);
  const setWalk = on => { ceiling.visible = on; skin.visible = on; }; setWalk(false);
  return { group, setWalk, cells: S.reduce((s, v) => s + v, 0) };
}

function morph(A, nx, nz, r, dilate) {   // square-kernel dilate (1) or erode (0), separable
  const T = new Uint8Array(A.length), O = new Uint8Array(A.length), want = dilate ? 1 : 0;
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) { let v = 1 - want; for (let k = Math.max(0, i - r); k <= Math.min(nx - 1, i + r); k++) if (A[j * nx + k] === want) { v = want; break; } T[j * nx + i] = v; }
  for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) { let v = 1 - want; for (let k = Math.max(0, j - r); k <= Math.min(nz - 1, j + r); k++) if (T[k * nx + i] === want) { v = want; break; } O[j * nx + i] = v; }
  return O;
}
function rects(S, nx, nz, x0, z0, y, up) {   // greedy rectangles over the filled cells, one quad each, metric UVs
  const used = new Uint8Array(S.length), pos = [], uv = [], nor = [], ind = [];
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    if (!S[j * nx + i] || used[j * nx + i]) continue;
    let w = 1; while (i + w < nx && S[j * nx + i + w] && !used[j * nx + i + w]) w++;
    let h = 1; grow: while (j + h < nz) { for (let k = 0; k < w; k++) if (!S[(j + h) * nx + i + k] || used[(j + h) * nx + i + k]) break grow; h++; }
    for (let jj = 0; jj < h; jj++) for (let k = 0; k < w; k++) used[(j + jj) * nx + i + k] = 1;
    const ax = x0 + i * CELL, az = z0 + j * CELL, bx = ax + w * CELL, bz = az + h * CELL, b = pos.length / 3;
    pos.push(ax, y, az, bx, y, az, bx, y, bz, ax, y, bz); uv.push(ax, -az, bx, -az, bx, -bz, ax, -bz); for (let k = 0; k < 4; k++) nor.push(0, up, 0);
    if (up > 0) ind.push(b, b + 2, b + 1, b, b + 3, b + 2); else ind.push(b, b + 1, b + 2, b, b + 2, b + 3);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setIndex(ind); return g;
}
function skinGeo(S, nx, nz, x0, z0, ceil, layout, apt) {
  // exterior openings in plan: window = gap between sill and head, exterior door = gap below the head
  const walls = new Map(layout.walls.map(w => [w.id, w])), ops = [];
  for (const o of layout.openings) { const w = walls.get(o.wall); if (!w || !w.exterior || !(o.type === 'window' || o.type === 'door' || o.type === 'opening')) continue;
    const f = frame(w), sill = o.type === 'window' ? (o.sill_m ?? 0.9) : 0, head = o.type === 'window' ? sill + (o.height_m ?? 1.3) : (o.height_m ?? 2.03);
    ops.push({ f, s0: o.s0 - 0.04, s1: o.s1 + 0.04, sill: sill + 0.02, head: head - 0.02 }); }
  const gapAt = (x, z) => { for (const o of ops) { const px = x - o.f.a.x, pz = z - o.f.a.y, s = px * o.f.d.x + pz * o.f.d.y, q = px * o.f.n.x + pz * o.f.n.y; if (s >= o.s0 && s <= o.s1 && Math.abs(q) <= o.f.t / 2 + 0.3) return o; } return null; };
  const pos = [], ind = [], eps = 0.012, y0 = -0.02, y1 = ceil + 0.02;
  const quad = (ax, az, bx, bz, ya, yb) => { if (yb - ya < 0.01) return; const b = pos.length / 3; pos.push(ax, ya, az, bx, ya, bz, bx, yb, bz, ax, yb, az); ind.push(b, b + 1, b + 2, b, b + 2, b + 3); };
  // boundary edges of the filled region, merged into runs with the same opening; offset a hair outward so they never z-fight the walls
  const runs = new Map();
  const edge = (key, line, t, o, seg) => { const r = runs.get(key) || []; r.push({ line, t, o, seg }); runs.set(key, r); };
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    if (!S[j * nx + i]) continue; const x = x0 + i * CELL, z = z0 + j * CELL;
    if (j === 0 || !S[(j - 1) * nx + i]) edge(`zN${j}`, z - eps, i, gapAt(x + CELL / 2, z), 'x');
    if (j === nz - 1 || !S[(j + 1) * nx + i]) edge(`zS${j}`, z + CELL + eps, i, gapAt(x + CELL / 2, z + CELL), 'x');
    if (i === 0 || !S[j * nx + i - 1]) edge(`xW${i}`, x - eps, j, gapAt(x, z + CELL / 2), 'z');
    if (i === nx - 1 || !S[j * nx + i + 1]) edge(`xE${i}`, x + CELL + eps, j, gapAt(x + CELL, z + CELL / 2), 'z');
  }
  for (const list of runs.values()) {
    list.sort((p, q) => p.t - q.t);
    for (let k = 0; k < list.length;) {
      let m = k; while (m + 1 < list.length && list[m + 1].t === list[m].t + 1 && list[m + 1].o === list[k].o) m++;
      const e = list[k], a = e.t * CELL, b = (list[m].t + 1) * CELL, o = e.o;
      const put = (ya, yb) => e.seg === 'x' ? quad(x0 + a, e.line, x0 + b, e.line, ya, yb) : quad(e.line, z0 + a, e.line, z0 + b, ya, yb);
      if (!o) put(y0, y1); else { if (o.sill > 0.05) put(y0, o.sill); put(o.head, y1); }
      k = m + 1;
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  const uv = []; for (let k = 0; k < pos.length; k += 3) uv.push(pos[k] + pos[k + 2], pos[k + 1]);   // metric-ish: along the wall, up
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); g.setIndex(ind); g.computeVertexNormals(); return g;
}
