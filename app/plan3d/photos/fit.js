// Deterministic photo cameras by analysis-by-synthesis (no model calls). The apartment is rendered as a LABEL image
// (floor 1, ceiling 2, wall 3, window 4, door 5, fixture 7: the same classes as the listing photos' Mask2Former
// segmentation, pipeline2/seg.py) into a 360-degree panorama from candidate standpoints on a grid in every room. A photo's
// label image is compared with every standpoint x yaw x pitch x lens; a yaw is just a column shift in the panorama, so
// one standpoint tests hundreds of poses cheaply. Coarse grid -> top candidates -> local refinement (position, eye height,
// angles, lens) at a finer resolution. Driven by photos/fitcams.py through window.fit.run(photos).
import * as THREE from 'three';
import { Apartment, MaterialLib } from '../build.js';

const Q = new URLSearchParams(location.search), unit = Q.get('unit');
const PW = 256, PH = 128, ELEV = 64 * Math.PI / 180;            // panorama: 1.4 deg per column, rows cover -64..+64 deg
const NV = 8, VW = 48, VH = 192;                                 // perspective views stitched into each panorama
const VHF = 2 * Math.atan(Math.tan(Math.PI / NV) * 1.08);        // each view a little wider than its 45-degree slice
const VVF = 2 * Math.atan(Math.tan(ELEV) / Math.cos(Math.PI / NV) * 1.04);
const W8 = { 1: 1, 2: 1, 3: 0.6, 4: 2, 7: 0.5 };               // floor, ceiling, wall, opening (window or door), fixture

const renderer = new THREE.WebGLRenderer({ antialias: false }); renderer.setSize(64, 64);
renderer.outputColorSpace = THREE.LinearSRGBColorSpace; renderer.toneMapping = THREE.NoToneMapping;
const scene = new THREE.Scene(); scene.background = new THREE.Color(4 / 255, 0, 0);   // seen through a window = outside = window
const lib = await new MaterialLib('/furnish/materials/').load(); lib.lowQuality = true;
const layout = await (await fetch(`/plan3d/layouts/${unit}.json`)).json();
const apt = new Apartment(layout, lib); scene.add(apt.group);
const mat = {}; const M = l => (mat[l] ||= new THREE.MeshBasicMaterial({ color: new THREE.Color(l / 255, 0, 0), side: THREE.DoubleSide }));
function kindOf(o) { for (let p = o; p; p = p.parent) { const k = p.userData && p.userData.kind; if (k === 'door' || k === 'window' || k === 'fixture') return k; } return o.userData && o.userData.kind; }
apt.group.traverse(o => {
  if (o.isSprite || o.isLight) { o.visible = false; return; }
  if (!o.isMesh) return; const k = kindOf(o);
  o.material = M(/^pfloor_/.test(o.name) ? 1 : k === 'ceiling' ? 2 : k === 'door' ? 5 : k === 'window' ? (o.name === 'pglass' ? 4 : 3) : k === 'fixture' ? 7 : 3);
});
apt.ceilingMeshes.forEach(m => { m.visible = true; m.material = M(2); });
const rt = new THREE.WebGLRenderTarget(VW, VH, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true });
const cam = new THREE.PerspectiveCamera(VVF * 180 / Math.PI, VW / VH, 0.05, 60);
const views = []; const buf = new Uint8Array(VW * VH * 4);

// panorama lookup: for every panorama pixel, which view and which view pixel
const LUT = new Int32Array(PW * PH);
{ const tH = Math.tan(VHF / 2), tV = Math.tan(VVF / 2);
  for (let r = 0; r < PH; r++) { const el = ELEV - (r + 0.5) / PH * 2 * ELEV;
    for (let c = 0; c < PW; c++) { const az = (c + 0.5) / PW * 2 * Math.PI;   // walk convention: 0 = +z, 90 = +x
      const k = Math.round(az / (2 * Math.PI / NV)) % NV, off = az - k * 2 * Math.PI / NV;
      const x = -Math.tan(off) / tH, y = Math.tan(el) / Math.cos(off) / tV;   // larger azimuth = toward the view's left
      const px = Math.min(VW - 1, Math.max(0, Math.floor((x * 0.5 + 0.5) * VW))), py = Math.min(VH - 1, Math.max(0, Math.floor((y * 0.5 + 0.5) * VH)));
      LUT[r * PW + c] = k * VW * VH + py * VW + px; } } }
function panorama(x, y, z) {
  const all = new Uint8Array(NV * VW * VH);
  for (let k = 0; k < NV; k++) {
    const a = k * 2 * Math.PI / NV; cam.position.set(x, y, z); cam.up.set(0, 1, 0); cam.lookAt(x + Math.sin(a), y, z + Math.cos(a));
    renderer.setRenderTarget(rt); renderer.render(scene, cam); renderer.readRenderTargetPixels(rt, 0, 0, VW, VH, buf);
    for (let i = 0; i < VW * VH; i++) all[k * VW * VH + i] = buf[i * 4];
  }
  renderer.setRenderTarget(null);
  const P = new Uint8Array(PW * PH); for (let i = 0; i < P.length; i++) P[i] = all[LUT[i]]; return P;
}

// photo ray tables: per (pitch, lens), each photo pixel's panorama row and column at yaw 0
function rays(w, h, pitch, hfov, aspect) {
  const rows = new Int16Array(w * h), cols = new Int16Array(w * h), t = Math.tan(hfov / 2), tv = t / aspect, cp = Math.cos(pitch), sp = Math.sin(pitch);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const u = ((i + 0.5) / w * 2 - 1) * t, v = (1 - (j + 0.5) / h * 2) * tv;
    // camera at yaw 0 looking +z, pitched: forward (0, sp, cp), up (0, cp, -sp), right = forward x up = (-1, 0, 0)
    const dx = -u, dy = sp + v * cp, dz = cp - v * sp;
    const el = Math.atan2(dy, Math.hypot(dx, dz)), az = Math.atan2(dx, dz);
    const r = Math.floor((ELEV - el) / (2 * ELEV) * PH), c = Math.floor(((az / (2 * Math.PI)) % 1 + 1) % 1 * PW);
    rows[j * w + i] = r < 0 || r >= PH ? -1 : r; cols[j * w + i] = c;
  }
  return { rows, cols };
}
// weighted IoU over the classes, photo pixels of other / furniture / mirror ignored (they hide the room)
// photo segmentation confuses windows and doors (sea views come out as "door"): both count as one class, an opening.
// Cabinets and counters are "fixture" in photos but mostly absent from our model: a photo fixture in front of our wall is fine.
const CL = [1, 2, 3, 4, 7], OPEN = c => (c === 5 ? 4 : c);
function scorePose(P, lab, R, shift, strict = false) {
  const inter = new Float32Array(8), uni = new Float32Array(8);
  for (let i = 0; i < lab.length; i++) {
    const a = OPEN(lab[i]); if (!W8[a]) continue;
    const r = R.rows[i]; if (r < 0) continue; const b = OPEN(P[r * PW + ((R.cols[i] + shift) & (PW - 1))]);
    if (a === b || (!strict && a === 7 && b === 3)) { inter[a]++; uni[a]++; } else { uni[a]++; if (W8[b] && (strict || b !== 7)) uni[b]++; }
  }
  let s = 0, ws = 0; for (const c of CL) if (uni[c] > 0) { s += W8[c] * inter[c] / uni[c]; ws += W8[c]; } return ws ? s / ws : 0;
}
function inPoly(x, z, P) { let k = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const [xi, zi] = P[i], [xj, zj] = P[j]; if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi) k = !k; } return k; }
function edgeDist(x, z, P) { let m = 1e9; for (let i = 0; i < P.length; i++) { const [ax, az] = P[i], [bx, bz] = P[(i + 1) % P.length], dx = bx - ax, dz = bz - az, t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1))); m = Math.min(m, Math.hypot(x - ax - t * dx, z - az - t * dz)); } return m; }
const fixtureRooms = new Set((layout.fixtures || []).filter(f => f.rect && !/closet|rod|shelf/.test(f.type)).map(f => (layout.rooms.find(r => inPoly(f.rect.x, f.rect.z, r.polygon)) || {}).id));
function standpoints(step) {
  const out = []; for (const r of layout.rooms) {
    if ((r.area_m2 || 0) < 2.5 || /closet/i.test(`${r.type} ${r.name}`)) continue;
    const xs = r.polygon.map(p => p[0]), zs = r.polygon.map(p => p[1]);
    for (let x = Math.min(...xs) + step / 2; x < Math.max(...xs); x += step) for (let z = Math.min(...zs) + step / 2; z < Math.max(...zs); z += step)
      if (inPoly(x, z, r.polygon) && edgeDist(x, z, r.polygon) > 0.3) out.push({ x, z, room: r.id });
  }
  return out;
}
const roomAt = (x, z) => (layout.rooms.find(r => inPoly(x, z, r.polygon)) || {}).id;

window.fit = { ready: true, rooms: layout.rooms.map(r => ({ id: r.id, name: r.name })),
  /** photos: [{id, w, h, aspect, labels:[...]}, ...] coarse labels; fine: same at higher res as {fw, fh, flabels} */
  async run(photos, { step = 0.5, eye = 1.5, top = 4 } = {}) {
    const t0 = performance.now(), S = standpoints(step);
    const pitches = [-14, -8, -2, 4].map(d => d * Math.PI / 180), lenses = [55, 65, 78, 92].map(d => d * Math.PI / 180);
    const pans = S.map(s => panorama(s.x, eye, s.z));
    const results = [];
    for (const ph of photos) {
      const lab = Uint8Array.from(ph.labels), tables = [], strict = !!ph.fixtureHeavy;
      const SI = S.map((s, i) => i).filter(i => !strict || fixtureRooms.has(S[i].room)); if (!SI.length) { results.push({ id: ph.id, score: 0, coarse: 0, room: null }); continue; }
      for (const p of pitches) for (const f of lenses) tables.push({ p, f, R: rays(ph.w, ph.h, p, f, ph.aspect) });
      const best = [];   // keep the top candidates over all standpoints
      for (const si of SI) for (const T of tables) for (let sh = 0; sh < PW; sh += 4) {
        const sc = scorePose(pans[si], lab, T.R, sh, strict); if (best.length < top * 6 || sc > best[best.length - 1].sc) {
          best.push({ sc, si, p: T.p, f: T.f, sh }); best.sort((a, b) => b.sc - a.sc); if (best.length > top * 6) best.pop(); } }
      // distinct candidates (different standpoint or direction), then refine each locally at the fine resolution
      const seeds = []; for (const b of best) if (!seeds.some(s => s.si === b.si && Math.abs(((s.sh - b.sh + PW / 2) % PW) - PW / 2) < 12)) { seeds.push(b); if (seeds.length >= top) break; }
      const flab = Uint8Array.from(ph.flabels); let win = null;
      for (const sd of seeds) {
        let cur = { x: S[sd.si].x, z: S[sd.si].z, y: eye, p: sd.p, f: sd.f, sh: sd.sh };
        let P = panorama(cur.x, cur.y, cur.z), sc = scorePose(P, flab, rays(ph.fw, ph.fh, cur.p, cur.f, ph.aspect), cur.sh, strict);
        for (const [dx, dz, dy, dp, df, dsh, n] of [[0.25, 0.25, 0.12, 3, 6, 3, 2], [0.12, 0.12, 0.06, 1.5, 3, 1, 2]]) for (let it = 0; it < n; it++) {
          // angles at this standpoint
          for (const p of [cur.p - dp * Math.PI / 180, cur.p, cur.p + dp * Math.PI / 180]) for (const f of [cur.f - df * Math.PI / 180, cur.f, cur.f + df * Math.PI / 180]) {
            if (f < 40 * Math.PI / 180 || f > 110 * Math.PI / 180) continue; const R = rays(ph.fw, ph.fh, p, f, ph.aspect);
            for (let s2 = cur.sh - dsh * 2; s2 <= cur.sh + dsh * 2; s2 += dsh) { const v = scorePose(P, flab, R, (s2 + PW) % PW, strict); if (v > sc) { sc = v; cur = { ...cur, p, f, sh: (s2 + PW) % PW }; } } }
          // standpoint and eye height
          const R = rays(ph.fw, ph.fh, cur.p, cur.f, ph.aspect);
          for (const [ox, oz, oy] of [[dx, 0, 0], [-dx, 0, 0], [0, dz, 0], [0, -dz, 0], [0, 0, dy], [0, 0, -dy]]) {
            const nx = cur.x + ox, nz = cur.z + oz, ny = Math.min(1.75, Math.max(1.2, cur.y + oy)); if (!roomAt(nx, nz)) continue;
            const P2 = panorama(nx, ny, nz), v = scorePose(P2, flab, R, cur.sh, strict); if (v > sc) { sc = v; P = P2; cur = { ...cur, x: nx, z: nz, y: ny }; } }
        }
        if (!win || sc > win.sc) win = { ...cur, sc };
      }
      // yaw: panorama column shift -> the camera's facing in the walk convention (shift moves the photo's centre column)
      const yaw = (((win.sh + 0.5) / PW * 360) % 360);
      results.push({ id: ph.id, strict, room: roomAt(win.x, win.z), pos: [+win.x.toFixed(3), +win.y.toFixed(3), +win.z.toFixed(3)], yaw: +yaw.toFixed(1),
        pitch: +(win.p * 180 / Math.PI).toFixed(1), hfov: +(win.f * 180 / Math.PI).toFixed(1), score: +win.sc.toFixed(3), coarse: +best[0].sc.toFixed(3) });
    }
    return { results, standpoints: S.length, ms: Math.round(performance.now() - t0) };
  },
  /** debug: the label render from a pose, as a data URL */
  view(pos, yaw, pitch, hfov, aspect, w = 320) {
    const h = Math.round(w / aspect), c = new THREE.PerspectiveCamera(2 * Math.atan(Math.tan(hfov * Math.PI / 360) / aspect) * 180 / Math.PI, aspect, 0.05, 60);
    const y = yaw * Math.PI / 180, p = pitch * Math.PI / 180; c.position.set(...pos); c.lookAt(pos[0] + Math.sin(y) * Math.cos(p), pos[1] + Math.sin(p), pos[2] + Math.cos(y) * Math.cos(p));
    renderer.setSize(w, h); const pal = [0x000000, 0xb08850, 0xf0f0f0, 0xc8c8c8, 0x5aa0e6, 0x3cb464, 0, 0x9050c0];
    const keep = new Map(); scene.traverse(o => { if (o.isMesh) { keep.set(o, o.material); const l = Math.round(o.material.color.r * 255); o.material = new THREE.MeshBasicMaterial({ color: pal[l] || 0x808080, side: THREE.DoubleSide }); } });
    const bg = scene.background; scene.background = new THREE.Color(pal[4]); renderer.render(scene, c); const url = renderer.domElement.toDataURL();
    for (const [o, m] of keep) o.material = m; scene.background = bg; return url;
  } };
