// Out-of-the-window spike. The apartment never moves: the Google world is placed around it.
//  1. tiles reoriented to the listing's lat/lon (+Y up), streamed through the key-hiding proxy (/v1/3dtiles, spend-capped)
//  2. a top-down height map of the block, rendered from the tiles (world y per pixel) -> ground, own building footprint, roof
//  3. floor: top floor for penthouses, else mid-building; facing: the most open view from the building's facade, scanned in
//     36 directions at that floor's eye height (one rigid turn of the world, so every window of the unit stays coherent)
//  4. the world is turned and shifted so the main window wall sits on that facade at that floor; tiles inside the apartment
//     box are discarded (our own building's mesh would fill the rooms)
//  5. look: real sun position for San Francisco at the chosen time, sky, haze, warm/cool tint on the tiles, bloom on the
//     bright window; "raw" turns all of it off to judge the photogrammetry honestly
import * as THREE from 'three';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';
import { TilesRenderer } from '3d-tiles-renderer';
import { GLTFExtensionsPlugin, ReorientationPlugin } from '3d-tiles-renderer/plugins';
import { Apartment, MaterialLib } from '../build.js';

const Q = new URLSearchParams(location.search), D2R = Math.PI / 180;
const UNIT = Q.get('unit') || 'gs-22612_plan_03', LAT = +(Q.get('lat') || 37.7989235), LON = +(Q.get('lon') || -122.4184604);
const FLOOR_H = 3.2, EYE = 1.6;
const $ = id => document.getElementById(id), sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- renderer, interior ----------
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 6000);
const pmrem = new THREE.PMREMGenerator(renderer); scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const lib = await new MaterialLib('/furnish/materials/').load();
const layout = await (await fetch(`/plan3d/layouts/${UNIT}.json`)).json();
const apt = new Apartment(layout, lib); scene.add(apt.group); apt.labels.forEach(l => l.visible = false);
const pane = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.07, roughness: 0.04, metalness: 0, depthWrite: false, side: THREE.DoubleSide });
apt.group.traverse(o => { if (o.isMesh && o.material && o.material.transmission > 0) o.material = pane; });   // transmission would render the city twice
const aptBox = new THREE.Box3().setFromObject(apt.group);

// main window wall: most window width; outward normal points away from the nearest room centre
const mainWall = (() => {
  const byWall = {}; for (const o of layout.openings) if (o.type === 'window') byWall[o.wall] = (byWall[o.wall] || 0) + (o.width_m || (o.s1 - o.s0));
  let best = null; for (const w of layout.walls) { const ww = byWall[w.id] || 0; if (ww > 0 && (!best || ww > best.ww)) best = { w, ww }; }
  const w = best.w, a = new THREE.Vector2(...w.a), b = new THREE.Vector2(...w.b), d = b.clone().sub(a).normalize(), n = new THREE.Vector2(-d.y, d.x), mid = a.clone().add(b).multiplyScalar(0.5);
  let near = null, nd = Infinity; for (const r of layout.rooms) { const c = r.polygon.reduce((s, p) => s.add(new THREE.Vector2(p[0], p[1])), new THREE.Vector2()).multiplyScalar(1 / r.polygon.length); const dd = c.distanceTo(mid); if (dd < nd) { nd = dd; near = c; } }
  if (near.clone().sub(mid).dot(n) > 0) n.negate();
  const t = w.thickness_m || 0.15;
  const win = layout.openings.filter(o => o.type === 'window' && o.wall === w.id).sort((p, q) => (q.s1 - q.s0) - (p.s1 - p.s0))[0];
  const wc = a.clone().add(d.clone().multiplyScalar((win.s0 + win.s1) / 2));   // centre of the largest window, on the wall's axis
  const inside = wc.clone().sub(n.clone().multiplyScalar(t / 2 + 0.6)), room = layout.rooms.find(r => inPoly(inside, r.polygon)) || layout.rooms[0];
  return { wall: w, n, mid, outer: mid.clone().add(n.clone().multiplyScalar(t / 2)), len: a.distanceTo(b), windowWidth: best.ww, win, wc, room,
    sillY: (win.sill_m ?? 0.9), headY: (win.sill_m ?? 0.9) + (win.height_m ?? 1.3) };
})();

function inPoly(p, P) { let k = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const [xi, zi] = P[i], [xj, zj] = P[j]; if ((zi > p.y) !== (zj > p.y) && p.x < (xj - xi) * (p.y - zi) / (zj - zi + 1e-12) + xi) k = !k; } return k; }
function roomyPoint(P) {   // grid point inside the polygon farthest from its walls
  const xs = P.map(p => p[0]), zs = P.map(p => p[1]); let best = null, bd = -1;
  const edge = (x, z) => { let m = Infinity; for (let i = 0; i < P.length; i++) { const [ax, az] = P[i], [bx, bz] = P[(i + 1) % P.length], dx = bx - ax, dz = bz - az, t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1))); m = Math.min(m, Math.hypot(x - ax - t * dx, z - az - t * dz)); } return m; };
  for (let i = 1; i < 30; i++) for (let j = 1; j < 30; j++) { const x = Math.min(...xs) + (Math.max(...xs) - Math.min(...xs)) * i / 30, z = Math.min(...zs) + (Math.max(...zs) - Math.min(...zs)) * j / 30; if (!inPoly(new THREE.Vector2(x, z), P)) continue; const d = edge(x, z); if (d > bd) { bd = d; best = new THREE.Vector2(x, z); } }
  return best;
}
// ---------- the world ----------
const world = new THREE.Group(); scene.add(world);
const tiles = new TilesRenderer('/v1/3dtiles/root.json');
const draco = new DRACOLoader().setDecoderPath('/vendor/three/jsm/libs/draco/gltf/');
tiles.registerPlugin(new GLTFExtensionsPlugin({ dracoLoader: draco }));
tiles.registerPlugin(new ReorientationPlugin({ lat: LAT * D2R, lon: LON * D2R, height: 0, up: '+y', recenter: true }));
tiles.errorTarget = 6; tiles.lruCache.minSize = 1200; tiles.lruCache.maxSize = 2400;
tiles.setCamera(camera); tiles.setResolutionFromRenderer(camera, renderer); world.add(tiles.group);

// tile materials: tint (time of day), haze (scene fog), and the carve that removes our own building inside the apartment box
const look = { tint: new THREE.Color(1, 1, 1) };
const carve = { min: { value: new THREE.Vector3(1e9, 1e9, 1e9) }, max: { value: new THREE.Vector3(-1e9, -1e9, -1e9) } };
const tileMats = new Set();
tiles.addEventListener('load-model', ({ scene: s }) => s.traverse(o => {
  if (!o.material) return; const m = o.material; tileMats.add(m);
  if (m.map) { m.map.anisotropy = renderer.capabilities.getMaxAnisotropy(); m.map.needsUpdate = true; }   // facades at grazing angles blur without it m.color.copy(look.tint); m.fog = true;
  m.onBeforeCompile = sh => {
    sh.uniforms.uCarveMin = carve.min; sh.uniforms.uCarveMax = carve.max;
    sh.vertexShader = 'varying vec3 vCarveW;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\nvCarveW = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = 'uniform vec3 uCarveMin; uniform vec3 uCarveMax; varying vec3 vCarveW;\n' + sh.fragmentShader.replace('void main() {', 'void main() {\nif (all(greaterThan(vCarveW, uCarveMin)) && all(lessThan(vCarveW, uCarveMax))) discard;');
  };
  m.customProgramCacheKey = () => 'carve'; m.needsUpdate = true;
}));
tiles.addEventListener('dispose-model', ({ scene: s }) => s.traverse(o => o.material && tileMats.delete(o.material)));

// ---------- light, sky, post ----------
const sun = new THREE.DirectionalLight(0xffffff, 3); sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096); sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.03; sun.shadow.radius = 3;
const ext = Math.max(aptBox.max.x - aptBox.min.x, aptBox.max.z - aptBox.min.z), ac = aptBox.getCenter(new THREE.Vector3());
const sc = sun.shadow.camera; sc.left = sc.bottom = -ext; sc.right = sc.top = ext; sc.near = 1; sc.far = ext * 8; sc.updateProjectionMatrix();
scene.add(sun, sun.target); sun.target.position.copy(ac);
const hemi = new THREE.HemisphereLight(0xdfe9ff, 0xf0e4d4, 0.5); scene.add(hemi);
const sky = new Sky(); sky.scale.setScalar(4400); sky.renderOrder = -1; scene.add(sky);
const composer = new EffectComposer(renderer); composer.addPass(new RenderPass(scene, camera));
const bokeh = new BokehPass(scene, camera, { focus: 4.0, aperture: 0.0022, maxblur: 0.009 }); bokeh.enabled = false; composer.addPass(bokeh);
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.32, 0.6, 0.86); composer.addPass(bloom); composer.addPass(new OutputPass());

// ---------- loop ----------
let running = true;
renderer.setAnimationLoop(() => { if (!running) return; camera.updateMatrixWorld(); tiles.update(); composer.render(); });
async function settle(min = 1500, max = 45000) {   // wait until the tiles for the current camera have streamed in
  const t0 = performance.now(); let ok = null;
  for (;;) { await sleep(200); const now = performance.now(), p = tiles.loadProgress;
    if (p >= 1) { ok ??= now; if (now - ok > 900 && now - t0 > min) return true; } else ok = null;
    if (now - t0 > max) return false; }
}

// ---------- geography: ENU basis in the measurement frame (world group at identity) ----------
function enuBasis() {
  const P = (la, lo) => tiles.ellipsoid.getCartographicToPosition(la * D2R, lo * D2R, 0, new THREE.Vector3()).applyMatrix4(tiles.group.matrix);
  const p0 = P(LAT, LON), north = P(LAT + 1e-4, LON).sub(p0).setY(0).normalize(), east = P(LAT, LON + 1e-4).sub(p0).setY(0).normalize();
  return { north, east };
}
function sunENU(date) {   // suncalc's solar position (BSD), azimuth measured from south toward west
  const J1970 = 2440588, J2000 = 2451545, d = date.valueOf() / 864e5 - 0.5 + J1970 - J2000, e = D2R * 23.4397;
  const M = D2R * (357.5291 + 0.98560028 * d), C = D2R * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)), L = M + C + D2R * 102.9372 + Math.PI;
  const dec = Math.asin(Math.sin(e) * Math.sin(L)), ra = Math.atan2(Math.sin(L) * Math.cos(e), Math.cos(L));
  const H = D2R * (280.16 + 360.9856235 * d) - D2R * -LON - ra, phi = LAT * D2R;
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi)), alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
  return { east: -Math.sin(az) * Math.cos(alt), north: -Math.cos(az) * Math.cos(alt), up: Math.sin(alt), altDeg: alt / D2R };
}

// ---------- 2. height map ----------
const HF = { size: 400, res: 400 };
let H = null, G = null, info = {};
async function measure() {
  apt.group.visible = false; sky.visible = false;
  camera.fov = 60; camera.position.set(0, 380, 0.01); camera.lookAt(0, 0, 0); camera.updateProjectionMatrix(); tiles.errorTarget = 6;
  await settle(2500);
  const rt = new THREE.WebGLRenderTarget(HF.res, HF.res, { type: THREE.FloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
  const ortho = new THREE.OrthographicCamera(-HF.size / 2, HF.size / 2, HF.size / 2, -HF.size / 2, 1, 4000); ortho.position.set(0, 2000, 0); ortho.up.set(0, 0, -1); ortho.lookAt(0, 0, 0);
  const hm = new THREE.ShaderMaterial({ side: THREE.DoubleSide,
    vertexShader: 'varying float vY; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vY = w.y; gl_Position = projectionMatrix * viewMatrix * w; }',
    fragmentShader: 'varying float vY; void main(){ gl_FragColor = vec4(vY + 3000.0, 0.0, 0.0, 1.0); }' });
  running = false; await sleep(50);
  scene.overrideMaterial = hm; renderer.setRenderTarget(rt); renderer.setClearColor(0x000000, 0); renderer.clear(); renderer.render(scene, ortho);
  const px = new Float32Array(HF.res * HF.res * 4); renderer.readRenderTargetPixels(rt, 0, 0, HF.res, HF.res, px);
  renderer.setRenderTarget(null); scene.overrideMaterial = null; running = true; rt.dispose();
  H = new Float32Array(HF.res * HF.res); for (let i = 0; i < H.length; i++) H[i] = px[i * 4] > 0 ? px[i * 4] - 3000 : NaN;
  G = minFilter(H, 15);   // local ground: lowest point within 15 m
  apt.group.visible = true; sky.visible = true;
  return analyse();
}
const cell = (x, z) => { const i = Math.floor((x + HF.size / 2) / HF.size * HF.res), j = Math.floor((HF.size / 2 - z) / HF.size * HF.res); return (i < 0 || j < 0 || i >= HF.res || j >= HF.res) ? -1 : j * HF.res + i; };
const at = (A, x, z) => { const c = cell(x, z); return c < 0 ? NaN : A[c]; };
const xz = c => [-HF.size / 2 + (c % HF.res + 0.5) * HF.size / HF.res, HF.size / 2 - (Math.floor(c / HF.res) + 0.5) * HF.size / HF.res];
function minFilter(A, r) {
  const n = HF.res, T = new Float32Array(A.length), O = new Float32Array(A.length);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) { let m = Infinity; for (let k = Math.max(0, i - r); k <= Math.min(n - 1, i + r); k++) { const v = A[j * n + k]; if (v < m) m = v; } T[j * n + i] = m; }
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { let m = Infinity; for (let k = Math.max(0, j - r); k <= Math.min(n - 1, j + r); k++) { const v = T[k * n + i]; if (v < m) m = v; } O[j * n + i] = m; }
  return O;
}
const pct = (arr, p) => { const s = arr.filter(Number.isFinite).sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : NaN; };
function analyse() {
  // own building: the raised region (> 4 m above local ground) nearest to the geocoded point, flood-filled within 35 m and
  // within 6 m of the seed's roof height (terraced neighbours on a hill stay separate)
  let seed = -1, sd = Infinity;
  for (let c = 0; c < H.length; c++) { if (!(H[c] - G[c] > 4)) continue; const [x, z] = xz(c), d = Math.hypot(x, z); if (d < sd && d < 30) { sd = d; seed = c; } }
  const foot = new Set();
  if (seed >= 0) { const h0 = H[seed], [sx, sz] = xz(seed), st = [seed];
    while (st.length && foot.size < 6000) { const c = st.pop(); if (foot.has(c)) continue; const [x, z] = xz(c);
      if (!(H[c] - G[c] > 4) || Math.abs(H[c] - h0) > 6 || Math.hypot(x - sx, z - sz) > 35) continue; foot.add(c);
      for (const nc of [c - 1, c + 1, c - HF.res, c + HF.res]) if (nc >= 0 && nc < H.length && !foot.has(nc)) st.push(nc); } }
  const fc = [...foot], roof = pct(fc.map(c => H[c]), 0.8), ground = pct(fc.map(c => G[c]), 0.5);
  let cx = 0, cz = 0; for (const c of fc) { const [x, z] = xz(c); cx += x; cz += z; } cx /= fc.length || 1; cz /= fc.length || 1;
  const floors = Math.max(1, Math.round((roof - ground) / FLOOR_H));
  info = { footprint_m2: fc.length, roof, ground, floors, height_m: roof - ground, centroid: [cx, cz], seedDist: sd };
  return info;
}
function chooseFloor(planName, override) {
  if (override) return { index: Math.max(0, override - 1), why: 'override' };
  if (/penthouse|\bph\b/i.test(planName || '')) return { index: info.floors - 1, why: 'penthouse: top floor' };
  return { index: Math.max(1, Math.round(info.floors / 2) - 1), why: 'mid-building' };
}
function facadeAndView(theta, eyeY) {   // from the footprint centre out to the facade, then how far the view runs at eye height
  const ux = Math.sin(theta), uz = Math.cos(theta); let [x, z] = info.centroid, out = 0, fx = x, fz = z;
  for (let s = 0; s < 120; s += 0.5) { const px = x + ux * s, pz = z + uz * s, h = at(H, px, pz), g = at(G, px, pz); if (h - g > 4) { fx = px; fz = pz; out = 0; } else if ((out += 0.5) > 2.5) break; }
  let blocked = 190, firstHit = null;
  for (let s = 2; s < 190; s += 1) { const h = at(H, fx + ux * s, fz + uz * s); if (!Number.isFinite(h)) break; if (h > eyeY + 1) { blocked = s; firstHit = s; break; } }
  return { fx, fz, open: blocked, firstHit, groundF: at(G, fx, fz) };
}

// ---------- 3-4. placement ----------
let place = null;
function placeUnit({ floor = 0, planName = '' } = {}) {
  const fl = chooseFloor(planName, floor), floorY = info.ground + fl.index * FLOOR_H, eyeY = floorY + EYE;
  const scan = []; for (let k = 0; k < 36; k++) scan.push({ theta: k * 10 * D2R, ...facadeAndView(k * 10 * D2R, eyeY) });
  const score = k => (scan[(k + 35) % 36].open + 2 * scan[k].open + scan[(k + 1) % 36].open) / 4;   // a wide opening, not a slit
  let bk = 0; for (let k = 1; k < 36; k++) if (score(k) > score(bk)) bk = k;
  const best = scan[bk], u = new THREE.Vector2(Math.sin(best.theta), Math.cos(best.theta)), n = mainWall.n;
  const phi = Math.atan2(n.x, n.y) - Math.atan2(u.x, u.y);   // turn about +Y that carries the view direction onto the wall's normal
  world.rotation.set(0, phi, 0); world.position.set(0, 0, 0); world.updateMatrixWorld(true);
  const F = new THREE.Vector3(best.fx, 0, best.fz).applyAxisAngle(new THREE.Vector3(0, 1, 0), phi);
  world.position.set(mainWall.outer.x - F.x, -floorY, mainWall.outer.y - F.z); world.updateMatrixWorld(true);
  carve.min.value.set(aptBox.min.x - 0.8, -50, aptBox.min.z - 0.8); carve.max.value.set(aptBox.max.x + 0.8, layout.ceiling_m + 0.6 || 3.2, aptBox.max.z + 0.8);
  const B = enuBasis(), headingDeg = ((Math.atan2(u.x * B.east.x + u.y * B.east.z, u.x * B.north.x + u.y * B.north.z) / D2R) + 360) % 360;
  place = { floorHuman: fl.index + 1, floorWhy: fl.why, floorY, phi, headingDeg, open: best.open, acrossStreet: best.firstHit, scan: scan.map(s => s.open) };
  return place;
}

// ---------- 5. time of day + look ----------
let lookName = '';
function setTime(hour, treated = true) {
  const hh = Math.floor(hour), mm = Math.round((hour - hh) * 60);
  const date = new Date(`2026-10-25T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00-07:00`);   // PDT
  const s = sunENU(date), B = enuBasis();
  const dm = new THREE.Vector3().addScaledVector(B.east, s.east).addScaledVector(B.north, s.north).add(new THREE.Vector3(0, s.up, 0)).normalize()
    .applyAxisAngle(new THREE.Vector3(0, 1, 0), place ? place.phi : 0);
  const alt = s.altDeg, k = THREE.MathUtils.clamp((alt + 4) / 14, 0, 1), gold = THREE.MathUtils.clamp(1 - Math.abs(alt - 3) / 9, 0, 1), night = THREE.MathUtils.clamp(-alt / 6, 0, 1);
  sky.material.uniforms.sunPosition.value.copy(dm); sky.material.uniforms.turbidity.value = 4 + 6 * gold; sky.material.uniforms.rayleigh.value = 1.2 + 1.8 * gold + 1.5 * night;
  sky.material.uniforms.mieCoefficient.value = 0.004 + 0.004 * gold; sky.material.uniforms.mieDirectionalG.value = 0.82;
  sun.position.copy(ac).addScaledVector(dm, ext * 3); sun.visible = alt > -1;
  sun.color.setRGB(1, 0.93 - 0.25 * gold, 0.84 - 0.42 * gold); sun.intensity = treated ? (alt > 0 ? 1.2 + 2.2 * k : 0) : 2.6;
  hemi.intensity = treated ? 0.18 + 0.4 * k : 0.5; scene.environmentIntensity = treated ? 0.25 + 0.35 * k : 0.55;
  for (const l of apt.lights) l.visible = treated && alt < 6;   // lamps on as the light goes
  if (treated) {
    look.tint.setRGB(1.2 + 0.25 * gold - 0.8 * night, 1.15 - 0.12 * gold - 0.7 * night, 1.12 - 0.5 * gold - 0.45 * night);   // bright windows; golden warm; blue-hour cool
    const fog = new THREE.Color().setRGB(0.80 + 0.17 * gold - 0.5 * night, 0.85 - 0.02 * gold - 0.5 * night, 0.92 - 0.22 * gold - 0.4 * night);
    scene.fog = new THREE.FogExp2(fog, 0.0005 + 0.0004 * gold); bloom.enabled = true; bloom.strength = 0.3 + 0.35 * gold; renderer.toneMappingExposure = 1.0 - 0.12 * gold;
  } else { look.tint.setRGB(1, 1, 1); scene.fog = null; bloom.enabled = false; renderer.toneMappingExposure = 1.0; }
  for (const m of tileMats) m.color.copy(look.tint);
  lookName = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')} PDT, sun ${alt.toFixed(1)}°, ${treated ? 'treated' : 'raw'}`;
}

// ---------- views ----------
function setView(kind) {
  const n = mainWall.n, o = mainWall.outer, t = mainWall.wall.thickness_m || 0.15, wc = mainWall.wc, midY = (mainWall.sillY + mainWall.headY) / 2;
  carve.max.value.y = kind === 'aerial' ? 500 : (layout.ceiling_m || 2.6) + 0.6;
  if (kind === 'window') {   // a room view: from the roomiest spot of the room behind the window, looking at it
    const p = roomyPoint(mainWall.room.polygon); camera.fov = 68; camera.position.set(p.x, EYE, p.y);
    camera.lookAt(wc.x + n.x * 4, midY - 0.25, wc.y + n.y * 4); apt.ceilingMeshes.forEach(m => m.visible = true); tiles.errorTarget = 3;
  } else if (kind === 'across') {   // standing at the window, looking straight out
    const p = wc.clone().sub(n.clone().multiplyScalar(t / 2 + 0.85)); camera.fov = 50; camera.position.set(p.x, EYE, p.y);
    camera.lookAt(wc.x + n.x * 30, EYE - 0.9, wc.y + n.y * 30); apt.ceilingMeshes.forEach(m => m.visible = true); tiles.errorTarget = 2.5;
  } else if (kind === 'aerial') {
    camera.fov = 50; camera.position.set(o.x + n.x * 85 - n.y * 40, 45, o.y + n.y * 85 + n.x * 40); camera.lookAt(o.x, 0, o.y);
    apt.ceilingMeshes.forEach(m => m.visible = false); tiles.errorTarget = 5;
  }
  camera.updateProjectionMatrix();
}
function label(view) {
  const P = place || {}, I = info;
  $('label').textContent = `${UNIT}  ${view}\nbuilding ≈${(I.height_m || 0).toFixed(0)} m, ${I.floors} floors · this unit on floor ${P.floorHuman} (${P.floorWhy})\nwindows face ${Math.round(P.headingDeg)}° from north · open view ${P.open} m${P.acrossStreet ? ` · first building ${P.acrossStreet} m away` : ''}\n${lookName}`;
  const a = (tiles.getAttributions?.() || []).map(x => x.value).filter(v => typeof v === 'string');
  $('attr').innerHTML = `<b>Google</b> · ${[...new Set(a)].join(' · ') || 'Map data ©2026 Google'}`;
}
window.spike = {
  ready: true, info: () => ({ info, place, mainWall: { len: mainWall.len, windowWidth: mainWall.windowWidth } }),
  measure, place: o => placeUnit(o),
  async shot({ view = 'window', hour = 17.5, treated = true, dof = false, errorTarget = null } = {}) { setView(view); if (errorTarget != null) tiles.errorTarget = errorTarget; setTime(hour, treated);
    bokeh.enabled = !!dof && treated; if (bokeh.enabled) bokeh.uniforms.focus.value = camera.position.distanceTo(new THREE.Vector3(mainWall.wc.x, EYE, mainWall.wc.y)) + 0.3;
    lookName += bokeh.enabled ? ', soft outside (depth of field)' : ''; await settle(1500); label(view); await sleep(300); return { progress: tiles.loadProgress }; },
};
if (Q.get('auto') === '1') { await settle(1500); await measure(); placeUnit({ floor: +(Q.get('floor') || 0) }); await window.spike.shot({ view: Q.get('view') || 'window', hour: +(Q.get('hour') || 17.5) }); }
$('label').textContent = 'ready';
