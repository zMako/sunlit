// Furnishing layer for room.html: true-scale items in the reconstructed room, drag/rotate/snap, fit feedback, persistence.
// Plan contract: app/furnish/plans/<room>.json {room, items:[{id,name,category,w_m,d_m,h_m,x,z,rot_deg,price_usd,product_url,image,model_glb?}], total_usd}
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';

const DEG = Math.PI / 180;
const CORRIDOR = 0.75, GRID = 0.1, WALL_SNAP = 0.10, ITEM_SNAP = 0.05;

export class Furnish {
  constructor({ scene, camera, renderer, controls, panelEl, toastEl, active = true, onChange = null, title = null }) {
    Object.assign(this, { scene, camera, renderer, controls, panelEl, toastEl, active, onChange, title });
    this.group = new THREE.Group(); this.group.name = 'furniture'; scene.add(this.group);
    this.items = []; this.fixtures = []; this.selected = null; this.room = null; this.meta = null; this.plan = { items: [] }; this.clipPlanes = [];
    this.ray = new THREE.Raycaster(); this.floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    (window.furnishInstances ||= []).push(this); window.furnishByRoom ||= {};
    this.drag = null; this.dirty = false; this.saveTimer = null; this.loader = new GLTFLoader(); const draco = new DRACOLoader(); draco.setDecoderPath('/vendor/three/jsm/libs/draco/gltf/'); this.loader.setDRACOLoader(draco); /* IKEA GLBs are Draco-compressed */ this.texLoader = new THREE.TextureLoader();
    this.texLoader.setCrossOrigin('anonymous');
    this._bind();
  }

  // ---------- room geometry ----------
  async setRoom(name, meta) {
    this.room = name; this.meta = meta; this.clear(); window.furnishByRoom[name] = this;
    const poly = meta.polygon || []; this.poly = poly.map(p => new THREE.Vector2(p[0], p[1]));
    this.edges = (meta.edges || []).map((e, i) => ({ i, a: new THREE.Vector2(...e.a), b: new THREE.Vector2(...e.b), n: new THREE.Vector2(...e.n), len: e.len }));
    // door swings: quarter circle of the door width inside the room, hinge at s0 end
    this.doors = (meta.doors || []).filter(d => d.kind === 'door' && this.edges[d.edge]).map(d => {
      const e = this.edges[d.edge]; const dir = e.b.clone().sub(e.a).normalize(); const w = Math.max(0.6, Math.min(1.1, d.width_m || 0.8));
      const hinge = e.a.clone().add(dir.clone().multiplyScalar(d.s0)); const inward = e.n.clone().negate();
      const mid = e.a.clone().add(dir.clone().multiplyScalar((d.s0 + d.s1) / 2)).add(inward.clone().multiplyScalar(0.05));
      return { edge: d.edge, hinge, dir, inward, w, mid };
    });
    this.windows = (meta.windows || []).filter(w => this.edges[w.edge]).map(w => ({ edge: w.edge, s0: w.s0, s1: w.s1, sill: w.sill_m }));
    // built-in fixtures (counters, tubs, closets...) from the plan: read-only obstacles for overlap and path checks, drawn by the apartment builder, not here
    this.fixtures = (meta.fixtures || []).filter(f => f.rect).map(f => ({ spec: { id: f.id, name: f.type, category: 'fixture', x: f.rect.x, z: f.rect.z, w_m: f.rect.w, d_m: f.rect.d, h_m: f.height_m || 0.9, rot_deg: f.rect.rot_deg || 0 }, readonly: true, problems: [] }));
    this._bbox = new THREE.Box2().setFromPoints(this.poly);
    await this.loadPlan();
  }

  clear() { for (const it of this.items) this.group.remove(it.obj); this.items = []; this.selected = null; this._panel(); }

  async loadPlan() {
    let plan = { room: this.room, items: [] };
    try { const r = await fetch(`/api/furnish?room=${encodeURIComponent(this.room)}`); if (r.ok) plan = await r.json(); } catch (e) {}
    this.plan = plan; this.clear();
    for (const it of (plan.items || [])) await this.addItem(it, false);
    this._refresh();
  }

  async setPlan(plan, save = false) { this.plan = plan; this.clear(); for (const it of (plan.items || [])) await this.addItem(it, false); this._refresh(); if (save) this.save(); }
  itemById(id) { return this.items.find(it => it.spec.id === id); }

  // ---------- items ----------
  async addItem(spec, markDirty = true) {
    const it = { spec: { rot_deg: 0, ...spec }, obj: new THREE.Group(), problems: [] };
    it.obj.userData.item = it;
    const w = +spec.w_m || 0.5, d = +spec.d_m || 0.5, h = +spec.h_m || 0.5;
    let built = false;
    this.useIkeaModels = this.useIkeaModels ?? (localStorage.getItem('models3d') !== '0');   // default ON: models are cached locally (owner's decision)
    const recorded = spec.model_glb ? (/^(https?:)?\//.test(spec.model_glb) ? spec.model_glb : '/' + spec.model_glb.replace(/^\.?\//, '')) : null;
    const byId = spec.id ? `/furnish/models/${String(spec.id).split('#')[0]}.glb` : null;   // the catalogue caches IKEA models locally by product id
    const remote = spec.model_glb_url ? `/api/model?u=${encodeURIComponent(spec.model_glb_url)}` : null;
    const candidates = this.useIkeaModels ? [recorded, byId, remote].filter((v, i, a) => v && a.indexOf(v) === i) : [];
    for (const glbSrc of candidates) {
      try {
        const gl = await this.loader.loadAsync(glbSrc); const m = gl.scene; m.traverse(o => { if (o.isMesh) { o.castShadow = true; o.userData.item = it; } });
        this._dressUntextured(m, spec);   // manufacturer OBJ/FBX exports mostly come without textures: give them a plausible PBR finish from the catalogue words
        // orientation pass (designer/orient.json, see orient/REPORT.md): which axis is up and where the front is, found from symmetry, backrest mass and CLIP; applied when confident
        const data = await Furnish._data(); const pid = String(spec.id || '').split('#')[0]; const od0 = data.orient[pid]; const fl = data.flags[pid];
        const od = fl && fl.yaw_fix != null ? { ...(od0 || { up: 'y' }), front_yaw_deg: ((od0 && od0.front_yaw_deg) || 0) + fl.yaw_fix, confidence: 1 } : od0;   // the owner's correction from the gallery wins
        if (od && (od.confidence ?? 0) >= 0.6 && (od.up !== 'y' || od.front_yaw_deg)) {
          const UP = { y: [0, 0, 0], '-y': [180, 0, 0], z: [-90, 0, 0], '-z': [90, 0, 0], x: [0, 0, 90], '-x': [0, 0, -90] }; const e = UP[od.up] || UP.y; const D = Math.PI / 180;
          const qUp = new THREE.Quaternion().setFromEuler(new THREE.Euler(e[0] * D, e[1] * D, e[2] * D)); const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), (od.front_yaw_deg || 0) * D).multiply(qUp);
          const og = new THREE.Group(); og.quaternion.copy(q); og.add(m); og.updateMatrixWorld(true); var oriented = og; it.oriented = od.method;
        }
        const m0 = (typeof oriented !== 'undefined' && oriented) ? oriented : m;
        let bb = new THREE.Box3().setFromObject(m0); let sz = bb.getSize(new THREE.Vector3());
        // which way up / which way round: of the 90-degree rotations, keep the one whose extents need the least anisotropic stretch to meet the listed w x h x d
        const err = (ex, ey, ez) => Math.abs(Math.log(Math.max(ex, 1e-3) / w)) + Math.abs(Math.log(Math.max(ey, 1e-3) / h)) + Math.abs(Math.log(Math.max(ez, 1e-3) / d));
        const tries = [[0, 0, 0, sz.x, sz.y, sz.z], [0, Math.PI / 2, 0, sz.z, sz.y, sz.x], [Math.PI / 2, 0, 0, sz.x, sz.z, sz.y], [Math.PI / 2, 0, Math.PI / 2, sz.y, sz.z, sz.x], [0, 0, Math.PI / 2, sz.y, sz.x, sz.z], [Math.PI / 2, Math.PI / 2, 0, sz.z, sz.x, sz.y]];
        const e0 = err(sz.x, sz.y, sz.z); let best = tries[0], be = e0;
        for (const t of tries) { const e = err(t[3], t[4], t[5]); if (e < be - 0.3) { best = t; be = e; } }   // a clear win only: near-cubic pieces keep their file orientation
        const inner = new THREE.Group(); inner.add(m0); inner.rotation.set(best[0], best[1], best[2]); inner.updateMatrixWorld(true);
        bb = new THREE.Box3().setFromObject(inner); sz = bb.getSize(new THREE.Vector3()); const c = bb.getCenter(new THREE.Vector3());
        inner.position.sub(c); inner.position.y += sz.y / 2;   // rest on the floor, centred on footprint
        const s = new THREE.Vector3(w / Math.max(sz.x, 1e-3), h / Math.max(sz.y, 1e-3), d / Math.max(sz.z, 1e-3));
        const wrap = new THREE.Group(); wrap.add(inner); wrap.scale.copy(s); it.obj.add(wrap); built = true; it.modelSrc = glbSrc; it.axisFix = best !== tries[0];
        if (spec.category === 'bed' && h < 0.42) {   // manufacturers model the frame only: add a mattress so the bed reads as a bed
          const mat = new THREE.Mesh(new THREE.BoxGeometry(Math.max(0.6, w - 0.12), 0.22, Math.max(1.2, d - 0.16)), new THREE.MeshPhysicalMaterial({ color: 0xf2eee6, roughness: 0.95, sheen: 0.3 }));
          mat.position.set(0, h - 0.06 + 0.11, 0.02); mat.castShadow = true; mat.userData.item = it; it.obj.add(mat);
          Furnish._bump('fabric').then(t => { if (t) { mat.material.normalMap = t; mat.material.normalScale.set(0.4, 0.4); mat.material.needsUpdate = true; } });
        }
        break;
      } catch (e) { console.warn('[furnish] model failed', spec.id, glbSrc, e && e.message); }
    }
    if (!built) { it.modelFailed = true; it.problems = it.problems || []; it.problems.push('3D model missing'); }   // never draw a photo-on-a-box: an item without a model is a problem, not a prop
    // label sprite
    const label = this._label(spec.name || spec.id || 'item'); label.position.set(0, h + 0.18, 0); it.obj.add(label); it.label = label;
    // footprint outline on the floor (selection/fit colour)
    const fp = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-w / 2, 0.005, -d / 2), new THREE.Vector3(w / 2, 0.005, -d / 2), new THREE.Vector3(w / 2, 0.005, d / 2), new THREE.Vector3(-w / 2, 0.005, d / 2)]), new THREE.LineBasicMaterial({ color: 0x9fe3c0 }));
    it.obj.add(fp); it.fp = fp;
    // front marker (local +z face is the front: it carries the product photo)
    const fm = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(w, 0.6) * 0.5, 0.03), new THREE.MeshBasicMaterial({ color: 0x9fe3c0, side: THREE.DoubleSide })); fm.rotation.x = -Math.PI / 2; fm.position.set(0, 0.006, d / 2 + 0.04); it.obj.add(fm); it.fm = fm;
    this._place(it, +spec.x || 0, +spec.z || 0, +spec.rot_deg || 0);
    this._applyClip(it.obj);
    this.group.add(it.obj); this.items.push(it);
    if (markDirty) { this._refresh(); this._touch(); }
    return it;
  }

  _card(spec, w, d, h, it) {
    const g = new THREE.Group();
    const mats = []; const base = new THREE.MeshStandardMaterial({ color: 0xf2f0ea, roughness: 0.85, metalness: 0 });
    for (let i = 0; i < 6; i++) mats.push(base);
    const box = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mats); box.position.y = h / 2; box.userData.item = it; g.add(box);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({ color: 0x2a2f38 })); edges.position.y = h / 2; g.add(edges);
    if (spec.image) {
      const src = /^https?:\/\//.test(spec.image) ? `/api/img?u=${encodeURIComponent(spec.image)}` : spec.image;
      this.texLoader.load(src, tex => {
        tex.colorSpace = THREE.SRGBColorSpace;
        const pm = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.8 });
        const m2 = mats.slice(); m2[4] = pm;   // +z face = front
        box.material = m2; box.material.needsUpdate = true;
      }, undefined, () => {});
    }
    return g;
  }

  _label(text) {
    const c = document.createElement('canvas'); c.width = 512; c.height = 96; const x = c.getContext('2d');
    x.fillStyle = 'rgba(10,14,22,0.8)'; x.fillRect(0, 0, c.width, c.height); x.fillStyle = '#e8ecf2'; x.font = '600 40px system-ui'; x.textBaseline = 'middle'; x.fillText(text.slice(0, 26), 16, 48);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false })); s.scale.set(0.9, 0.17, 1); return s;
  }

  setClipping(planes) { this.clipPlanes = planes || []; for (const it of this.items) this._applyClip(it.obj); }
  _applyClip(obj) { obj.traverse(o => { if (o.isMesh && o.material && !o.isSprite) { const ms = Array.isArray(o.material) ? o.material : [o.material]; ms.forEach(m => { m.clippingPlanes = this.clipPlanes; m.clipShadows = true; }); } }); }
  setActive(on) { this.active = !!on; if (!on) { this.drag = null; this.select(null); } }
  _place(it, x, z, rot) { it.spec.x = x; it.spec.z = z; it.spec.rot_deg = ((rot % 360) + 360) % 360; it.obj.position.set(x, +it.spec.y_m || 0, z); it.obj.rotation.y = -it.spec.rot_deg * DEG; this._cord(it); }
  _cord(it) {   // pendants hang from the ceiling: a thin cord from the top of the shade up to the slab
    if (it.spec.category !== 'pendant_lamp') return;
    const ceil = (this.meta && +this.meta.ceiling_m) || 2.6; const top = (+it.spec.y_m || 0) + (+it.spec.h_m || 0); const len = Math.max(0.02, ceil - top);
    if (!it.cord) { it.cord = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 1, 6), new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.8 })); it.obj.add(it.cord); }
    it.cord.scale.y = len; it.cord.position.y = (+it.spec.h_m || 0) + len / 2;
  }

  remove(it) { if (!it) return; this.group.remove(it.obj); this.items = this.items.filter(o => o !== it); if (this.selected === it) this.select(null); this._refresh(); this._touch(); }
  duplicate(it) { if (!it) return; const s = { ...it.spec, x: it.spec.x + 0.3, z: it.spec.z + 0.3 }; this.addItem(s).then(n => this.select(n)); }
  select(it) { this.selected = it; this._refresh(); }

  // ---------- geometry helpers ----------
  _distToPoly(p) { let best = 1e9; for (let i = 0; i < this.poly.length; i++) best = Math.min(best, Furnish.segDist(p, this.poly[i], this.poly[(i + 1) % this.poly.length])); return best; }
  corners(it, x = it.spec.x, z = it.spec.z, rot = it.spec.rot_deg) {
    const w = +it.spec.w_m, d = +it.spec.d_m; const c = Math.cos(-rot * DEG), s = Math.sin(-rot * DEG);
    const pts = [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]];
    return pts.map(([px, pz]) => new THREE.Vector2(x + px * c + pz * s, z - px * s + pz * c));   // rotation.y=-rot => standard yaw
  }
  frontCenter(it) { const r = -it.spec.rot_deg * DEG; const d = +it.spec.d_m; const fx = (d / 2 + 0.2) * Math.sin(r), fz = (d / 2 + 0.2) * Math.cos(r); return new THREE.Vector2(it.spec.x + fx, it.spec.z + fz); }
  static inPoly(p, poly) { let inside = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const a = poly[i], b = poly[j]; if (((a.y > p.y) !== (b.y > p.y)) && (p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x)) inside = !inside; } return inside; }
  static sat(A, B) {   // oriented rectangle overlap (separating axis)
    for (const P of [A, B]) for (let i = 0; i < 4; i++) { const e = P[(i + 1) % 4].clone().sub(P[i]); const ax = new THREE.Vector2(-e.y, e.x).normalize();
      let a0 = Infinity, a1 = -Infinity, b0 = Infinity, b1 = -Infinity; for (const p of A) { const v = p.dot(ax); a0 = Math.min(a0, v); a1 = Math.max(a1, v); } for (const p of B) { const v = p.dot(ax); b0 = Math.min(b0, v); b1 = Math.max(b1, v); }
      if (a1 < b0 + 1e-3 || b1 < a0 + 1e-3) return false; }
    return true;
  }
  static segDist(p, a, b) { const ab = b.clone().sub(a); const t = Math.max(0, Math.min(1, p.clone().sub(a).dot(ab) / Math.max(ab.lengthSq(), 1e-9))); return p.distanceTo(a.clone().add(ab.multiplyScalar(t))); }

  // ---------- snapping ----------
  snap(it, x, z) {
    if (!this.poly.length || this._shift) return [x, z];
    let best = null;
    const cs = this.corners(it, x, z);
    // walls: translate so the nearest item corner lands exactly on the wall when within WALL_SNAP (and the item is inside)
    for (const e of this.edges) {
      for (const c of cs) { const dist = c.clone().sub(e.a).dot(e.n); // signed distance outward along normal (0 on wall, >0 outside)
        if (Math.abs(dist) < WALL_SNAP) { const shift = e.n.clone().multiplyScalar(-dist); if (!best || shift.length() < best.length()) best = shift; } }
    }
    if (best) { x += best.x; z += best.y; }
    // other items: align edges (axis-aligned approximation on item bbox)
    const bb = new THREE.Box2().setFromPoints(this.corners(it, x, z));
    for (const o of this.items) { if (o === it) continue; const ob = new THREE.Box2().setFromPoints(this.corners(o));
      for (const [a, b] of [[bb.min.x, ob.max.x], [bb.max.x, ob.min.x], [bb.min.x, ob.min.x], [bb.max.x, ob.max.x]]) if (Math.abs(a - b) < ITEM_SNAP) { x += b - a; break; }
      for (const [a, b] of [[bb.min.y, ob.max.y], [bb.max.y, ob.min.y], [bb.min.y, ob.min.y], [bb.max.y, ob.max.y]]) if (Math.abs(a - b) < ITEM_SNAP) { z += b - a; break; } }
    return [x, z];
  }

  // ---------- fit check ----------
  check() {
    if (!this.poly.length) return;
    const fps = this.items.map(it => this.corners(it));
    for (const it of this.items) it.problems = [];
    this.items.forEach((it, i) => {
      const fp = fps[i];
      const hung = sp => sp.floor === false || sp.category === 'pendant_lamp' || (+sp.y_m || 0) > 0.3;   // hung or carried: takes no floor, overlaps nothing
      const out = fp.some(c => !Furnish.inPoly(c, this.poly)); if (out && fp.some(c => Furnish.inPoly(c, this.poly))) { const cen = fp.reduce((a, c) => a.add(c), new THREE.Vector2()).multiplyScalar(0.25); if (Furnish.inPoly(cen, this.poly) && fp.every(c => Furnish.inPoly(c, this.poly) || this._distToPoly(c) < 0.06)) { /* a corner grazing the wall line within 6 cm: fine */ } else it.problems.push('outside the walls'); } else if (out) it.problems.push('outside the walls');
      if (!hung(it.spec)) this.items.forEach((o, j) => { if (j > i && !hung(o.spec) && Furnish.sat(fp, fps[j]) && it.spec.category !== 'rug' && o.spec.category !== 'rug') { it.problems.push(`overlaps ${o.spec.name}`); o.problems.push(`overlaps ${it.spec.name}`); } });
      if (it.spec.category !== 'rug' && !hung(it.spec)) for (const fx of this.fixtures) if (Furnish.sat(fp, this.corners(fx))) it.problems.push(`overlaps the ${fx.spec.name}`);
      for (const dsw of this.doors) { // quarter circle: points within w of hinge, on the inward side, within 90deg from the edge direction
        const hit = fp.some(c => { const v = c.clone().sub(dsw.hinge); return v.length() < dsw.w && v.dot(dsw.inward) > -0.02 && v.dot(dsw.dir) > -0.02; }) || Furnish.segDist(dsw.mid, fp[0], fp[1]) < 0.001;
        if (hit && it.spec.category !== 'rug') it.problems.push('in a door swing');
      }
      if (it.spec.h_m > 0.05) for (const win of this.windows) { const e = this.edges[win.edge]; if (!e) continue; const dir = e.b.clone().sub(e.a).normalize();
        const near = fp.some(c => Math.abs(c.clone().sub(e.a).dot(e.n)) < 0.12); if (!near) continue;
        const ss = fp.map(c => c.clone().sub(e.a).dot(dir)); const lo = Math.min(...ss), hi = Math.max(...ss);
        if (hi > win.s0 && lo < win.s1 && it.spec.h_m > win.sill) it.problems.push('covers a window'); }
    });
    this._paths();
  }
  static SMALL = new Set(['rug', 'fixture_small', 'nightstand', 'side_table', 'floor_lamp', 'table_lamp', 'mirror', 'plant_pot', 'plant', 'stool', 'ottoman', 'pendant_lamp']);
  static bigItem(it) { const s = it.spec; return !Furnish.SMALL.has(s.category) && (+s.w_m || 0) * (+s.d_m || 0) >= 0.3; }   // same rule as place.py: small pieces neither block nor need the corridor
  _paths() {   // 10 cm grid, occupied by big items, BFS from each door; big items whose front cell is unreachable block the walking path
    if (!this.doors.length || !this.items.length) return;
    const bb = this._bbox; const nx = Math.ceil((bb.max.x - bb.min.x) / GRID) + 1, nz = Math.ceil((bb.max.y - bb.min.y) / GRID) + 1;
    const occ = new Uint8Array(nx * nz); const idx = (x, z) => Math.floor((z - bb.min.y) / GRID) * nx + Math.floor((x - bb.min.x) / GRID);
    const fps = this.items.map(it => this.corners(it));
    for (let gz = 0; gz < nz; gz++) for (let gx = 0; gx < nx; gx++) { const p = new THREE.Vector2(bb.min.x + gx * GRID, bb.min.y + gz * GRID); let o = !Furnish.inPoly(p, this.poly);
      if (!o) for (let i = 0; i < fps.length; i++) { if (!Furnish.bigItem(this.items[i])) continue; if (Furnish.inPoly(p, fps[i])) { o = 1; break; } }
      if (!o) for (const fx of this.fixtures) { if (Furnish.inPoly(p, this.corners(fx))) { o = 1; break; } }
      occ[gz * nx + gx] = o ? 1 : 0; }
    // corridor width: dilate obstacles by (CORRIDOR/2) so a walkable cell has clearance
    const r = Math.round(CORRIDOR / 2 / GRID); const occ2 = new Uint8Array(occ);
    for (let gz = 0; gz < nz; gz++) for (let gx = 0; gx < nx; gx++) if (occ[gz * nx + gx]) for (let dz = -r; dz <= r; dz++) for (let dx = -r; dx <= r; dx++) { const X = gx + dx, Z = gz + dz; if (X >= 0 && Z >= 0 && X < nx && Z < nz && dx * dx + dz * dz <= r * r) occ2[Z * nx + X] = 1; }
    const seen = new Uint8Array(nx * nz); const q = [];
    for (const d of this.doors) {   // seed from every free cell within 0.8 m inside the door
      const s = d.mid.clone().add(d.inward.clone().multiplyScalar(0.4)); const rr = Math.round(0.8 / GRID); const c = idx(s.x, s.y); const cx = c % nx, cz = (c - cx) / nx;
      for (let dz = -rr; dz <= rr; dz++) for (let dx = -rr; dx <= rr; dx++) { const X = cx + dx, Z = cz + dz; if (X < 0 || Z < 0 || X >= nx || Z >= nz) continue; const kk = Z * nx + X; if (!occ2[kk] && !seen[kk]) { seen[kk] = 1; q.push(kk); } } }
    if (!q.length) return;   // doors fully blocked by walls' dilation: no path information
    while (q.length) { const k = q.shift(); const gx = k % nx, gz = (k - gx) / nx; for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const X = gx + dx, Z = gz + dz; if (X < 0 || Z < 0 || X >= nx || Z >= nz) continue; const kk = Z * nx + X; if (seen[kk] || occ2[kk]) continue; seen[kk] = 1; q.push(kk); } }
    for (const it of this.items) { if (!Furnish.bigItem(it)) continue; const f = this.frontCenter(it);
      // reachable if any free cell within CORRIDOR/2+0.3 of the front centre is reached
      let ok = false; const rr = Math.round(1.2 / GRID); /* a walkable cell within 1.2 m of the item's front counts as reachable: a coffee table 0.5 m in front of a sofa is normal */ const c = idx(f.x, f.y); const cx = c % nx, cz = (c - cx) / nx;
      for (let dz = -rr; dz <= rr && !ok; dz++) for (let dx = -rr; dx <= rr; dx++) { const X = cx + dx, Z = cz + dz; if (X >= 0 && Z >= 0 && X < nx && Z < nz && seen[Z * nx + X]) { ok = true; break; } }
      if (!ok) it.problems.push('blocks the walking path'); }
  }

  _refresh() {
    this.check();
    for (const it of this.items) { const hard = it.problems.some(p => !p.startsWith('blocks')); const soft = it.problems.length && !hard;
      const col = hard ? 0xff5a5a : soft ? 0xffb347 : (it === this.selected ? 0x66ccff : 0x9fe3c0);
      it.fp.material.color.setHex(col); it.fm.material.color.setHex(col); it.fp.material.linewidth = 1;
      it.obj.traverse(o => { if (o.isMesh && o.material && o.material.emissive) { o.material.emissive.setHex(it === this.selected ? 0x224466 : 0x000000); } });
      it.label.visible = true; }
    this._panel();
  }

  _panel() {
    if (this.onChange) this.onChange(this);
    if (!this.panelEl) return; const items = this.items; const total = items.reduce((s, it) => s + (+it.spec.price_usd || 0), 0); const nprob = items.reduce((s, it) => s + it.problems.length, 0);
    this.panelEl.innerHTML = `<div class="frow"><b>${this.title || 'Furniture'}</b> <span class="${nprob ? 'bad' : 'ok'}">${items.length ? (nprob ? nprob + ' problem' + (nprob > 1 ? 's' : '') : 'fits') : 'empty plan'}</span>
      <span style="float:right">$${total.toFixed(0)}</span></div>` +
      items.map((it, i) => `<div class="fitem ${it === this.selected ? 'sel' : ''} ${it.problems.length ? (it.problems.some(p => !p.startsWith('blocks')) ? 'bad' : 'warn') : ''}" data-i="${i}">
        <span class="fname">${it.spec.name || it.spec.id}</span> <span class="fdim">${(+it.spec.w_m).toFixed(2)}×${(+it.spec.d_m).toFixed(2)}×${(+it.spec.h_m).toFixed(2)} m</span>
        <span class="fprice">${it.spec.price_usd != null ? '$' + (+it.spec.price_usd).toFixed(0) + (it.spec.price_source === 'estimated' ? ' <span class="fdim">est.</span>' : '') : '<span class="fdim">price on request</span>'}</span> ${it.spec.product_url ? `<a href="${it.spec.product_url}" target="_blank">product</a>` : ''}${it.spec.borrowed ? ' <span class="fdim">· from the standard range (few designer pieces in this category)</span>' : ''}
        ${it.problems.length ? `<div class="fprob">${it.problems.join(' · ')}</div>` : ''}</div>`).join('') +
      `<div class="frow"><button id="fsave">Save</button> <button id="fauto">Auto-arrange</button> <button id="freload">Reload</button> <span id="fstatus" class="fdim">${this.dirty ? 'unsaved' : ''}</span></div>
       <div class="fdim"><label><input type="checkbox" id="fikea" ${this.useIkeaModels ? 'checked' : ''}> 3D product models (local cache)</label></div>
       <div class="fdim">click select · drag move · R rotate 90° · [ ] 15° · arrows nudge 5 cm · D duplicate · Del remove · Shift no snap${this.fixtures.length ? ` · ${this.fixtures.length} built-in fixtures are obstacles` : ''}</div>
       ${items.some(it => String(it.spec.id||'').startsWith('abo-')) ? `<div class="fdim">Amazon items: 3D models and images from the Amazon Berkeley Objects dataset © Amazon.com, CC BY 4.0; resized and compressed; prices marked est. are our estimates from comparable products and are confirmed at the merchant.</div>` : ''}
       ${items.some(it => it.spec.price_source === 'estimated' && String(it.spec.id||'').startsWith('dsg-')) ? `<div class="fdim">Designer prices marked est. are estimated from the brand's and category's listed prices; the final quote comes from the dealer.</div>` : ''}`;
    this.panelEl.querySelectorAll('.fitem').forEach(el => el.onclick = () => this.select(this.items[+el.dataset.i]));
    const b = id => this.panelEl.querySelector('#' + id); b('fsave').onclick = () => this.save(); b('freload').onclick = () => this.loadPlan(); b('fauto').onclick = () => this.auto();
    b('fikea').onchange = e => { this.useIkeaModels = e.target.checked; localStorage.setItem('models3d', e.target.checked ? '1' : '0'); this.loadPlan(); };
  }


  // ---------- material fallback for untextured models ----------
  _finishFor(spec) {   // finish class + colour from the catalogue words (name, colour, materials, description); secondary = legs/frame guess
    const t = [spec.color, spec.colours, spec.materials, spec.name, spec.description].flat().filter(Boolean).join(' ').toLowerCase();
    const has = (...w) => w.some(x => t.includes(x));
    const legs = has('brass', 'gold') ? ['metal_brass', '#c8a24a'] : has('chrome', 'stainless', 'steel', 'aluminium', 'aluminum') ? ['metal_chrome', '#d9d9d9'] : has('black') ? ['metal_black', '#1d1d1d'] : has('oak', 'ash', 'birch', 'beech', 'maple', 'pine') ? ['wood_light', '#c9a977'] : ['metal_black', '#2a2a2a'];
    let main;
    if (has('walnut', 'smoked oak', 'dark oak', 'wenge', 'black stained')) main = ['wood_dark', '#4a3222'];
    else if (has('oak', 'ash', 'birch', 'beech', 'maple', 'natural wood', 'pine')) main = ['wood_light', '#c9a977'];
    else if (has('teak', 'mahogany', 'cherry')) main = ['wood_mid', '#8a5a33'];
    else if (has('black leather')) main = ['leather', '#1e1a18'];
    else if (has('cognac', 'tan leather', 'brown leather', 'leather')) main = ['leather', '#8b5a2b'];
    else if (has('boucle', 'bouclé', 'sheepskin', 'shearling')) main = ['boucle', '#e8e2d6'];
    else if (has('velvet')) main = ['velvet', has('green') ? '#3f5a48' : has('blue') ? '#30405a' : '#7a4a4a'];
    else if (has('glass')) main = ['glass', '#dfe8ee'];
    else if (has('opal', 'diffuser')) main = ['glass_opal', '#f4f1ea'];
    else if (has('marble')) main = ['marble', '#d8d4cc'];
    else if (has('stone', 'concrete', 'terrazzo')) main = ['stone', '#c9c4bb'];
    else if (has('brass', 'gold')) main = ['metal_brass', '#c8a24a'];
    else if (has('chrome', 'stainless', 'steel', 'aluminium', 'aluminum', 'metal')) main = ['metal_chrome', '#b8bcc0'];
    else if (has('white', 'off-white', 'cream', 'ivory')) main = [has('lamp', 'light', 'pendant') ? 'glass_opal' : has('sofa', 'chair', 'bed', 'pouf', 'ottoman') ? 'fabric' : 'lacquer', '#f1ede6'];
    else if (has('black', 'charcoal', 'anthracite')) main = [has('sofa', 'chair', 'bed') ? 'fabric' : 'metal_black', '#24262a'];
    else if (has('grey', 'gray')) main = ['fabric', '#8d8f93'];
    else if (has('green', 'sage', 'olive')) main = ['fabric', '#6f7f62'];
    else if (has('blue', 'navy')) main = ['fabric', '#3d5370'];
    else if (has('beige', 'sand', 'linen', 'fabric', 'wool', 'upholster', 'textile', 'sofa', 'armchair', 'pouf', 'ottoman', 'bed', 'rug')) main = ['fabric', '#c9bca6'];
    else if (has('lamp', 'light', 'pendant')) main = ['glass_opal', '#f1ede6'];
    else main = ['plastic', '#b9b2a6'];   // neutral warm grey, never black
    return { finish: main[0], hex: main[1], secondary: legs[0], secondaryHex: legs[1], color: parseInt(main[1].slice(1), 16), roughness: 0.7, metalness: 0 };
  }
  // Finish classes (palette/BRIEF.md) -> PBR parameters. Lamp shades glow a little so lamps read as lamps.
  static FINISH = {
    fabric: { roughness: 0.92, metalness: 0, bump: 'fabric' }, boucle: { roughness: 0.95, metalness: 0, bump: 'boucle' }, velvet: { roughness: 0.75, metalness: 0, sheen: 0.6 },
    leather: { roughness: 0.42, metalness: 0, clearcoat: 0.15 }, wood_light: { roughness: 0.55, metalness: 0 }, wood_mid: { roughness: 0.5, metalness: 0 }, wood_dark: { roughness: 0.5, metalness: 0 }, wood_black: { roughness: 0.45, metalness: 0 },
    metal_chrome: { roughness: 0.12, metalness: 1, color: '#d9d9d9' }, metal_black: { roughness: 0.4, metalness: 0.85 }, metal_brass: { roughness: 0.28, metalness: 1 }, metal_white: { roughness: 0.45, metalness: 0.3 }, metal_painted: { roughness: 0.45, metalness: 0.35 },
    plastic: { roughness: 0.4, metalness: 0 }, glass: { roughness: 0.05, metalness: 0, transparent: true, opacity: 0.35 }, glass_opal: { roughness: 0.55, metalness: 0, glow: 0.55 }, paper: { roughness: 0.85, metalness: 0, glow: 0.35 },
    marble: { roughness: 0.25, metalness: 0 }, stone: { roughness: 0.6, metalness: 0 }, concrete: { roughness: 0.85, metalness: 0 }, ceramic: { roughness: 0.3, metalness: 0 }, lacquer: { roughness: 0.18, metalness: 0, clearcoat: 0.6 },
    rattan: { roughness: 0.9, metalness: 0 }, cork: { roughness: 0.95, metalness: 0 }, rubber: { roughness: 0.8, metalness: 0 } };
  static LAMP = new Set(['pendant_lamp', 'table_lamp', 'floor_lamp']);
  static _data() {   // palette.json (Haiku's reading of each hero photo) and brand_textures.json (Muuto/Hem/Carl Hansen texture packs), fetched once
    if (!Furnish._dataP) Furnish._dataP = Promise.all([fetch('/furnish/designer/palette.json').then(r => r.ok ? r.json() : {}).catch(() => ({})), fetch('/furnish/designer/brand_textures.json').then(r => r.ok ? r.json() : {}).catch(() => ({})), fetch('/furnish/designer/orient.json').then(r => r.ok ? r.json() : {}).catch(() => ({})), fetch('/api/gallery_flags').then(r => r.ok ? r.json() : {}).catch(() => ({}))]).then(([p, b, o, f]) => ({ palette: p, brand: b, orient: o, flags: f }));
    return Furnish._dataP;
  }
  _matFor(finish, hex, sheen, isLamp) {
    const f = Furnish.FINISH[finish] || { roughness: 0.6, metalness: 0 };
    const rough = Math.min(1, Math.max(0.03, f.roughness + (sheen === 'matte' ? 0.12 : sheen === 'gloss' ? -0.2 : 0)));
    const m = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(f.color || hex || '#b9b2a6'), roughness: rough, metalness: f.metalness, transparent: !!f.transparent, opacity: f.opacity ?? 1, clearcoat: f.clearcoat || 0, sheen: f.sheen || 0, sheenColor: new THREE.Color(0xffffff) });
    if (f.glow && isLamp) { m.emissive = new THREE.Color(0xfff0d2); m.emissiveIntensity = f.glow; }
    if (f.bump) Furnish._bump(f.bump).then(t => { if (t) { m.normalMap = t; m.normalScale.set(0.6, 0.6); m.needsUpdate = true; } });
    return m;
  }
  static _bump(kind) {   // a CC0 weave normal map from the material library, tiled; used only on meshes that carry UVs
    Furnish._bumps = Furnish._bumps || {}; const id = kind === 'boucle' ? 'Fabric022' : 'Fabric019';
    if (!Furnish._bumps[kind]) Furnish._bumps[kind] = new Promise(res => new THREE.TextureLoader().load(`/furnish/materials/${id}/normal.jpg`, t => { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(6, 6); res(t); }, undefined, () => res(null)));
    return Furnish._bumps[kind];
  }
  _dressUntextured(root, spec) {
    let textured = false; root.traverse(o => { if (o.isMesh) { const ms = Array.isArray(o.material) ? o.material : [o.material]; if (ms.some(mm => mm && (mm.map || mm.normalMap))) textured = true; } });
    if (textured) return;
    // material groups ordered by size: the viewer assigns the photo's biggest part to the biggest group
    const groups = new Map(); const v3 = new THREE.Vector3();
    root.traverse(o => {
      if (!o.isMesh) return; if (o.geometry && !o.geometry.attributes.normal) o.geometry.computeVertexNormals();   // some manufacturer exports carry no normals; a fresh material lights black without them
      const ms = Array.isArray(o.material) ? o.material : [o.material]; const bb = new THREE.Box3().setFromObject(o); const sz = bb.getSize(v3); const vol = Math.max(1e-6, sz.x * sz.y * sz.z) / ms.length;
      ms.forEach((mm, i) => { const g = groups.get(mm) || { mat: mm, vol: 0, uses: [], uv: false }; g.vol += vol; g.uses.push([o, i]); g.uv = g.uv || !!(o.geometry && o.geometry.attributes.uv); groups.set(mm, g); });
    });
    const ordered = [...groups.values()].sort((a, b) => b.vol - a.vol); const isLamp = Furnish.LAMP.has(spec.category); const words = this._finishFor(spec); const wordFinish = words.finish || 'plastic';
    const chromatic = mm => { const c = mm && mm.color; if (!c) return false; const hsl = c.getHSL({}); return hsl.s > 0.25 && hsl.l > 0.08 && hsl.l < 0.95; };   // a real coloured MTL colour is kept
    const apply = (g, mat) => { g.uses.forEach(([o, i]) => { if (Array.isArray(o.material)) { const arr = o.material.slice(); arr[i] = mat; o.material = arr; } else o.material = mat; }); };
    const id = String(spec.id || '').split('#')[0];
    // first pass, synchronous: product words (never black); then refine from the data files when they arrive
    ordered.forEach((g, i) => apply(g, chromatic(g.mat) ? this._matFor(wordFinish, '#' + g.mat.color.getHexString(), null, isLamp) : this._matFor(i === 0 ? wordFinish : (words.secondary || wordFinish), i === 0 ? words.hex : (words.secondaryHex || words.hex), null, isLamp)));
    root.userData.dressed = 'words';
    Furnish._data().then(({ palette, brand }) => {
      const bt = brand[id]; const pal = palette[id];
      if (bt && bt.has_uv && !bt.multi_material && ordered.length) {   // the manufacturer's own texture for the default colourway
        const def = (bt.variants || []).find(v => v.name === bt.default) || (bt.variants || [])[0];
        if (def) { const mat = this._matFor(def.finish || wordFinish, def.mean_hex, null, isLamp); ordered.forEach(g => apply(g, mat));
          new THREE.TextureLoader().load(`/furnish/designer/textures/${id}.webp`, t => { t.colorSpace = THREE.SRGBColorSpace; t.flipY = false; mat.map = t; mat.color.set(0xffffff); mat.needsUpdate = true; });
          root.userData.dressed = 'brand texture'; return; }
      }
      if (pal && pal.parts && pal.parts.length) {   // the hero photo's parts, biggest first, onto the biggest material groups
        ordered.forEach((g, i) => { const part = pal.parts[Math.min(i, pal.parts.length - 1)]; if (chromatic(g.mat) && i > 0) return; apply(g, this._matFor(part.finish, part.hex, pal.sheen, isLamp)); });
        root.userData.dressed = 'photo palette'; return;
      }
      if (bt && bt.variants && bt.variants.length && ordered.length) {   // multi-material pack: exact colour of the default variant on the main part
        const def = bt.variants.find(v => v.name === bt.default) || bt.variants[0]; apply(ordered[0], this._matFor(def.finish || wordFinish, def.mean_hex, null, isLamp)); root.userData.dressed = 'brand colour';
      }
    });
  }

  // ---------- persistence ----------
  toPlan() { return { room: this.room, items: this.items.map(it => ({ ...it.spec, x: +it.spec.x.toFixed(3), z: +it.spec.z.toFixed(3), rot_deg: Math.round(it.spec.rot_deg) })), total_usd: +this.items.reduce((s, it) => s + (+it.spec.price_usd || 0), 0).toFixed(2) }; }
  _touch() { this.dirty = true; clearTimeout(this.saveTimer); this.saveTimer = setTimeout(() => this.save(), 2000); const s = this.panelEl?.querySelector('#fstatus'); if (s) s.textContent = 'unsaved'; }
  async save() { if (!this.room) return; try { const r = await fetch(`/api/furnish?room=${encodeURIComponent(this.room)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this.toPlan()) }); this.dirty = !r.ok; this.toast(r.ok ? 'saved' : 'save failed'); } catch (e) { this.toast('save failed'); } const s = this.panelEl?.querySelector('#fstatus'); if (s) s.textContent = this.dirty ? 'unsaved' : 'saved'; }
  async auto() { try { const r = await fetch(`/api/furnish/auto?room=${encodeURIComponent(this.room)}`); if (!r.ok) { this.toast(r.status === 404 ? 'auto-arrange not available yet' : 'auto-arrange failed'); return; } await this.loadPlan(); this.toast('auto-arranged'); } catch (e) { this.toast('auto-arrange failed'); } }
  toast(msg) { if (!this.toastEl) return; this.toastEl.textContent = msg; this.toastEl.style.opacity = 1; clearTimeout(this._tt); this._tt = setTimeout(() => this.toastEl.style.opacity = 0, 1800); }

  // ---------- input ----------
  _pick(ev) { const r = this.renderer.domElement.getBoundingClientRect(); const m = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1); this.ray.setFromCamera(m, this.camera);
    const hits = this.ray.intersectObjects(this.group.children, true); for (const h of hits) { let o = h.object; while (o && !o.userData.item) o = o.parent; if (o && o.userData.item) return o.userData.item; } return null; }
  _floorPoint(ev) { const r = this.renderer.domElement.getBoundingClientRect(); const m = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1); this.ray.setFromCamera(m, this.camera); const p = new THREE.Vector3(); return this.ray.ray.intersectPlane(this.floor, p) ? p : null; }
  _bind() {
    const el = this.renderer.domElement;
    el.addEventListener('pointerdown', ev => { if (ev.button !== 0 || !this.active) return; const it = this._pick(ev); if (!it) { if (this.selected && ev.target === el) { /* keep selection; orbit */ } return; }
      const p = this._floorPoint(ev); if (!p) return; this.select(it); this.drag = { it, off: new THREE.Vector2(it.spec.x - p.x, it.spec.z - p.z) }; this.controls.enabled = false; el.setPointerCapture(ev.pointerId); });
    el.addEventListener('pointermove', ev => { if (!this.drag) return; const p = this._floorPoint(ev); if (!p) return; this._shift = ev.shiftKey; let [x, z] = this.snap(this.drag.it, p.x + this.drag.off.x, p.z + this.drag.off.y); this._place(this.drag.it, x, z, this.drag.it.spec.rot_deg); this._refresh(); });
    const up = ev => { if (!this.drag) return; this.drag = null; this.controls.enabled = true; this._touch(); };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    addEventListener('keydown', ev => { if (!this.active || (ev.target && /INPUT|TEXTAREA|SELECT/.test(ev.target.tagName))) return; const it = this.selected; if (!it) return; this._shift = ev.shiftKey;
      const rot = d => { this._place(it, it.spec.x, it.spec.z, it.spec.rot_deg + d); this._refresh(); this._touch(); };
      const nud = (dx, dz) => { const [x, z] = this.snap(it, it.spec.x + dx, it.spec.z + dz); this._place(it, x, z, it.spec.rot_deg); this._refresh(); this._touch(); };
      switch (ev.key) { case 'r': case 'R': rot(90); break; case '[': rot(-15); break; case ']': rot(15); break;
        case 'ArrowLeft': nud(-0.05, 0); ev.preventDefault(); break; case 'ArrowRight': nud(0.05, 0); ev.preventDefault(); break; case 'ArrowUp': nud(0, -0.05); ev.preventDefault(); break; case 'ArrowDown': nud(0, 0.05); ev.preventDefault(); break;
        case 'Delete': case 'Backspace': this.remove(it); ev.preventDefault(); break; case 'd': case 'D': this.duplicate(it); break; case 'Escape': this.select(null); break; } });
  }
}
