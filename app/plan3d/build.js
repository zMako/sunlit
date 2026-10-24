// Procedural apartment from a layout JSON (see LAYOUT_CONTRACT.md): walls with openings, doors, windows, floors,
// ceilings, baseboards, parametric fixtures, CC0 PBR materials with metric UVs, physically based lighting.
import * as THREE from 'three';

export const DEFAULTS = {
  wood_floor: { color: 0xb3804d, roughness: 0.55, metalness: 0 },
  tile: { color: 0xdcd8d0, roughness: 0.25, metalness: 0 },
  carpet: { color: 0xb9b2a4, roughness: 1.0, metalness: 0 },
  paint: { color: 0xf1eee6, roughness: 0.92, metalness: 0 },
  paint_white: { color: 0xf7f7f4, roughness: 0.9, metalness: 0 },
  stone: { color: 0x3b3b3d, roughness: 0.3, metalness: 0 },
  laminate: { color: 0xe8e4dc, roughness: 0.35, metalness: 0 },
  steel: { color: 0xa6a8ab, roughness: 0.32, metalness: 0.85 },
  dark_glass: { color: 0x14161a, roughness: 0.12, metalness: 0.4 },
  porcelain: { color: 0xf6f6f4, roughness: 0.15, metalness: 0 },
  wood_trim: { color: 0xf4f2ee, roughness: 0.7, metalness: 0 },
};
// which default a material slot falls back to
const SLOT_DEFAULT = { floor: 'wood_floor', wall: 'paint', ceiling: 'paint_white', door: 'paint_white', cabinet: 'paint_white', counter: 'stone', baseboard: 'paint_white', trim: 'wood_trim' };
const ROOM_FLOOR_DEFAULT = { kitchen: 'tile', bathroom: 'tile', closet: 'wood_floor' };
// metres covered by one texture tile per library category (ambientCG/Poly Haven 1K textures are mostly 1-2 m squares)
const CAT_SIZE = { wood_floor: 2.0, tile: 1.0, plaster: 2.0, paint: 2.0, concrete: 2.0, laminate: 1.0, stone: 1.0, brick: 1.0, fabric: 0.6, metal: 1.0, carpet: 1.0 };
const CAT_ROUGH = { wood_floor: 0.55, tile: 0.25, plaster: 0.95, paint: 0.9, concrete: 0.9, laminate: 0.4, stone: 0.35, brick: 0.9, fabric: 1.0, metal: 0.4, carpet: 1.0 };

export class MaterialLib {
  constructor(base = '../furnish/materials/') { this.base = base; this.index = null; this.cache = new Map(); this.tex = new THREE.TextureLoader(); }
  async load() {
    try { const r = await fetch(this.base + 'index.json'); if (r.ok) { const j = await r.json(); this.index = new Map((Array.isArray(j) ? j : j.items || []).map(m => [m.id, m])); } } catch (e) { this.index = null; }
    return this;
  }
  _tex(url, srgb) {
    const t = this.tex.load(url); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 16; if (srgb) t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  /** id from the layout; slot = floor|wall|ceiling|...; returns MeshStandardMaterial with textures in metres (1 unit = 1 m, scaled by entry.size_m). */
  get(id, slot = 'wall', roomType = null) {
    const key = `${id}|${slot}`; if (this.cache.has(key)) return this.cache.get(key);
    const entry = id && this.index ? this.index.get(id) : null; let m;
    if (entry) {
      const dir = this.base + entry.id + '/'; const size = entry.size_m || CAT_SIZE[entry.category] || 1.0;
      const hasMap = (k) => !entry.maps || entry.maps.includes(k);
      m = new THREE.MeshStandardMaterial({ roughness: CAT_ROUGH[entry.category] ?? 0.8, metalness: entry.category === 'metal' ? 0.8 : 0 });
      m.map = this._tex(dir + 'color.jpg', true); m.map.repeat.set(1 / size, 1 / size);
      if (entry.has_normal !== false && hasMap('normal')) { m.normalMap = this._tex(dir + 'normal.jpg', false); m.normalMap.repeat.set(1 / size, 1 / size); m.normalScale.set(0.5, 0.5); }
      if (entry.has_roughness !== false && hasMap('roughness')) { m.roughnessMap = this._tex(dir + 'roughness.jpg', false); m.roughnessMap.repeat.set(1 / size, 1 / size); m.roughness = 1.0; }
      if (slot === 'floor' && entry.category === 'wood_floor') m.envMapIntensity = 0.6;
      m.userData.materialId = entry.id; m.userData.category = entry.category;
    } else {
      const dk = (slot === 'floor' && roomType && ROOM_FLOOR_DEFAULT[roomType]) || (id && DEFAULTS[id] ? id : null) || SLOT_DEFAULT[slot] || 'paint';
      m = new THREE.MeshStandardMaterial(DEFAULTS[dk]); m.userData.materialId = `default:${dk}`;
      const pt = proceduralTexture(dk); if (pt) { m.map = pt.map; m.color.set(0xffffff); if (pt.rough) { m.roughnessMap = pt.rough; m.roughness = 1; } if (pt.normal) { m.normalMap = pt.normal; m.normalScale.set(0.35, 0.35); } }
    }
    this.cache.set(key, m); return m;
  }
  plain(kind) { const key = `plain|${kind}`; if (!this.cache.has(key)) { const m = new THREE.MeshStandardMaterial(DEFAULTS[kind]); this.cache.set(key, m); } return this.cache.get(key); }
}

// BoxGeometry has 6 faces x 4 verts in the order +x,-x,+y,-y,+z,-z with uv 0..1; rescale each face to metres.
export function metricBox(w, h, d, uOff = 0, vOff = 0) {
  const g = new THREE.BoxGeometry(w, h, d); const uv = g.attributes.uv; const sizes = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) { const i = f * 4 + k; const big = f >= 4; uv.setXY(i, uv.getX(i) * sizes[f][0] + (big ? uOff : 0), uv.getY(i) * sizes[f][1] + (big ? vOff : 0)); }
  uv.needsUpdate = true; return g;
}
function hash01(str) { let h = 2166136261; for (let i = 0; i < String(str).length; i++) { h ^= String(str).charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 10007) / 10007; }

const v2 = (a) => new THREE.Vector2(a[0], a[1]);

export class Apartment {
  constructor(layout, lib) {
    this.layout = layout; this.lib = lib; this.group = new THREE.Group(); this.group.name = 'apartment';
    this.ceil = layout.ceiling_m || 2.6; this.roomMeshes = {}; this.wallMeshes = []; this.ceilingMeshes = []; this.labels = []; this.lights = [];
    this.bounds = new THREE.Box3(); this.walls = new Map(layout.walls.map(w => [w.id, w]));
    this.build();
  }
  build() {
    const L = this.layout;
    for (const w of L.walls) this.buildWall(w, L.openings.filter(o => o.wall === w.id));
    for (const r of L.rooms) this.buildRoom(r);
    for (const f of L.fixtures || []) this.buildFixture(f);
    this.bounds.setFromObject(this.group);
  }

  // ---------- walls ----------
  wallFrame(w) {
    const a = v2(w.a), b = v2(w.b), d = b.clone().sub(a); const len = d.length(); d.normalize();
    const n = new THREE.Vector2(-d.y, d.x);   // "in" side of the wall (see doors)
    return { a, b, d, n, len, angle: -Math.atan2(d.y, d.x), t: w.thickness_m || 0.15 };
  }
  placeAlong(fr, s, y, h, lenPiece, t, offsetN = 0, uOff = 0, vOff = 0) {
    const c = fr.a.clone().add(fr.d.clone().multiplyScalar(s)).add(fr.n.clone().multiplyScalar(offsetN));
    const g = metricBox(lenPiece, h, t, uOff, vOff); const m = new THREE.Mesh(g, this.wallMat); m.position.set(c.x, y + h / 2, c.y); m.rotation.y = fr.angle; m.castShadow = m.receiveShadow = true; return m;
  }
  buildWall(w, openings) {
    const fr = this.wallFrame(w); const H = this.ceil; const t = fr.t; this.wallMat = this.lib.get((this.layout.materials || {}).wall_default || null, 'wall');
    const ops = openings.slice().sort((p, q) => p.s0 - q.s0); let s = -t / 2;   // extend into the corner so walls meet
    const pieces = [];
    for (const o of ops) {
      const s0 = Math.max(o.s0, s), s1 = Math.min(o.s1, fr.len + t / 2);
      if (s0 > s + 1e-3) pieces.push({ s, len: s0 - s, y: 0, h: H });
      const oh = o.type === 'window' ? (o.sill_m ?? 0.9) + (o.height_m ?? 1.3) : (o.height_m ?? 2.03);
      if (o.type === 'window' && (o.sill_m ?? 0.9) > 0.02) pieces.push({ s: s0, len: s1 - s0, y: 0, h: o.sill_m ?? 0.9 });
      if (oh < H - 0.02) pieces.push({ s: s0, len: s1 - s0, y: oh, h: H - oh });
      s = s1;
    }
    if (fr.len + t / 2 > s + 1e-3) pieces.push({ s, len: fr.len + t / 2 - s, y: 0, h: H });
    const wallOff = hash01(w.id) * 3.1;   // per-wall texture phase, so neighbouring walls never share a visible repeat
    for (const p of pieces) { const m = this.placeAlong(fr, p.s + p.len / 2, p.y, p.h, p.len, t, 0, p.s + wallOff, p.y); m.userData = { kind: 'wall', wall: w.id, exterior: !!w.exterior, mid: m.position.clone() }; this.group.add(m); this.wallMeshes.push(m); }
    for (const o of ops) { if (o.type === 'window') this.buildWindow(fr, o); else if (o.type === 'door' || o.type === 'closet_door') this.buildDoor(fr, o); else this.buildOpeningTrim(fr, o); }
  }
  buildOpeningTrim(fr, o) {   // cased opening: thin jambs
    const trim = this.lib.get(null, 'trim'); const h = o.height_m ?? 2.2; const t = fr.t + 0.02;
    for (const s of [o.s0 + 0.03, o.s1 - 0.03]) { const m = new THREE.Mesh(metricBox(0.06, h, t), trim); const c = fr.a.clone().add(fr.d.clone().multiplyScalar(s)); m.position.set(c.x, h / 2, c.y); m.rotation.y = fr.angle; this.group.add(m); }
  }
  buildDoor(fr, o) {
    const trim = this.lib.get((this.layout.materials || {}).door || null, 'door'); const h = o.height_m ?? 2.03; const w = o.s1 - o.s0; const t = fr.t + 0.02;
    const jamb = (s) => { const m = new THREE.Mesh(metricBox(0.05, h + 0.05, t), trim); const c = fr.a.clone().add(fr.d.clone().multiplyScalar(s)); m.position.set(c.x, (h + 0.05) / 2, c.y); m.rotation.y = fr.angle; m.castShadow = true; this.group.add(m); };
    jamb(o.s0 + 0.025); jamb(o.s1 - 0.025);
    const head = new THREE.Mesh(metricBox(w, 0.06, t), trim); const cm = fr.a.clone().add(fr.d.clone().multiplyScalar((o.s0 + o.s1) / 2)); head.position.set(cm.x, h + 0.03, cm.y); head.rotation.y = fr.angle; this.group.add(head);
    // leaf: hinge at the left (s0) or right (s1) end, opening to the 'in' side (+n) or 'out' side (-n), ajar
    const sw = o.swing || 'in_left'; const hingeS = sw.endsWith('left') ? o.s0 + 0.02 : o.s1 - 0.02; const side = sw.startsWith('out') ? -1 : 1; const dir = sw.endsWith('left') ? 1 : -1;
    const pivot = new THREE.Group(); const hc = fr.a.clone().add(fr.d.clone().multiplyScalar(hingeS)); pivot.position.set(hc.x, 0, hc.y); pivot.rotation.y = fr.angle;
    const lw = w - 0.05, lh = h - 0.03; const leafMat = this.lib.plain('wood_trim');
    const leaf = new THREE.Mesh(metricBox(lw, lh, 0.04), leafMat); leaf.position.set(dir * lw / 2, lh / 2, 0); leaf.castShadow = true; leaf.receiveShadow = true;
    for (const [py, ph] of [[0.62, 0.72], [0.28, 0.42]]) for (const zs of [1, -1]) {   // two recessed panels per face
      const panel = new THREE.Mesh(metricBox(lw - 0.22, lh * ph - 0.12, 0.012), leafMat); panel.position.set(0, -lh / 2 + lh * py, zs * 0.016); leaf.add(panel);
      const inset = new THREE.Mesh(metricBox(lw - 0.3, lh * ph - 0.2, 0.004), new THREE.MeshStandardMaterial({ color: 0xe3e0da, roughness: 0.75 })); inset.position.set(0, -lh / 2 + lh * py, zs * 0.024); leaf.add(inset);
    }
    for (const zs of [1, -1]) { const knob = new THREE.Mesh(new THREE.SphereGeometry(0.028, 16, 12), this.lib.plain('steel')); knob.position.set(dir * (lw - 0.1), 1.0 - lh / 2, zs * 0.05); leaf.add(knob); }
    pivot.add(leaf); pivot.rotation.y += -dir * side * THREE.MathUtils.degToRad(o.type === 'closet_door' ? 0 : 9);   // nearly closed: reads as a door in its frame
    pivot.userData = { kind: 'door', opening: o.id }; this.group.add(pivot);
  }
  buildWindow(fr, o) {
    const sill = o.sill_m ?? 0.9, h = o.height_m ?? 1.3, w = o.s1 - o.s0, t = fr.t; const trim = this.lib.get(null, 'trim'); const cm = fr.a.clone().add(fr.d.clone().multiplyScalar((o.s0 + o.s1) / 2));
    const frame = new THREE.Group(); frame.position.set(cm.x, 0, cm.y); frame.rotation.y = fr.angle;
    const bar = (len, hh, x, y) => { const m = new THREE.Mesh(metricBox(len, hh, t * 0.5), trim); m.position.set(x, y, 0); m.castShadow = true; frame.add(m); };
    bar(w, 0.06, 0, sill + 0.03); bar(w, 0.06, 0, sill + h - 0.03); bar(0.06, h, -w / 2 + 0.03, sill + h / 2); bar(0.06, h, w / 2 - 0.03, sill + h / 2);
    const nMull = Math.max(1, Math.round(w / 0.8)); for (let i = 1; i < nMull; i++) bar(0.03, h, -w / 2 + i * w / nMull, sill + h / 2);
    bar(w + 0.1, 0.03, 0, sill - 0.015);   // stool
    const sillBoard = new THREE.Mesh(metricBox(w + 0.1, 0.03, t + 0.06), trim); sillBoard.position.set(0, sill - 0.015, 0); frame.add(sillBoard);
    const glass = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.1, h - 0.1), this.glassMat()); glass.position.set(0, sill + h / 2, 0); glass.name = 'pglass'; frame.add(glass);
    frame.userData = { kind: 'window', opening: o.id }; this.group.add(frame);
  }
  glassMat() {
    if (!this._glass) this._glass = new THREE.MeshPhysicalMaterial({ color: 0xffffff, transmission: 0.92, roughness: 0.04, metalness: 0, ior: 1.5, thickness: 0.01, transparent: true, opacity: 1, side: THREE.DoubleSide, envMapIntensity: 1.2 });
    return this._glass;
  }

  // ---------- rooms: floor, ceiling, baseboard, light, label ----------
  buildRoom(r) {
    const pts = r.polygon.map(p => new THREE.Vector2(p[0], -p[1])); const shape = new THREE.Shape(pts);
    const geo = new THREE.ShapeGeometry(shape); geo.rotateX(-Math.PI / 2);   // (x, -z) -> (x, 0, z); uv = metres
    const mats = this.layout.materials || {}; const floorMat = this.lib.get((mats.floor || {})[r.id] || null, 'floor', r.type);
    // planks run along the room's long axis (texture planks are taken to run along V); each room gets its own phase
    { const xs = r.polygon.map(p => p[0]), zs = r.polygon.map(p => p[1]); const longX = (Math.max(...xs) - Math.min(...xs)) >= (Math.max(...zs) - Math.min(...zs));
      const ang = (floorMat.userData.category === 'wood_floor' || String(floorMat.userData.materialId).startsWith('default:wood')) && longX ? Math.PI / 2 : 0;
      const ox = hash01(r.id + 'x') * 1.7, oz = hash01(r.id + 'z') * 1.7; const uv = geo.attributes.uv; const ca = Math.cos(ang), sa = Math.sin(ang);
      for (let i = 0; i < uv.count; i++) { const u = uv.getX(i), v = uv.getY(i); uv.setXY(i, ca * u - sa * v + ox, sa * u + ca * v + oz); } uv.needsUpdate = true; }
    const floor = new THREE.Mesh(geo, floorMat); floor.receiveShadow = true; floor.position.y = 0.001; floor.name = 'pfloor_' + r.id; floor.userData = { kind: 'floor', room: r.id }; this.group.add(floor);
    const ceilMat = this.lib.get(mats.ceiling || null, 'ceiling'); const ceil = new THREE.Mesh(geo.clone(), ceilMat); ceil.material = ceilMat.clone(); ceil.material.side = THREE.BackSide; ceil.position.y = this.ceil; ceil.name = 'pceil_' + r.id; ceil.userData = { kind: 'ceiling', room: r.id }; this.group.add(ceil); this.ceilingMeshes.push(ceil);
    const wallMat = this.lib.get((mats.wall || {})[r.id] || null, 'wall');
    if ((mats.wall || {})[r.id]) this.recolourRoomWalls(r, wallMat);
    // baseboard along each interior edge
    const bb = this.lib.get(mats.baseboard || null, 'baseboard');
    for (let i = 0; i < r.polygon.length; i++) {
      const a = v2(r.polygon[i]), b = v2(r.polygon[(i + 1) % r.polygon.length]); const d = b.clone().sub(a); const len = d.length(); if (len < 0.05) continue; d.normalize();
      const nIn = new THREE.Vector2(-d.y, d.x);   // CCW polygon in (x,z) with z down: interior is to the right-hand side; test and flip
      const mid = a.clone().add(b).multiplyScalar(0.5); const probe = mid.clone().add(nIn.clone().multiplyScalar(0.05));
      if (!pointInPoly(probe, r.polygon)) nIn.negate();
      const m = new THREE.Mesh(metricBox(len, 0.1, 0.012), bb); const c = mid.clone().add(nIn.clone().multiplyScalar(0.006)); m.position.set(c.x, 0.05, c.y); m.rotation.y = -Math.atan2(d.y, d.x); m.castShadow = true; this.group.add(m);
    }
    const c = centroid(r.polygon); const area = r.area_m2 || polyArea(r.polygon);
    const light = new THREE.PointLight(0xfff1dc, Math.min(6, 0.55 * area), Math.max(4, Math.sqrt(area) * 2.4), 2); light.position.set(c.x, this.ceil - 0.25, c.y); light.userData = { room: r.id }; this.group.add(light); this.lights.push(light);
    if (area > 2.5 && pointInPoly(c, r.polygon)) {   // flush-mount ceiling fixture: a shallow disc that reads as the light source
      const fix = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.19, 0.07, 32), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff2dc, emissiveIntensity: 1.6, roughness: 0.6 }));
      fix.position.set(c.x, this.ceil - 0.035, c.y); fix.name = 'pceilfix_' + r.id; fix.userData = { kind: 'ceiling', room: r.id }; this.group.add(fix); this.ceilingMeshes.push(fix);
    }
    const label = makeLabel(`${r.name}  ${area.toFixed(1)} m²`); label.position.set(c.x, this.ceil + 0.25, c.y); label.userData = { room: r.id }; this.group.add(label); this.labels.push(label);
    this.roomMeshes[r.id] = { floor, ceiling: ceil, light, label, room: r, center: new THREE.Vector3(c.x, 0, c.y) };
  }
  recolourRoomWalls(r, mat) {   // per-room wall material: applies to wall pieces whose inside face is on this room (approximate: midpoint within 0.3 m of the polygon)
    for (const m of this.wallMeshes) { const p = new THREE.Vector2(m.position.x, m.position.z); if (distToPoly(p, r.polygon) < 0.3) m.material = mat; }
  }

  // ---------- fixtures ----------
  fixtureGroup(f) {
    const g = new THREE.Group(); const R = f.rect; g.position.set(R.x, 0, R.z); g.rotation.y = -THREE.MathUtils.degToRad(R.rot_deg || 0); g.userData = { kind: 'fixture', type: f.type, id: f.id }; return g;
  }
  box(w, h, d, mat, x = 0, y = 0, z = 0, g = null) { const m = new THREE.Mesh(metricBox(w, h, d), mat); m.position.set(x, y + h / 2, z); m.castShadow = m.receiveShadow = true; if (g) g.add(m); return m; }
  buildFixture(f) {
    const R = f.rect, w = R.w, d = R.d, H = f.height_m; const mats = this.layout.materials || {}; const g = this.fixtureGroup(f);
    const cab = this.lib.get(mats.cabinet || null, 'cabinet'), top = this.lib.get(mats.counter || null, 'counter'), steel = this.lib.plain('steel'), dark = this.lib.plain('dark_glass'), porc = this.lib.plain('porcelain');
    switch (f.type) {
      case 'counter': case 'island': case 'vanity': {
        const h = (H || 0.9) - 0.04; this.box(w - 0.02, 0.1, d - 0.07, dark, 0, 0, 0.03, g);              // toe kick (recessed)
        this.box(w, h - 0.1, d, cab, 0, 0.1, 0, g); this.box(w + 0.03, 0.04, d + 0.03, top, 0, h, 0.0, g);   // cabinet + slab
        const nd = Math.max(1, Math.round(w / 0.6)); const seam = new THREE.MeshStandardMaterial({ color: 0x3a3630, roughness: 0.9 });
        for (let i = 0; i < nd; i++) { this.box(0.12, 0.012, 0.02, steel, -w / 2 + (i + 0.5) * w / nd, h - 0.25, d / 2 + 0.01, g); if (i) this.box(0.006, h - 0.12, 0.004, seam, -w / 2 + i * w / nd, 0.11, d / 2 + 0.002, g); }   // handles + door seams (front = +z)
        this.box(w, 0.006, 0.004, seam, 0, h - 0.04, d / 2 + 0.002, g);   // drawer line under the slab
        if (f.type === 'vanity') { const basin = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.12, 24), porc); basin.position.set(0, h + 0.04 - 0.06, 0); g.add(basin); this.tap(g, 0, h + 0.04, -d / 2 + 0.08); }
        break; }
      case 'sink': { const rim = this.box(Math.min(w, 0.6), 0.015, Math.min(d, 0.45), steel, 0, (H || 0.9) + 0.0, 0, g); const basin = this.box(Math.min(w, 0.6) - 0.06, 0.02, Math.min(d, 0.45) - 0.06, dark, 0, (H || 0.9) + 0.015, 0, g); this.tap(g, 0, (H || 0.9) + 0.015, -Math.min(d, 0.45) / 2 + 0.04); break; }
      case 'stove': { this.box(w, (H || 0.9), d, steel, 0, 0, 0, g); const topm = this.box(w - 0.02, 0.012, d - 0.02, dark, 0, (H || 0.9), 0, g);
        for (const [bx, bz] of [[-0.18, -0.15], [0.18, -0.15], [-0.18, 0.15], [0.18, 0.15]]) { const b = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.01, 20), this.lib.plain('stone')); b.position.set(bx, (H || 0.9) + 0.018, bz); g.add(b); }
        this.box(w - 0.1, 0.1, 0.04, steel, 0, (H || 0.9) + 0.012, -d / 2 + 0.03, g);   // back panel
        this.box(w - 0.1, 0.35, 0.02, dark, 0, 0.3, d / 2 + 0.005, g); break; }   // oven window
      case 'fridge': { const fh = H || 1.75; this.box(w, fh, d, steel, 0, 0, 0, g); this.box(0.02, fh * 0.42, 0.03, steel, w / 2 - 0.1, fh * 0.1, d / 2 + 0.02, g); this.box(0.02, fh * 0.22, 0.03, steel, w / 2 - 0.1, fh * 0.72, d / 2 + 0.02, g);
        this.box(w + 0.004, 0.008, d + 0.004, dark, 0, fh * 0.66, 0, g); this.box(w - 0.02, 0.1, 0.02, dark, 0, 0.0, d / 2 - 0.01, g); break; }
      case 'dishwasher': { this.box(w - 0.02, (H || 0.85) - 0.12, 0.02, steel, 0, 0.1, d / 2 - 0.0, g); this.box(w - 0.1, 0.012, 0.03, steel, 0, (H || 0.85) - 0.2, d / 2 + 0.015, g); break; }
      case 'tub': { const h = H || 0.55; this.box(w, h, d, porc, 0, 0, 0, g); this.box(w - 0.16, 0.02, d - 0.16, this.lib.plain('tile'), 0, h - 0.14, 0, g); this.tap(g, 0, h, -d / 2 + 0.12); break; }
      case 'shower': { this.box(w, 0.1, d, porc, 0, 0, 0, g); const gl = new THREE.Mesh(new THREE.PlaneGeometry(w, 2.0), this.glassMat()); gl.position.set(0, 1.1, d / 2); g.add(gl); break; }
      case 'toilet': { this.box(0.4, 0.4, 0.18, porc, 0, 0.42, -d / 2 + 0.09, g); const bowl = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.14, 0.4, 24), porc); bowl.position.set(0, 0.2, 0.08); bowl.scale.z = 1.4; g.add(bowl); const seat = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.03, 24), porc); seat.position.set(0, 0.415, 0.08); seat.scale.z = 1.4; g.add(seat); break; }
      case 'closet_rod': { const rod = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, w - 0.05, 12), steel); rod.rotation.z = Math.PI / 2; rod.position.set(0, (H || 1.8), 0); g.add(rod); this.box(w, 0.025, d, this.lib.plain('wood_trim'), 0, (H || 1.8) + 0.25, 0, g); break; }
      case 'fireplace': { const h = H || 1.1; this.box(w, h, d, this.lib.plain('wood_trim'), 0, 0, 0, g); this.box(Math.min(w, 0.15), h - 0.4, d - 0.5, dark, w / 2 - Math.min(w, 0.15) / 2 + 0.01, 0.1, 0, g); this.box(w + 0.1, 0.05, d + 0.1, this.lib.plain('wood_trim'), 0, h, 0, g); this.box(w + 0.2, 0.02, d + 0.3, this.lib.plain('stone'), 0, 0, 0.0, g); break; }
      case 'washer': { this.box(w, H || 0.85, d, steel, 0, 0, 0, g); const door = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.02, 24), dark); door.rotation.x = Math.PI / 2; door.position.set(0, 0.45, d / 2 + 0.01); g.add(door); break; }
      default: this.box(w, H || 0.8, d, cab, 0, 0, 0, g);
    }
    this.group.add(g);
  }
  tap(g, x, y, z) { const steel = this.lib.plain('steel'); const base = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.02, 0.18, 12), steel); base.position.set(x, y + 0.09, z); g.add(base); const spout = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.14, 10), steel); spout.rotation.x = Math.PI / 2; spout.position.set(x, y + 0.18, z + 0.07); g.add(spout); }
}

// ---------- geometry helpers ----------
export function pointInPoly(p, poly) { let inside = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const xi = poly[i][0], zi = poly[i][1], xj = poly[j][0], zj = poly[j][1]; if (((zi > p.y) !== (zj > p.y)) && (p.x < (xj - xi) * (p.y - zi) / (zj - zi + 1e-12) + xi)) inside = !inside; } return inside; }
export function polyArea(poly) { let a = 0; for (let i = 0; i < poly.length; i++) { const [x1, z1] = poly[i], [x2, z2] = poly[(i + 1) % poly.length]; a += x1 * z2 - x2 * z1; } return Math.abs(a) / 2; }
export function centroid(poly) { let x = 0, z = 0; for (const p of poly) { x += p[0]; z += p[1]; } return new THREE.Vector2(x / poly.length, z / poly.length); }
function distToPoly(p, poly) { let best = Infinity; for (let i = 0; i < poly.length; i++) { const a = v2(poly[i]), b = v2(poly[(i + 1) % poly.length]); const ab = b.clone().sub(a); const t = THREE.MathUtils.clamp(p.clone().sub(a).dot(ab) / (ab.lengthSq() + 1e-9), 0, 1); best = Math.min(best, a.clone().add(ab.multiplyScalar(t)).distanceTo(p)); } return pointInPoly(p, poly) ? 0 : best; }
function makeLabel(text) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 96; const ctx = c.getContext('2d'); ctx.fillStyle = 'rgba(20,24,32,0.78)'; roundRect(ctx, 4, 4, 504, 88, 18); ctx.fill();
  ctx.font = '600 38px system-ui, -apple-system, Segoe UI, sans-serif'; ctx.fillStyle = '#f3f5f8'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 256, 50);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true })); sp.scale.set(1.9, 0.36, 1); sp.renderOrder = 10; return sp;
}
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

// ---------- procedural fallback textures (canvas), 1 texture unit = 1 m ----------
const _ptCache = new Map();
export function proceduralTexture(kind) {
  if (_ptCache.has(kind)) return _ptCache.get(kind);
  let res = null; const S = 1024; const mk = () => { const c = document.createElement('canvas'); c.width = c.height = S; return [c, c.getContext('2d')]; };
  const tex = (c, srgb) => { const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; if (srgb) t.colorSpace = THREE.SRGBColorSpace; return t; };
  const rnd = mulberry32(kind.length * 977 + 13);
  if (kind === 'wood_floor') {   // 1 m x 1 m: planks 0.125 m wide, random lengths, grain lines
    const [c, ctx] = mk(); const pw = S / 8; const base = [178, 128, 78];
    for (let i = 0; i < 8; i++) { let y = 0; const off = rnd() * S; while (y < S + S) { const len = S * (0.6 + rnd() * 0.9); const tone = 0.82 + rnd() * 0.36; ctx.fillStyle = `rgb(${base[0] * tone | 0},${base[1] * tone | 0},${base[2] * tone | 0})`; ctx.fillRect(i * pw, (y - off) % S, pw, len); ctx.fillStyle = 'rgba(40,25,10,0.55)'; ctx.fillRect(i * pw, ((y - off) % S) - 2, pw, 3); y += len; } ctx.fillStyle = 'rgba(40,25,10,0.5)'; ctx.fillRect(i * pw - 1, 0, 2, S); }
    ctx.globalAlpha = 0.18; for (let k = 0; k < 2600; k++) { const x = rnd() * S, y = rnd() * S; ctx.fillStyle = rnd() < 0.5 ? '#3a2410' : '#e2b582'; ctx.fillRect(x, y, 1.5 + rnd() * 2, 18 + rnd() * 90); } ctx.globalAlpha = 1;
    const [r, rc] = mk(); rc.fillStyle = '#8c8c8c'; rc.fillRect(0, 0, S, S); rc.globalAlpha = 0.25; for (let k = 0; k < 2000; k++) { rc.fillStyle = rnd() < 0.5 ? '#000' : '#fff'; rc.fillRect(rnd() * S, rnd() * S, 2, 40); }
    res = { map: tex(c, true), rough: tex(r, false) };
  } else if (kind === 'tile') {   // 0.33 m tiles with grout
    const [c, ctx] = mk(); const n = 3, tw = S / n; ctx.fillStyle = '#b9b4ab'; ctx.fillRect(0, 0, S, S);
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { const t = 0.94 + rnd() * 0.08; ctx.fillStyle = `rgb(${225 * t | 0},${221 * t | 0},${213 * t | 0})`; ctx.fillRect(i * tw + 4, j * tw + 4, tw - 8, tw - 8); }
    const [r, rc] = mk(); rc.fillStyle = '#4a4a4a'; rc.fillRect(0, 0, S, S); rc.fillStyle = '#c8c8c8'; for (let i = 0; i < n; i++) { rc.fillRect(i * tw, 0, 8, S); rc.fillRect(0, i * tw, S, 8); }
    res = { map: tex(c, true), rough: tex(r, false) };
  } else if (kind === 'paint' || kind === 'paint_white') {   // very subtle plaster noise
    const [c, ctx] = mk(); const b = kind === 'paint' ? [241, 238, 230] : [247, 247, 244]; ctx.fillStyle = `rgb(${b[0]},${b[1]},${b[2]})`; ctx.fillRect(0, 0, S, S); ctx.globalAlpha = 0.045;
    for (let k = 0; k < 9000; k++) { ctx.fillStyle = rnd() < 0.5 ? '#000' : '#fff'; ctx.fillRect(rnd() * S, rnd() * S, 2 + rnd() * 4, 2 + rnd() * 4); }
    res = { map: tex(c, true) };
  } else if (kind === 'stone') {
    const [c, ctx] = mk(); ctx.fillStyle = '#3b3b3d'; ctx.fillRect(0, 0, S, S); ctx.globalAlpha = 0.5; for (let k = 0; k < 6000; k++) { ctx.fillStyle = rnd() < 0.6 ? '#2a2a2c' : '#5a5a5e'; ctx.beginPath(); ctx.arc(rnd() * S, rnd() * S, 1 + rnd() * 4, 0, 7); ctx.fill(); }
    res = { map: tex(c, true) };
  } else if (kind === 'carpet') {
    const [c, ctx] = mk(); ctx.fillStyle = '#b9b2a4'; ctx.fillRect(0, 0, S, S); ctx.globalAlpha = 0.25; for (let k = 0; k < 40000; k++) { ctx.fillStyle = rnd() < 0.5 ? '#8f8778' : '#d8d1c3'; ctx.fillRect(rnd() * S, rnd() * S, 2, 2); }
    res = { map: tex(c, true) };
  }
  _ptCache.set(kind, res); return res;
}
function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
