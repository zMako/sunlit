// Walls, ceilings and the small things on them, for the customer apartment page.
//  - tone: the chosen style's palette, per room type (living spaces full, bedrooms softer, kitchens and baths crisp), nudged
//    toward each room's wall colour measured in the listing photos (layout.materials.wall_rgb); one accent wall in the main
//    room. Each wall face takes the tone of the room it faces (box face materials), so a shared wall can differ per side.
//  - texture: painted-plaster relief from the CC0 library (normal + roughness only, the colour stays ours), finer on ceilings.
//  - light across surfaces: a shader term on walls and ceilings (no extra lights): daylight glow that falls off with
//    distance from the windows in front of the surface, warm bounce from the floor onto the ceiling and lower walls, and a
//    soft darkening just under the ceiling. Driven per view and mood by setLight().
//  - crafted details: crown moulding along every wall top that faces a room, light switches beside doors, outlets along free
//    wall stretches, one thermostat. Merged into three meshes; clipped with the rest in the overview.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const STYLE = {   // base wall tone, accent tone (chalky paints)
  'warm scandinavian': ['#ede6dc', '#c8b6a0'], 'japandi': ['#ebe4d9', '#b5987c'], 'mid-century modern': ['#eee7db', '#7f8d70'],
  'quiet minimal': ['#f0eee9', '#d6d1c7'], 'coastal': ['#eef0ec', '#9fb6bf'], default: ['#ece7df', '#cbbba8'],
};
const RELIEF = 'PaintedPlaster006', CEILING = '#f7f2ea';
const LIGHT = {   // per view and mood: window glow colour * strength, floor bounce colour * strength, ceiling-line darkening
  'walk:golden': { win: [1.0, 0.72, 0.48], wi: 0.28, bounce: [1.0, 0.68, 0.45], bi: 0.24, edge: 0.2 },
  'walk:day':    { win: [0.9, 0.95, 1.0], wi: 0.32, bounce: [1.0, 0.88, 0.76], bi: 0.34, edge: 0.16 },
  'doll:golden': { win: [1.0, 0.75, 0.52], wi: 0.15, bounce: [1.0, 0.72, 0.5], bi: 0.08, edge: 0 },
  'doll:day':    { win: [0.92, 0.95, 1.0], wi: 0.12, bounce: [1.0, 0.88, 0.75], bi: 0.06, edge: 0 },
};
const MAXW = 16;

export function createSurfaces({ apt, layout, lib }) {
  const rooms = layout.rooms, levels = layout.levels && layout.levels.length > 1 ? layout.levels : null;
  const elev = k => levels ? ((levels.find(v => v.id === (k || 0)) || {}).elevation_m || 0) : 0;
  const inPoly = (x, z, P) => { let k = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const [xi, zi] = P[i], [xj, zj] = P[j]; if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi) k = !k; } return k; };
  const roomAt = (x, z, level = 0) => rooms.find(r => (r.level || 0) === (level || 0) && inPoly(x, z, r.polygon)) || null;
  const levelOf = o => { for (let p = o; p; p = p.parent) if (p.userData && p.userData.level != null) return p.userData.level; return 0; };
  const frame = w => { const a = new THREE.Vector2(...w.a), b = new THREE.Vector2(...w.b), d = b.clone().sub(a); const len = d.length() || 1; d.divideScalar(len); return { a, d, n: new THREE.Vector2(-d.y, d.x), len, t: w.thickness_m || 0.15, angle: -Math.atan2(d.y, d.x) }; };

  // ---------- shared light uniforms + the shader term ----------
  const U = { uWin: { value: Array.from({ length: MAXW }, () => new THREE.Vector4()) }, uWinN: { value: Array.from({ length: MAXW }, () => new THREE.Vector3()) },
    uWinCount: { value: 0 }, uWinCol: { value: new THREE.Color() }, uBounce: { value: new THREE.Color() }, uCeil: { value: apt.ceil }, uEdge: { value: 0 }, uLevelH: { value: levels ? Math.max(apt.ceil + 0.1, levels[1].elevation_m - levels[0].elevation_m) : 1e4 } };
  const ALL = [];
  { let k = 0; const walls = new Map(layout.walls.map(w => [w.id, w]));   // windows: centre, size weight, normal into the room
    for (const o of layout.openings) { if (o.type !== 'window' || k >= MAXW) continue; const w = walls.get(o.wall); if (!w) continue; const f = frame(w);
      const m = f.a.clone().add(f.d.clone().multiplyScalar((o.s0 + o.s1) / 2)); let n = f.n.clone(); const probe = s => m.clone().add(f.n.clone().multiplyScalar(s * (f.t / 2 + 0.3)));
      if (!roomAt(probe(1).x, probe(1).y, w.level) && roomAt(probe(-1).x, probe(-1).y, w.level)) n.negate();
      const sill = o.sill_m ?? 0.9, h = o.height_m ?? 1.3, area = (o.s1 - o.s0) * h;
      ALL.push({ c: new THREE.Vector4(m.x, elev(w.level) + sill + h / 2, m.y, THREE.MathUtils.clamp(area / 1.5, 0.5, 2.2)), n: new THREE.Vector3(n.x, 0, n.y) }); k++; } }
  function focus(x, z, max = 6) {   // the shader loops over the windows nearest the camera only (uniform update, no recompile)
    const near = ALL.slice().sort((a, b) => Math.hypot(a.c.x - x, a.c.z - z) - Math.hypot(b.c.x - x, b.c.z - z)).slice(0, max);
    near.forEach((w, i) => { U.uWin.value[i].copy(w.c); U.uWinN.value[i].copy(w.n); }); U.uWinCount.value = near.length;
  }
  focus(0, 0, MAXW);
  function patch(mat) {
    mat.onBeforeCompile = sh => {
      Object.assign(sh.uniforms, U);
      sh.vertexShader = 'varying vec3 vGiPos; varying vec3 vGiNor;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\nvGiPos = (modelMatrix * vec4(transformed, 1.0)).xyz; vGiNor = normalize(mat3(modelMatrix) * objectNormal);');
      sh.fragmentShader = `uniform vec4 uWin[${MAXW}]; uniform vec3 uWinN[${MAXW}]; uniform int uWinCount; uniform vec3 uWinCol; uniform vec3 uBounce; uniform float uCeil; uniform float uEdge; uniform float uLevelH; varying vec3 vGiPos; varying vec3 vGiNor;\n`
        + sh.fragmentShader.replace('#include <lights_fragment_end>', `#include <lights_fragment_end>
        { vec3 Ng = normalize(vGiNor) * (gl_FrontFacing ? 1.0 : -1.0); float g = 0.0;
          for (int i = 0; i < ${MAXW}; i++) { if (i >= uWinCount) break; vec3 d = vGiPos - uWin[i].xyz; if (dot(d, uWinN[i]) < -0.05) continue;   // only surfaces in front of the window
            float dist = length(d); g += uWin[i].w * exp(-dist / 2.4) * clamp(0.3 + 0.7 * dot(Ng, -d / max(dist, 1e-3)), 0.0, 1.0); }
          float ceilF = smoothstep(0.3, 0.9, -Ng.y), hgt = clamp(mod(vGiPos.y, uLevelH) / max(uCeil, 1.0), 0.0, 1.0);
          reflectedLight.indirectDiffuse += diffuseColor.rgb * (uWinCol * min(g, 2.5) + uBounce * (ceilF + (1.0 - ceilF) * (1.0 - hgt) * 0.4));
          float edge = 1.0 - uEdge * smoothstep(0.84, 1.0, hgt) * (1.0 - ceilF);   // a soft shadow line just under the ceiling
          reflectedLight.indirectDiffuse *= edge; reflectedLight.directDiffuse *= mix(1.0, edge, 0.4); }`);
    };
    mat.customProgramCacheKey = () => 'surfaces-gi'; mat.needsUpdate = true; return mat;
  }
  function setLight(mode, mood) {
    const L = LIGHT[`${mode}:${mood}`] || LIGHT['doll:day'];
    U.uWinCol.value.setRGB(...L.win).multiplyScalar(L.wi); U.uBounce.value.setRGB(...L.bounce).multiplyScalar(L.bi); U.uEdge.value = L.edge;
  }

  // ---------- materials ----------
  const relief = (() => { try { const n = lib._tex(lib.base + RELIEF + '/normal.jpg', false), r = lib._tex(lib.base + RELIEF + '/roughness.jpg', false); n.repeat.set(0.5, 0.5); r.repeat.set(0.5, 0.5); return { n, r }; } catch (e) { return null; } })();
  const template = apt.wallMeshes[0]?.material;
  const cache = new Map();
  function paint(hex, ceiling = false) {
    const key = hex + (ceiling ? 'c' : ''); if (cache.has(key)) return cache.get(key);
    const m = (template && !Array.isArray(template) ? template : new THREE.MeshStandardMaterial()).clone(); m.color.set(hex); m.roughness = ceiling ? 0.95 : 0.88;
    if (relief) { m.normalMap = relief.n; m.normalScale = new THREE.Vector2(ceiling ? 0.04 : 0.11, ceiling ? 0.04 : 0.11); m.roughnessMap = relief.r; }
    patch(m); cache.set(key, m); return m;
  }
  function tone(base, room) {
    const c = new THREE.Color(base), t = (room && room.type) || '';
    if (/bed/.test(t)) c.lerp(new THREE.Color('#ffffff'), 0.3); else if (/kitchen|bath|laundry/.test(t)) c.lerp(new THREE.Color('#f4f3ef'), 0.65); else if (/hall|entry|closet/.test(t)) c.lerp(new THREE.Color('#ffffff'), 0.15);
    const rgb = room && ((layout.materials || {}).wall_rgb || {})[room.id];
    if (Array.isArray(rgb) && rgb.length >= 3) {   // the photographed wall: its hue, gently (listing photos are dim and tungsten-warm)
      const p = new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255), hp = {}, hc = {}; p.getHSL(hp); c.getHSL(hc);
      const q = new THREE.Color().setHSL(hp.h, Math.min(hp.s * 0.35, 0.09), hc.l); c.lerp(q, 0.25);
    }
    return '#' + c.getHexString();
  }
  function applyStyle(style) {
    const [base, accent] = STYLE[String(style || '').toLowerCase()] || STYLE.default;
    // accent: the longest wall stretch without openings that faces the main room (prefer one with nothing behind it)
    const main = rooms.find(r => r.type === 'living') || [...rooms].sort((a, b) => (b.area_m2 || 0) - (a.area_m2 || 0))[0];
    const busy = new Set(layout.openings.map(o => o.wall)); let acc = null;
    for (const w of layout.walls) { if (busy.has(w.id)) continue; const f = frame(w); if (f.len < 1.8) continue;
      const m = f.a.clone().add(f.d.clone().multiplyScalar(f.len / 2)); for (const s of [1, -1]) { const p = m.clone().add(f.n.clone().multiplyScalar(s * (f.t / 2 + 0.3)));
        if (roomAt(p.x, p.y, w.level) === main) { const score = f.len + (!roomAt(m.x - f.n.x * s * (f.t / 2 + 0.3), m.y - f.n.y * s * (f.t / 2 + 0.3), w.level) ? 2 : 0); if (!acc || score > acc.score) acc = { id: w.id, side: s, score }; } } }
    const q = new THREE.Quaternion(), nz = new THREE.Vector3(), wp = new THREE.Vector3();
    for (const mesh of apt.wallMeshes) {
      mesh.getWorldQuaternion(q); nz.set(0, 0, 1).applyQuaternion(q); mesh.getWorldPosition(wp);
      const bb = mesh.geometry.boundingBox || (mesh.geometry.computeBoundingBox(), mesh.geometry.boundingBox), t = bb.max.z - bb.min.z, lv = levelOf(mesh);
      const side = s => roomAt(wp.x + nz.x * s * (t / 2 + 0.25), wp.z + nz.z * s * (t / 2 + 0.25), lv);
      const wall = layout.walls.find(w => w.id === mesh.userData.wall), f = wall ? frame(wall) : null, rp = side(1), rn = side(-1);
      const isAcc = s => acc && mesh.userData.wall === acc.id && f && (Math.sign(nz.x * f.n.x + nz.z * f.n.y) * s === acc.side);
      const face = (s, r) => paint(isAcc(s) ? accent : tone(base, r));
      // BoxGeometry index order: +x -x +y -y +z -z (6 indices each). Two draw groups at most: edges + the +z face, and the -z face
      const mp = face(rp ? 1 : -1, rp || rn), mn = face(-1, rn || rp), g = mesh.geometry;
      if (g.index && g.index.count === 36) {
        g.clearGroups();
        if (mp === mn) { mesh.material = mp; }
        else { const plusFirst = face(1, rp); g.addGroup(0, 30, 0); g.addGroup(30, 6, 1); mesh.material = [plusFirst === mp ? mp : plusFirst, mn]; }
      } else mesh.material = mp;
    }
    const ceil = paint(CEILING, true); ceil.side = THREE.DoubleSide;   // the ceiling planes are seen from below (their back)
    for (const m of apt.ceilingMeshes) if (/^pceil_/.test(m.name)) m.material = ceil;
    apt.group.traverse(o => {   // floors: the material's own roughness map stays in charge; a gentle sheen, and the grain a little deeper
      if (!/^pfloor_/.test(o.name) || !o.material || Array.isArray(o.material)) return; const m = o.material, cat = m.userData && m.userData.category; if (m.userData.amb) return; m.userData.amb = true;
      const F = { wood_floor: [0.85, 0.55, 0.85], laminate: [0.8, 0.6, 0.7], tile: [0.7, 0.75, 0.6], stone: [0.75, 0.7, 0.7], carpet: [1, 0.2, 1], concrete: [0.9, 0.4, 0.8] }[cat] || [0.9, 0.5, 0.7];
      m.roughness = m.roughnessMap ? F[0] : Math.max(m.roughness, 0.55); m.envMapIntensity = F[1]; if (m.normalMap && m.normalScale) m.normalScale.setScalar(F[2]);
      m.needsUpdate = false; });
  }

  // ---------- crown moulding: a cove profile along every wall top that faces a room ----------
  const PROF = (() => { const p = [[0, 0], [0.082, 0], [0.082, 0.011], [0.074, 0.014]]; for (let k = 1; k < 8; k++) { const a = Math.PI / 2 * k / 8; p.push([0.074 - 0.06 * Math.sin(a), 0.074 - 0.06 * Math.cos(a)]); }
    p.push([0.014, 0.074], [0.012, 0.084], [0, 0.088]); return p; })();
  function prism(L, place) {   // profile swept along local x in [-L/2, L/2]; place(d, v, x) -> world Vector3
    const pos = []; for (let k = 0; k < PROF.length - 1; k++) { const [d0, v0] = PROF[k], [d1, v1] = PROF[k + 1];
      const A = place(d0, v0, -L / 2), B = place(d0, v0, L / 2), C = place(d1, v1, L / 2), D = place(d1, v1, -L / 2);
      pos.push(...A.toArray(), ...B.toArray(), ...C.toArray(), ...A.toArray(), ...C.toArray(), ...D.toArray()); }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.computeVertexNormals(); return g;
  }
  const crown = [], crownBy = new Map();   // per parent group: level groups move between the overview and walking
  for (const mesh of apt.wallMeshes) {
    const { y0 = 0, h = 0 } = mesh.userData; if (y0 + h < apt.ceil - 0.02) continue;   // only pieces that reach the ceiling
    const bb = mesh.geometry.boundingBox || (mesh.geometry.computeBoundingBox(), mesh.geometry.boundingBox), L = bb.max.x - bb.min.x, t = bb.max.z - bb.min.z; if (L < 0.25) continue;
    const lv = levelOf(mesh), base = 0, cx = mesh.position.x, cz = mesh.position.z, ang = mesh.rotation.y, host = mesh.parent || apt.group;
    const ux = Math.cos(ang), uz = -Math.sin(ang), nx = Math.sin(ang), nzz = Math.cos(ang);   // local x and local z in world
    for (const s of [1, -1]) {
      if (!roomAt(cx + nx * s * (t / 2 + 0.25), cz + nzz * s * (t / 2 + 0.25), lv)) continue;   // faces outside: no moulding
      const g = prism(L, (d, v, x) => new THREE.Vector3(cx + ux * x + nx * s * (t / 2 + d), base + apt.ceil - v, cz + uz * x + nzz * s * (t / 2 + d)));
      crown.push(g); if (!crownBy.has(host)) crownBy.set(host, []); crownBy.get(host).push(g);
    }
  }
  const group = new THREE.Group(); group.name = 'surfaces';
  const trim = (apt.trimMat ? apt.trimMat() : new THREE.MeshStandardMaterial({ color: 0xf4f2ee, roughness: 0.6 })).clone(); trim.roughness = 0.55; trim.side = THREE.DoubleSide;
  for (const [host, list] of crownBy) { const m = new THREE.Mesh(mergeGeometries(list), trim); m.receiveShadow = true; m.userData.kind = 'trim'; m.name = 'crown'; (host === apt.group ? group : host).add(m); }

  // ---------- switches, outlets, thermostat ----------
  const plates = [], slots = [], byLevel = new Map(), plastic = new THREE.MeshStandardMaterial({ color: 0xf6f5f1, roughness: 0.32 }), dark = new THREE.MeshStandardMaterial({ color: 0x3a3a3a, roughness: 0.6 });
  const walls = layout.walls, opsOf = new Map(); for (const o of layout.openings) { if (!opsOf.has(o.wall)) opsOf.set(o.wall, []); opsOf.get(o.wall).push(o); }
  const free = (w, s, r = 0.12) => s > r && s < frame(w).len - r && !(opsOf.get(w.id) || []).some(o => s > o.s0 - r && s < o.s1 + r);
  function put(w, s, side, y, kind) {   // a small box on the wall face: kind 'switch' | 'outlet' | 'thermo'
    const f = frame(w), m = f.a.clone().add(f.d.clone().multiplyScalar(s)), yy = (apt.levelGroups && apt.levelGroups[w.level || 0] ? 0 : elev(w.level)) + y;   // level groups carry their own height
    if (!byLevel.has(w.level || 0)) byLevel.set(w.level || 0, { plates: [], slots: [] }); const L = byLevel.get(w.level || 0);
    const add = (which, bw, bh, bd, ox, oy, oz) => { const list = which === plates ? L.plates : L.slots; (which === plates ? plates : slots).push(0); const g = new THREE.BoxGeometry(bw, bh, bd); const M = new THREE.Matrix4().makeRotationY(f.angle + (side < 0 ? Math.PI : 0));
      const off = new THREE.Vector3(ox, oy, f.t / 2 + oz).applyMatrix4(M); g.applyMatrix4(M); g.translate(m.x + off.x * 1 + 0 * side, yy + off.y, m.y + off.z); list.push(g); };
    // local z of a wall frame points along n; for the -n side we turned the plate around
    if (kind === 'switch') { add(plates, 0.07, 0.115, 0.007, 0, 0, 0.0035); add(plates, 0.022, 0.04, 0.006, 0, 0, 0.009); }
    else if (kind === 'outlet') { add(plates, 0.07, 0.115, 0.007, 0, 0, 0.0035); for (const oy of [0.022, -0.022]) add(slots, 0.03, 0.022, 0.004, 0, oy, 0.0075); }
    else { add(plates, 0.085, 0.085, 0.024, 0, 0, 0.012); add(slots, 0.04, 0.022, 0.003, 0, 0.012, 0.025); }
  }
  const sideRoom = (w, s, side) => { const f = frame(w), m = f.a.clone().add(f.d.clone().multiplyScalar(s)).add(f.n.clone().multiplyScalar(side * (f.t / 2 + 0.3))); return roomAt(m.x, m.y, w.level); };
  for (const o of layout.openings) {   // a switch on the latch side of every door, on the side it opens into (or wherever a room is)
    if (o.type !== 'door') continue; const w = walls.find(x => x.id === o.wall); if (!w) continue;
    const sw = o.swing || 'in_left', pref = sw.startsWith('out') ? -1 : 1, latch = sw.endsWith('left') ? o.s1 + 0.13 : o.s0 - 0.13, other = sw.endsWith('left') ? o.s0 - 0.13 : o.s1 + 0.13;
    for (const side of [pref, -pref]) { const r = sideRoom(w, (o.s0 + o.s1) / 2, side); if (!r || /closet/.test(r.type || '')) continue;
      const s = free(w, latch) ? latch : free(w, other) ? other : null; if (s != null) { put(w, s, side, 1.2, 'switch'); break; } }
  }
  const perRoom = {};
  for (const w of walls) {   // outlets every ~3 m along free stretches facing living spaces
    const f = frame(w); if (f.len < 1.2) continue;
    for (const side of [1, -1]) { const r = sideRoom(w, f.len / 2, side); if (!r || /closet|bath|kitchen|laundry|hall|entry/.test(r.type || '')) continue;
      for (let s = 0.6; s < f.len - 0.5; s += 3.0) { if ((perRoom[r.id] || 0) >= 5 || !free(w, s, 0.35) || sideRoom(w, s, side) !== r) continue; put(w, s, side, 0.3, 'outlet'); perRoom[r.id] = (perRoom[r.id] || 0) + 1; } }
  }
  { const r = rooms.find(x => /hall|entry/.test(x.type || '')) || rooms.find(x => x.type === 'living');   // one thermostat
    if (r) outer: for (const w of walls) { const f = frame(w); for (const side of [1, -1]) for (let s = 0.5; s < f.len - 0.5; s += 0.5) if (free(w, s, 0.4) && sideRoom(w, s, side) === r) { put(w, s, side, 1.5, 'thermo'); break outer; } } }
  for (const [lv, L] of byLevel) { const host = (apt.levelGroups && apt.levelGroups[lv]) || group;
    if (L.plates.length) { const m = new THREE.Mesh(mergeGeometries(L.plates), plastic); m.name = 'wall-details'; m.castShadow = true; m.receiveShadow = true; host.add(m); }
    if (L.slots.length) { const m = new THREE.Mesh(mergeGeometries(L.slots), dark); m.name = 'wall-details-dark'; host.add(m); } }
  apt.group.add(group);

  return { applyStyle, setLight, focus, group, stats: () => ({ windows: ALL.length, inShader: U.uWinCount.value, crownPieces: crown.length, plates: plates.length, slots: slots.length }) };
}
