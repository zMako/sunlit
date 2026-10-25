// The world outside the windows (walk view): Google Photorealistic 3D Tiles placed around the apartment, which never moves.
// Measures the block with a hidden camera (height map rendered from the tiles), picks the floor (top for penthouses, else
// mid-building) and the most open facade, turns the world so the main window wall sits on that facade, carves our own
// building out of the apartment box, and applies the look: real sun for the address and time, sky, haze, bright windows,
// and the close-range rule (photogrammetry melts within ~30 m, so near surfaces dissolve into the window's bright haze).
// Without network, tiles server or budget it stays a soft sky. Spike and measurements: outside/spike.js.
import * as THREE from 'three';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { TilesRenderer } from '3d-tiles-renderer';
import { GLTFExtensionsPlugin, ReorientationPlugin } from '3d-tiles-renderer/plugins';

const D2R = Math.PI / 180, FLOOR_H = 3.2, EYE = 1.6, HF = { size: 400, res: 400 };
const TILES = (window.MOVEIN_TILES || 'http://127.0.0.1:8771') + '/v1/3dtiles/root.json';   // key-hiding, spend-capped proxy (outside/tiles_server.py)
const sleep = ms => new Promise(r => setTimeout(r, ms));

export function createOutside({ scene, camera, renderer, apt, layout, sun, hemi, lat, lon, planName = () => '', onStatus = () => {} }) {
  const aptBox = new THREE.Box3().setFromObject(apt.group), ac = aptBox.getCenter(new THREE.Vector3());
  const ext = Math.max(aptBox.max.x - aptBox.min.x, aptBox.max.z - aptBox.min.z);
  const mainWall = findMainWall(layout);
  const sky = new THREE.Group(); const skyMesh = new Sky(); skyMesh.scale.setScalar(4400); skyMesh.renderOrder = -1; sky.add(skyMesh); sky.visible = false; scene.add(sky);
  const world = new THREE.Group(); world.visible = false; scene.add(world);
  const attr = document.createElement('div'); attr.className = 'gattr'; attr.hidden = true; document.body.appendChild(attr);
  const st = { status: 'idle', enabled: false, hour: +(new URLSearchParams(location.search).get('hour') || 16.5), place: null, info: null, tiles: null, fps: 0 };
  const set = s => { st.status = s; onStatus(s); };
  const saved = { far: camera.far, near: camera.near };
  const uni = { carveMin: { value: new THREE.Vector3(1e9, 1e9, 1e9) }, carveMax: { value: new THREE.Vector3(-1e9, -1e9, -1e9) },
    nearColor: { value: new THREE.Color(1, 0.98, 0.95) }, nearIn: { value: 11 }, nearOut: { value: 34 }, nearAmt: { value: 0.97 } };
  const tint = new THREE.Color(1.12, 1.1, 1.08), tileMats = new Set();
  let H = null, G = null, basis = null;

  function start() {
    if (st.tiles || !Number.isFinite(lat) || !Number.isFinite(lon)) { if (!st.tiles) set('unavailable'); return; }
    const tiles = new TilesRenderer(TILES); st.tiles = tiles;
    tiles.registerPlugin(new GLTFExtensionsPlugin({ dracoLoader: new DRACOLoader().setDecoderPath('/vendor/three/jsm/libs/draco/gltf/') }));
    tiles.registerPlugin(new ReorientationPlugin({ lat: lat * D2R, lon: lon * D2R, height: 0, up: '+y', recenter: true }));
    tiles.errorTarget = 12; tiles.lruCache.minSize = 400; tiles.lruCache.maxSize = 900;
    tiles.setCamera(camera); tiles.setResolutionFromRenderer(camera, renderer); world.add(tiles.group);
    let errors = 0, loaded = 0;
    tiles.addEventListener('load-error', () => { if (++errors > 3 && !loaded) { set('unavailable'); world.visible = false; } });
    tiles.addEventListener('load-model', ({ scene: s }) => { loaded++; s.traverse(o => o.material && patch(o.material)); });
    tiles.addEventListener('dispose-model', ({ scene: s }) => s.traverse(o => o.material && tileMats.delete(o.material)));
    set('loading'); measureAndPlace().catch(e => { console.warn('[outside]', e); set('unavailable'); });
  }
  function patch(m) {
    tileMats.add(m); m.color.copy(tint); m.fog = true;
    if (m.map) { m.map.anisotropy = renderer.capabilities.getMaxAnisotropy(); m.map.needsUpdate = true; }
    m.onBeforeCompile = sh => {
      Object.assign(sh.uniforms, { uCarveMin: uni.carveMin, uCarveMax: uni.carveMax, uNearColor: uni.nearColor, uNearIn: uni.nearIn, uNearOut: uni.nearOut, uNearAmt: uni.nearAmt });
      sh.vertexShader = 'varying vec3 vCarveW; varying float vViewDist;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\nvCarveW = (modelMatrix * vec4(transformed, 1.0)).xyz; vViewDist = length(mvPosition.xyz);');
      sh.fragmentShader = 'uniform vec3 uCarveMin; uniform vec3 uCarveMax; uniform vec3 uNearColor; uniform float uNearIn; uniform float uNearOut; uniform float uNearAmt; varying vec3 vCarveW; varying float vViewDist;\n'
        + sh.fragmentShader.replace('void main() {', 'void main() {\nif (all(greaterThan(vCarveW, uCarveMin)) && all(lessThan(vCarveW, uCarveMax))) discard;')
          .replace('#include <fog_fragment>', 'gl_FragColor.rgb = mix(gl_FragColor.rgb, uNearColor, uNearAmt * (1.0 - smoothstep(uNearIn, uNearOut, vViewDist)));\n#include <fog_fragment>');
    };
    m.customProgramCacheKey = () => 'outside'; m.needsUpdate = true;
  }

  // ---------- measurement: a hidden camera above the block, then a top-down height map ----------
  async function settle(min, max) { const t0 = performance.now(); let ok = null;
    for (;;) { await sleep(200); const now = performance.now(), p = st.tiles.loadProgress;
      if (p >= 1) { ok ??= now; if (now - ok > 800 && now - t0 > min) return true; } else ok = null; if (now - t0 > max) return false; } }
  async function measureAndPlace() {
    const tiles = st.tiles, cam = new THREE.PerspectiveCamera(60, 1, 1, 4000); cam.position.set(0, 380, 0.01); cam.lookAt(0, 0, 0); cam.updateMatrixWorld();
    const key = 'outside:' + layout.unit, q = new URLSearchParams(location.search);
    const memo = !q.has('floor') && !q.has('remeasure') && JSON.parse(localStorage.getItem(key) || 'null');
    if (memo && memo.v === 1) {
      basis = null; world.rotation.set(0, memo.phi, 0); world.position.fromArray(memo.pos); world.updateMatrixWorld(true);
      uni.carveMin.value.fromArray(memo.cmin); uni.carveMax.value.fromArray(memo.cmax); st.place = memo.place; st.info = { floors: memo.place.floors };
      await settle(300, 4000); basis = enuBasis(tiles, lat, lon); set('ready'); apply(); return;
    }
    tiles.setCamera(cam); tiles.setResolution(cam, 900, 900); set('measuring');
    await settle(4000, 45000); await settle(1500, 15000); if (st.status === 'unavailable') return;
    const rt = new THREE.WebGLRenderTarget(HF.res, HF.res, { type: THREE.FloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
    const ortho = new THREE.OrthographicCamera(-HF.size / 2, HF.size / 2, HF.size / 2, -HF.size / 2, 1, 4000); ortho.position.set(0, 2000, 0); ortho.up.set(0, 0, -1); ortho.lookAt(0, 0, 0);
    const hm = new THREE.ShaderMaterial({ side: THREE.DoubleSide, vertexShader: 'varying float vY; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vY = w.y; gl_Position = projectionMatrix * viewMatrix * w; }',
      fragmentShader: 'varying float vY; void main(){ gl_FragColor = vec4(vY + 3000.0, 0.0, 0.0, 1.0); }' });
    const tmp = new THREE.Scene(); world.rotation.set(0, 0, 0); world.position.set(0, 0, 0); tmp.add(world); tmp.overrideMaterial = hm; world.updateMatrixWorld(true);
    const wasVis = world.visible; world.visible = true; const cc = renderer.getClearColor(new THREE.Color()), ca = renderer.getClearAlpha();
    renderer.setRenderTarget(rt); renderer.setClearColor(0x000000, 0); renderer.clear(); renderer.render(tmp, ortho);
    const px = new Float32Array(HF.res * HF.res * 4); renderer.readRenderTargetPixels(rt, 0, 0, HF.res, HF.res, px);
    renderer.setRenderTarget(null); renderer.setClearColor(cc, ca); world.visible = wasVis; scene.add(world); rt.dispose(); hm.dispose();
    tiles.deleteCamera(cam);
    H = new Float32Array(HF.res * HF.res); for (let i = 0; i < H.length; i++) H[i] = px[i * 4] > 0 ? px[i * 4] - 3000 : NaN;
    G = minFilter(H, 15); basis = enuBasis(tiles, lat, lon);
    st.info = analyse(); if (!st.info.floors) { set('unavailable'); return; }
    st.place = placeUnit(); set('ready'); apply();
    if (!q.has('floor')) localStorage.setItem(key, JSON.stringify({ v: 1, phi: world.rotation.y, pos: world.position.toArray(), cmin: uni.carveMin.value.toArray(), cmax: uni.carveMax.value.toArray(), place: st.place }));
  }
  const cell = (x, z) => { const i = Math.floor((x + HF.size / 2) / HF.size * HF.res), j = Math.floor((HF.size / 2 - z) / HF.size * HF.res); return (i < 0 || j < 0 || i >= HF.res || j >= HF.res) ? -1 : j * HF.res + i; };
  const at = (A, x, z) => { const c = cell(x, z); return c < 0 ? NaN : A[c]; };
  const xz = c => [-HF.size / 2 + (c % HF.res + 0.5) * HF.size / HF.res, HF.size / 2 - (Math.floor(c / HF.res) + 0.5) * HF.size / HF.res];
  function analyse() {   // own building: raised region nearest the geocoded point, within 35 m and 6 m of the seed's roof height
    let seed = -1, sd = Infinity;
    for (let c = 0; c < H.length; c++) { if (!(H[c] - G[c] > 4)) continue; const [x, z] = xz(c), d = Math.hypot(x, z); if (d < sd && d < 30) { sd = d; seed = c; } }
    if (seed < 0) return {};
    const foot = new Set(), h0 = H[seed], [sx, sz] = xz(seed), stack = [seed];
    while (stack.length && foot.size < 6000) { const c = stack.pop(); if (foot.has(c)) continue; const [x, z] = xz(c);
      if (!(H[c] - G[c] > 4) || Math.abs(H[c] - h0) > 6 || Math.hypot(x - sx, z - sz) > 35) continue; foot.add(c);
      for (const nc of [c - 1, c + 1, c - HF.res, c + HF.res]) if (nc >= 0 && nc < H.length && !foot.has(nc)) stack.push(nc); }
    const fc = [...foot], roof = pct(fc.map(c => H[c]), 0.8), ground = pct(fc.map(c => G[c]), 0.5);
    let cx = 0, cz = 0; for (const c of fc) { const [x, z] = xz(c); cx += x; cz += z; }
    return { roof, ground, floors: Math.max(1, Math.round((roof - ground) / FLOOR_H)), centroid: [cx / fc.length, cz / fc.length] };
  }
  function facadeAndView(theta, eyeY) {
    const ux = Math.sin(theta), uz = Math.cos(theta); const [x, z] = st.info.centroid; let out = 0, fx = x, fz = z;
    for (let s = 0; s < 120; s += 0.5) { const px = x + ux * s, pz = z + uz * s; if (at(H, px, pz) - at(G, px, pz) > 4) { fx = px; fz = pz; out = 0; } else if ((out += 0.5) > 2.5) break; }
    let open = 190; for (let s = 2; s < 190; s++) { const h = at(H, fx + ux * s, fz + uz * s); if (!Number.isFinite(h)) break; if (h > eyeY + 1) { open = s; break; } }
    return { fx, fz, open };
  }
  function placeUnit() {
    const I = st.info, pen = /penthouse|\bph\b/i.test(planName() || ''), q = new URLSearchParams(location.search);
    const index = q.has('floor') ? Math.max(0, +q.get('floor') - 1) : pen ? I.floors - 1 : Math.max(1, Math.round(I.floors / 2) - 1);
    const floorY = I.ground + index * FLOOR_H, eyeY = floorY + EYE;
    const scan = []; for (let k = 0; k < 36; k++) scan.push({ theta: k * 10 * D2R, ...facadeAndView(k * 10 * D2R, eyeY) });
    const score = k => (scan[(k + 35) % 36].open + 2 * scan[k].open + scan[(k + 1) % 36].open) / 4;
    let bk = 0; for (let k = 1; k < 36; k++) if (score(k) > score(bk)) bk = k;
    const b = scan[bk], u = new THREE.Vector2(Math.sin(b.theta), Math.cos(b.theta)), n = mainWall.n;
    const phi = Math.atan2(n.x, n.y) - Math.atan2(u.x, u.y);
    const F = new THREE.Vector3(b.fx, 0, b.fz).applyAxisAngle(new THREE.Vector3(0, 1, 0), phi);
    world.rotation.set(0, phi, 0); world.position.set(mainWall.outer.x - F.x, -floorY, mainWall.outer.y - F.z); world.updateMatrixWorld(true);
    uni.carveMin.value.set(aptBox.min.x - 0.8, -60, aptBox.min.z - 0.8); uni.carveMax.value.set(aptBox.max.x + 0.8, (layout.ceiling_m || 2.6) + 0.6, aptBox.max.z + 0.8);
    const heading = ((Math.atan2(u.x * basis.east.x + u.y * basis.east.z, u.x * basis.north.x + u.y * basis.north.z) / D2R) + 360) % 360;
    return { floor: index + 1, floors: I.floors, phi, heading, open: b.open, penthouse: pen };
  }

  // ---------- look: sun, sky, haze for the hour ----------
  function apply() {
    if (!st.enabled) return;
    const hh = Math.floor(st.hour), mm = Math.round((st.hour - hh) * 60);
    const s = sunENU(new Date(`2026-10-25T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00-07:00`), lat, lon);
    const B = basis || { east: new THREE.Vector3(1, 0, 0), north: new THREE.Vector3(0, 0, -1) };
    const dm = new THREE.Vector3().addScaledVector(B.east, s.east).addScaledVector(B.north, s.north).add(new THREE.Vector3(0, s.up, 0)).normalize()
      .applyAxisAngle(new THREE.Vector3(0, 1, 0), st.place ? st.place.phi : 0);
    const alt = s.altDeg, k = THREE.MathUtils.clamp((alt + 4) / 14, 0, 1), gold = THREE.MathUtils.clamp(1 - Math.abs(alt - 3) / 9, 0, 1), night = THREE.MathUtils.clamp(-alt / 6, 0, 1);
    const U = skyMesh.material.uniforms; U.sunPosition.value.copy(dm); U.turbidity.value = 4 + 6 * gold; U.rayleigh.value = 1.2 + 1.8 * gold + 1.5 * night; U.mieCoefficient.value = 0.004 + 0.004 * gold; U.mieDirectionalG.value = 0.82;
    sun.position.copy(ac).addScaledVector(dm, ext * 3); sun.target.position.copy(ac); sun.visible = alt > -1;
    sun.color.setRGB(1, 0.93 - 0.25 * gold, 0.84 - 0.42 * gold); sun.intensity = alt > 0 ? 1.3 + 2.0 * k : 0; hemi.intensity = 0.2 + 0.4 * k; scene.environmentIntensity = 0.28 + 0.32 * k;
    for (const l of apt.lights) { l.userData.base ??= l.intensity; l.intensity = alt < 6 ? l.userData.base : 0; }
    tint.setRGB(1.18 + 0.2 * gold - 0.8 * night, 1.14 - 0.1 * gold - 0.7 * night, 1.12 - 0.4 * gold - 0.45 * night); for (const m of tileMats) m.color.copy(tint);
    const fog = new THREE.Color().setRGB(0.82 + 0.15 * gold - 0.5 * night, 0.86 - 0.02 * gold - 0.5 * night, 0.92 - 0.2 * gold - 0.4 * night);
    if (scene.fog) { scene.fog.color.copy(fog); scene.fog.density = 0.0007 + 0.0003 * gold; } uni.nearColor.value.copy(fog).lerp(new THREE.Color(1, 1, 1), 0.55);
  }

  // ---------- public ----------
  const api = {
    get status() { return st.status; }, get place() { return st.place; }, get info() { return st.info; },
    enable(on) {
      st.enabled = on; sky.visible = on; world.visible = on && st.status === 'ready';
      if (on) { saved.pr = renderer.getPixelRatio(); renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5)); camera.near = 0.1; camera.far = 3000; camera.updateProjectionMatrix(); start(); apply(); }
      else { if (saved.pr) renderer.setPixelRatio(saved.pr); camera.near = saved.near; camera.far = saved.far; camera.updateProjectionMatrix(); if (scene.fog) scene.fog.density = 0; attr.hidden = true; for (const l of apt.lights) if (l.userData.base != null) l.intensity = l.userData.base; }
    },
    setTime(hour) { st.hour = hour; apply(); },
    windowYaw() { return Math.atan2(mainWall.n.x, mainWall.n.y) / D2R; },   // walk convention: 0 looks +z, 90 looks +x
    get hour() { return st.hour; },
    update() {   // call every frame while enabled
      if (!st.enabled || !st.tiles) return;
      world.visible = st.status === 'ready'; camera.updateMatrixWorld(); st.tiles.update();
      if (st.status === 'ready' && (api._t = (api._t || 0) + 1) % 30 === 0) {
        const a = (st.tiles.getAttributions?.() || []).map(x => x.value).filter(v => typeof v === 'string');
        attr.innerHTML = `<b>Google</b> ${[...new Set(a)].join(' · ') || 'Map data ©2026 Google'}`; attr.hidden = false;
      }
    },
    stats() { const t = st.tiles; return t ? { status: st.status, visibleTiles: t.visibleTiles?.size, downloading: t.stats?.downloading, parsing: t.stats?.parsing, progress: t.loadProgress, materials: tileMats.size, triangles: renderer.info.render.triangles, calls: renderer.info.render.calls, place: st.place } : { status: st.status }; },
  };
  return api;
}

function findMainWall(layout) {   // the wall with the most window; outward normal points away from the nearest room centre
  const byWall = {}; for (const o of layout.openings) if (o.type === 'window') byWall[o.wall] = (byWall[o.wall] || 0) + (o.width_m || (o.s1 - o.s0));
  let best = null; for (const w of layout.walls) { const ww = byWall[w.id] || 0; if (ww > 0 && (!best || ww > best.ww)) best = { w, ww }; }
  if (!best) best = { w: layout.walls[0], ww: 0 };
  const w = best.w, a = new THREE.Vector2(...w.a), b = new THREE.Vector2(...w.b), d = b.clone().sub(a).normalize(), n = new THREE.Vector2(-d.y, d.x), mid = a.clone().add(b).multiplyScalar(0.5);
  let near = null, nd = Infinity; for (const r of layout.rooms) { const c = r.polygon.reduce((s, p) => s.add(new THREE.Vector2(p[0], p[1])), new THREE.Vector2()).multiplyScalar(1 / r.polygon.length); const dd = c.distanceTo(mid); if (dd < nd) { nd = dd; near = c; } }
  if (near && near.clone().sub(mid).dot(n) > 0) n.negate();
  return { n, outer: mid.clone().add(n.clone().multiplyScalar((w.thickness_m || 0.15) / 2)) };
}
function enuBasis(tiles, latDeg, lonDeg) {   // north and east as horizontal directions in the reoriented (world-at-identity) frame
  const la = latDeg * D2R, lo = lonDeg * D2R;
  const P = (a, b) => tiles.ellipsoid.getCartographicToPosition(a, b, 0, new THREE.Vector3()).applyMatrix4(tiles.group.matrix);
  const p0 = P(la, lo), north = P(la + 1e-6, lo).sub(p0).setY(0).normalize(), east = P(la, lo + 1e-6).sub(p0).setY(0).normalize();
  return { north, east };
}
function minFilter(A, r) {
  const n = HF.res, T = new Float32Array(A.length), O = new Float32Array(A.length);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) { let m = Infinity; for (let k = Math.max(0, i - r); k <= Math.min(n - 1, i + r); k++) { const v = A[j * n + k]; if (v < m) m = v; } T[j * n + i] = m; }
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { let m = Infinity; for (let k = Math.max(0, j - r); k <= Math.min(n - 1, j + r); k++) { const v = T[k * n + i]; if (v < m) m = v; } O[j * n + i] = m; }
  return O;
}
function pct(arr, p) { const s = arr.filter(Number.isFinite).sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : NaN; }
function sunENU(date, LAT, LON) {   // suncalc (BSD): azimuth from south toward west
  const d = date.valueOf() / 864e5 - 0.5 + 2440588 - 2451545, e = D2R * 23.4397;
  const M = D2R * (357.5291 + 0.98560028 * d), C = D2R * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)), L = M + C + D2R * 102.9372 + Math.PI;
  const dec = Math.asin(Math.sin(e) * Math.sin(L)), ra = Math.atan2(Math.sin(L) * Math.cos(e), Math.cos(L));
  const H = D2R * (280.16 + 360.9856235 * d) + D2R * LON - ra, phi = LAT * D2R;
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi)), alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
  return { east: -Math.sin(az) * Math.cos(alt), north: -Math.cos(az) * Math.cos(alt), up: Math.sin(alt), altDeg: alt / D2R };
}
