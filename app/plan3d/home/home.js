// Customer apartment page (home.html): light scene, Overview / Walk, rooms, floor plan, and the design sheet.
// Reuses the plan engine (build.js) and the furnishing layer (furnish.js); walk.js and agent.js run beside it unchanged.
// agent.js is driven through its own element ids (aiBudget, aiStyle, aiTier, aiGo, aiAll, aiStop, aiChat, aiSend) and read
// back through aiLog / aiStop, so its behaviour (streaming, animations, tiers) stays the single source of truth.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { Apartment, MaterialLib } from '../build.js';
import { Furnish } from '../../furnish/furnish.js';
import { enhanceAll } from '/ui/glass.js';
import { createOutside } from '../outside/outside.js';
import { classifyExteriorDoors, dressExteriorDoors, sealApartment } from './hermetic.js';
import { createAmbiance } from './ambiance.js';
// curtains hang from the plan's window positions, which are often a little off: left out of the 3D scene unless localStorage curtains = '1'
import('../../furnish/props.js').then(m => { const P = m.Props, orig = P && P._curtains; if (orig) P._curtains = function (...a) { if (localStorage.getItem('curtains') === '1') return orig.apply(this, a); }; }).catch(() => {});

const Q = new URLSearchParams(location.search), unit = Q.get('unit') || 'gs-22612_plan_03';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const money = v => '$' + Math.round(v || 0).toLocaleString('en-US');
const sheetW = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sheet')) || 0;
enhanceAll();
window.__quality = 'low';   // furnish.js: lamp lights without shadows (a shadowed point light renders the scene six more times per frame)

// ---------- scene ----------
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(innerWidth, innerHeight); renderer.setClearColor(0x000000, 0);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.localClippingEnabled = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
$('scene').appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(0xdde3ea, 0);   // constant: toggling fog changes every program
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.05, 300);
const orbit = new OrbitControls(camera, renderer.domElement); orbit.enableDamping = true; orbit.dampingFactor = 0.08; orbit.maxPolarAngle = Math.PI * 0.47; orbit.enablePan = false;
const look = new PointerLockControls(camera, renderer.domElement);
const pmrem = new THREE.PMREMGenerator(renderer); scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; scene.environmentIntensity = 0.55;

const lib = await new MaterialLib('/furnish/materials/').load();
const layout = await (await fetch(`layouts/${unit}.json`)).json();
const extDoors = classifyExteriorDoors(layout);   // entrance = wood slab, balcony = glass; both shut and locked when walking
const apt = new Apartment(layout, lib); scene.add(apt.group); apt.labels.forEach(l => l.visible = false);
const lockedDoors = dressExteriorDoors(apt, extDoors), seal = sealApartment(apt, layout);
window.__exteriorDoors = layout._exteriorDoors;   // for checking: [{id, kind, facade score, room}]
const pane = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.07, roughness: 0.04, metalness: 0, depthWrite: false, side: THREE.DoubleSide });
apt.group.traverse(o => { if (o.isMesh && o.material && o.material.transmission > 0) o.material = pane; });   // transmission glass re-renders the whole scene (city included) every frame
const bb = apt.bounds, center = bb.getCenter(new THREE.Vector3()), size = bb.getSize(new THREE.Vector3()), ext = Math.max(size.x, size.z);
orbit.minDistance = ext * 0.35; orbit.maxDistance = ext * 3;

// low warm sun pouring through the wall with the most window, cool sky fill; shadows land on the page
function windowAzimuth(L) {
  const byWall = {}; for (const o of L.openings) if (o.type === 'window') byWall[o.wall] = (byWall[o.wall] || 0) + (o.width_m || (o.s1 - o.s0));
  let best = null; for (const w of L.walls) { const ww = byWall[w.id] || 0; if (ww > 0 && (!best || ww > best.ww)) best = { w, ww }; }
  if (!best) return Math.atan2(-0.6, -0.8);
  const a = best.w.a, b = best.w.b, d = new THREE.Vector2(b[0] - a[0], b[1] - a[1]).normalize(), n = new THREE.Vector2(-d.y, d.x), mid = new THREE.Vector2((a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
  let near = null, nd = Infinity; for (const r of L.rooms) { const c = r.polygon.reduce((s, p) => s.add(new THREE.Vector2(p[0], p[1])), new THREE.Vector2()).multiplyScalar(1 / r.polygon.length); const dd = c.distanceTo(mid); if (dd < nd) { nd = dd; near = c; } }
  if (near && near.clone().sub(mid).dot(n) > 0) n.negate();
  return Math.atan2(n.x, n.y) + THREE.MathUtils.degToRad(22);
}
const sunAz = windowAzimuth(layout);
const sun = new THREE.DirectionalLight(0xffdcb4, 3); sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096); sun.shadow.bias = -0.00025; sun.shadow.normalBias = 0.03; sun.shadow.radius = 4;
const sc = sun.shadow.camera; sc.left = sc.bottom = -ext * 0.9; sc.right = sc.top = ext * 0.9; sc.near = 0.5; sc.far = ext * 8; sc.updateProjectionMatrix();
scene.add(sun, sun.target); sun.target.position.copy(center);
const hemi = new THREE.HemisphereLight(0xe9f0ff, 0xf2e6d6, 0.6); scene.add(hemi);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(ext * 30, ext * 30), new THREE.ShadowMaterial({ color: 0x4a3a2c, opacity: 0.18 }));
ground.rotation.x = -Math.PI / 2; ground.position.set(center.x, -0.004, center.z); ground.receiveShadow = true; scene.add(ground);
function setSun(elevDeg, color, intensity) {
  const el = THREE.MathUtils.degToRad(elevDeg); sun.color.setHex(color); sun.intensity = intensity;
  sun.position.copy(center).add(new THREE.Vector3(Math.sin(sunAz) * Math.cos(el), Math.sin(el), Math.cos(sunAz) * Math.cos(el)).multiplyScalar(ext * 2.5));
}
const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
window.apartment = { layout, roomMeshes: apt.roomMeshes, floorPlane, scene, camera, renderer, apt };

// ---------- furniture: one Furnish per room; only models are shown (labels, footprints and fit colours are editing aids) ----------
const furn = {}; let activeRoom = null, changeQueued = false;
function changed() { if (changeQueued) return; changeQueued = true; requestAnimationFrame(() => { changeQueued = false; hideAids(); amb?.dress(); renderItems(); if (typeof stageSoon === 'function') stageSoon(); }); }
function hideAids() { for (const f of Object.values(furn)) for (const it of f.items) { if (it.label) it.label.visible = false; if (it.fp) it.fp.visible = false; if (it.fm) it.fm.visible = false; } }
const roomJobs = layout.rooms.map(async r => {
  try { const res = await fetch(`../rooms/${layout.unit}__${r.id}.json`); if (!res.ok) return;
    const f = new Furnish({ scene, camera, renderer, controls: orbit, panelEl: null, toastEl: $('toast'), active: false, onChange: changed, title: r.name });
    furn[r.id] = f; await f.setRoom(`${layout.unit}__${r.id}`, await res.json()); f.setClipping([clip]); changed();
  } catch (e) { console.warn('[home] furnish', r.id, e); }
});
function activateRoom(id) {
  if (!id || activeRoom === id) { refreshRoomUi(); return; }
  for (const [rid, f] of Object.entries(furn)) if (rid !== id && f.active) { f.setActive(false); f.panelEl = null; }
  activeRoom = id; amb?.placeWindowLights(id); const f = furn[id]; if (f) { f.panelEl = $('furn'); if (mode === 'doll') f.setActive(true); }   // editing (drag, R, D, Delete) only in the overview: D is also strafe-right
  refreshRoomUi(); renderItems();
}
const roomName = id => (layout.rooms.find(r => r.id === id) || {}).name || 'this room';

// ---------- views ----------
let mode = 'doll'; const clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1.3);
const CUT = 1.3;
function applyClip(on) {   // the cut plane stays on every material and only moves: adding or removing it would recompile every shader
  clip.constant = on ? CUT : 1e6;
  apt.group.traverse(o => { if (o.isMesh && o.material && o.userData.kind !== 'wall') for (const m of [].concat(o.material)) { if (m.clippingPlanes?.[0] !== clip) m.clippingPlanes = [clip]; m.clipShadows = true; } });
  apt.section(on ? CUT : null); for (const f of Object.values(furn)) f.setClipping([clip]);
}
function frameView() {   // keep the scene centred in the space left of the design sheet
  const W = innerWidth, H = innerHeight; renderer.setSize(W, H); amb?.resize(); camera.aspect = W / H;
  const s = sheetW(); if (s) camera.setViewOffset(W, H, s / 2, 0, W, H); else camera.clearViewOffset(); camera.updateProjectionMatrix();
}
function pressMode(id) { for (const b of ['vDoll', 'vWalk', 'vPhoto']) $(b).setAttribute('aria-pressed', String(b === id)); }
function setDoll() {
  leavePhoto(); mode = 'doll'; if (look.isLocked) look.unlock(); $('bWalk').classList.remove('on'); pressMode('vDoll');
  outside?.enable(false); document.body.classList.remove('walking'); seal?.setWalk(false);
  if (activeRoom && furn[activeRoom]) { furn[activeRoom].panelEl = $('furn'); furn[activeRoom].setActive(true); }
  apt.ceilingMeshes.forEach(m => m.visible = false); applyClip(true); orbit.enabled = true; amb?.setMode('doll');
  $('walkHint').hidden = true; $('cross').hidden = true; camera.fov = 40; frameView();
  const d = ext * 1.55; camera.position.set(center.x + d * 0.55, d * 0.85 + 2, center.z + d * 0.75); orbit.target.set(center.x, 0.4, center.z); orbit.update();
}
function setWalk(roomId, yawDeg) {
  leavePhoto(); mode = 'walk'; $('bWalk').classList.add('on'); pressMode('vWalk'); closeMenus();
  apt.ceilingMeshes.forEach(m => m.visible = true); applyClip(false); orbit.enabled = false;
  outside?.enable(true); document.body.classList.add('walking'); seal?.setWalk(true); amb?.setMode('walk');
  for (const f of Object.values(furn)) { f.select(null); f.setActive(false); }
  const id = roomId && apt.roomMeshes[roomId] ? roomId : currentRoom() || layout.rooms[0].id; activateRoom(id);
  const c = roomyPoint(id); camera.fov = 62; frameView(); $('tip').hidden = true;
  camera.position.set(c.x, c.y + 1.6, c.z); const yaw = THREE.MathUtils.degToRad(yawDeg ?? roomWindowYaw(id, c) ?? outside?.windowYaw?.() ?? 35); camera.rotation.set(0, 0, 0); camera.lookAt(c.x + Math.sin(yaw), c.y + 1.5, c.z + Math.cos(yaw));
  if (window.walk?.teleport) window.walk.teleport(c.x, c.z, c.y);
  $('walkHint').hidden = false;
}
function roomyPoint(id) {   // the grid point inside the room polygon farthest from its walls
  const r = layout.rooms.find(x => x.id === id), base = apt.roomMeshes[id].center; if (!r || !r.polygon?.length) return base;
  const P = r.polygon, xs = P.map(p => p[0]), zs = P.map(p => p[1]); let best = null, bd = -1;
  const inside = (x, z) => { let k = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const [xi, zi] = P[i], [xj, zj] = P[j]; if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi) k = !k; } return k; };
  const edge = (x, z) => { let m = Infinity; for (let i = 0; i < P.length; i++) { const [ax, az] = P[i], [bx, bz] = P[(i + 1) % P.length], dx = bx - ax, dz = bz - az, t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1))); m = Math.min(m, Math.hypot(x - ax - t * dx, z - az - t * dz)); } return m; };
  for (let i = 1; i < 24; i++) for (let j = 1; j < 24; j++) { const x = Math.min(...xs) + (Math.max(...xs) - Math.min(...xs)) * i / 24, z = Math.min(...zs) + (Math.max(...zs) - Math.min(...zs)) * j / 24; if (!inside(x, z)) continue; const d = edge(x, z); if (d > bd) { bd = d; best = new THREE.Vector3(x, base.y, z); } }
  return best || base;
}
window.setWalk = setWalk; window.setDoll = setDoll;
(async () => {   // exterior doors leave walk.js's door list: no prompt, no toggling, and a door not in the list is never passable
  while (!window.walk?.doors) await new Promise(r => setTimeout(r, 100));
  for (const id of lockedDoors) window.walk.doors.delete(id);
})();   // agent.js and walk.js call these
$('vDoll').onclick = setDoll; $('vWalk').onclick = () => setWalk(activeRoom);
renderer.domElement.addEventListener('click', () => { if (mode === 'walk' && !look.isLocked) look.lock(); });
look.addEventListener('lock', () => { $('walkHint').hidden = true; $('cross').hidden = false; });
look.addEventListener('unlock', () => { $('cross').hidden = true; if (mode === 'walk') $('walkHint').hidden = false; });
addEventListener('keydown', e => {
  if (e.code === 'Escape' && ((mode === 'walk' && !look.isLocked) || mode === 'photo')) setDoll();
  if (mode === 'photo' && !/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) && (e.code === 'ArrowLeft' || e.code === 'ArrowRight')) { e.preventDefault(); setPhoto(phIdx + (e.code === 'ArrowLeft' ? -1 : 1)); }
});

// ---------- photos: a slider between each listing photo and the same photo, furnished (photos/<unit>.json) ----------
// Right of the slider: the photo furnished by the staging worker (photos/stage_server.py: Stable Diffusion restyles only our
// furniture and its shadows, strength 0.3, the rest of the photo is copied back), and until that is ready the live overlay
// (our furniture drawn into the photo from its camera). Renders start in the background when the furniture settles, so the
// furnished photo is usually waiting by the time Photos opens.
const STAGE = window.MOVEIN_STAGE || 'http://127.0.0.1:8772', STAGE_V = 1;
let PH = null, phIdx = 0, phRect = null, phHfov = 75, phSplit = 0.5, phReady = false;
const adjOf = i => JSON.parse(localStorage.getItem(`photoAdj:${unit}:${PH.photos[i].src}`) || '{"dy":0,"dp":0,"df":0}');
fetch(`photos/${unit}.json`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(j => {
  if (!j || !j.photos || !j.photos.length) return; PH = j; $('vPhoto').hidden = false;
  $('pStrip').innerHTML = j.photos.map((p, i) => `<button data-i="${i}" aria-label="Photo ${i + 1}" style="background-image:url('${p.src}')"></button>`).join('');
  stageSoon(3000);
}).catch(() => {});
$('vPhoto').onclick = () => setPhoto(phIdx);
$('pStrip').onclick = e => { const b = e.target.closest('[data-i]'); if (b) setPhoto(+b.dataset.i); };
$('pPrev').onclick = () => setPhoto(phIdx - 1); $('pNext').onclick = () => setPhoto(phIdx + 1);
$('pRender').onclick = () => { if (PH) requestStage(phIdx, true); };
function setFurnVisible(on) { for (const f of Object.values(furn)) f.group.visible = on; }

// staged materials: walls, ceilings, doors, fixtures become invisible depth occluders (and cast no shadow), floors catch
// the furniture's shadows; with the warm, low window light of the listing photos
let staged = false; const stageSaved = new Map();
const OCCLUDE = new THREE.MeshBasicMaterial({ colorWrite: false }), CATCH = new THREE.ShadowMaterial({ color: 0x24180e, opacity: 0.5 });
function stageMats(on) {
  if (on) apt.group.traverse(o => { if (!o.isMesh || o.userData.item || stageSaved.has(o)) return; stageSaved.set(o, o.material); o.userData.castWas = o.castShadow;
    const floor = /^pfloor_/.test(o.name); if (!floor) o.castShadow = false; o.material = floor ? CATCH : OCCLUDE; });
  else { for (const [o, m] of stageSaved) { o.material = m; if (o.userData.castWas != null) o.castShadow = o.userData.castWas; } stageSaved.clear(); }
}
function stageLight() { renderer.toneMappingExposure = 0.82; setSun(24, 0xffd9ae, 2.6); hemi.intensity = 0.45; scene.environmentIntensity = 0.5; sun.visible = true; }
function setStaged(on) {
  if (on === staged) return; staged = on; $('pBack').hidden = !on;
  if (on) { outside?.enable(false); seal?.setWalk(false); stageMats(true); stageLight(); } else stageMats(false);
}
function leavePhoto() { if (mode !== 'photo') return; setStaged(false); $('photos').hidden = true; document.body.classList.remove('photomode'); renderer.domElement.style.clipPath = ''; renderer.domElement.style.visibility = ''; setFurnVisible(true); }
function setPhoto(i) {
  if (!PH) return; phIdx = (i + PH.photos.length) % PH.photos.length;
  if (mode !== 'photo') {
    if (look.isLocked) look.unlock(); mode = 'photo'; $('bWalk').classList.remove('on'); pressMode('vPhoto'); closeMenus();
    apt.ceilingMeshes.forEach(m => m.visible = true); applyClip(false); orbit.enabled = false;
    document.body.classList.add('walking', 'photomode');
    for (const f of Object.values(furn)) { f.select(null); f.setActive(false); }
    $('photos').hidden = false; $('tip').hidden = true; $('walkHint').hidden = true; $('cross').hidden = true;
    setFurnVisible(true); outside?.enable(false); seal?.setWalk(false);
    renderer.domElement.style.visibility = 'hidden';   // photos only: the listing photo and, once rendered, the furnished photo
  }
  const p = PH.photos[phIdx], room = layout.rooms.find(r => r.id === p.room);
  $('pPhoto').onload = layoutPhotos; $('pPhoto').src = p.src; $('pBackImg').src = p.src; $('pCount').textContent = `${phIdx + 1} of ${PH.photos.length}`;
  $('pNote').textContent = (p.source === 'metrology' ? "Camera measured from the photo." : "Camera matched to the photo's floor, walls, windows and doors.") + ` ${room ? room.name : ''}`;
  for (const b of $('pStrip').children) b.setAttribute('aria-current', String(+b.dataset.i === phIdx));
  if (room && furn[room.id]) activateRoom(room.id);
  layoutPhotos(); applyPhotoCam(); showStaged(); requestStage(phIdx);
}
function photoCam(i, cam) {   // the photo's camera (with any saved fine-tune) applied to cam; returns the horizontal lens
  const p = PH.photos[i], a = adjOf(i), yaw = THREE.MathUtils.degToRad(p.yaw + a.dy), pitch = THREE.MathUtils.degToRad(p.pitch + a.dp);
  cam.position.set(p.pos[0], p.pos[1], p.pos[2]); cam.rotation.set(0, 0, 0);
  cam.lookAt(p.pos[0] + Math.sin(yaw) * Math.cos(pitch), p.pos[1] + Math.sin(pitch), p.pos[2] + Math.cos(yaw) * Math.cos(pitch));
  return Math.min(115, Math.max(35, p.hfov + a.df));
}
function applyPhotoCam() { phHfov = photoCam(phIdx, camera); }
function place(el, x, y, w, h) { Object.assign(el.style, { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' }); }
function layoutPhotos() {   // one frame at the photo's aspect: listing photo left of the slider, furnished photo right of it
  if (!PH || mode !== 'photo') return;
  const ph = PH.photos[phIdx], aspect = ph.aspect || 1.5, W = innerWidth - sheetW(), H = innerHeight, top = 146, bottom = 222, availH = Math.max(160, H - top - bottom);
  const w = Math.min(W - 36, availH * aspect), h = w / aspect, x = (W - w) / 2, y = top + (availH - h) / 2; phRect = { x, y, w, h };
  for (const id of ['pBox', 'p3d', 'pStagedBox', 'pBack']) place($(id), x, y, w, h);
  const c = ph.crop || [0, 0, 1, 1], iw = w / (c[2] - c[0]), ih = h / (c[3] - c[1]), st = { width: iw + 'px', height: ih + 'px', left: (-c[0] * iw) + 'px', top: (-c[1] * ih) + 'px' };
  Object.assign($('pPhoto').style, st); Object.assign($('pBackImg').style, st);
  $('pBox').style.clipPath = phReady ? `inset(0 ${((1 - phSplit) * 100).toFixed(2)}% 0 0 round 16px 0 0 16px)` : '';   // the slider only once the furnished photo exists
  $('pHandle').hidden = !phReady; $('p3d').style.pointerEvents = phReady ? '' : 'none'; place($('pHandle'), x + w * phSplit, y, 0, h);
  Object.assign($('pCapL').style, { left: x + 'px', top: (y + h + 10) + 'px' });
  Object.assign($('pCapR').style, { left: (x + w) + 'px', top: (y + h + 10) + 'px', transform: 'translateX(-100%)', textAlign: 'right' });
  $('pNote').style.top = (y + h + 34) + 'px'; $('pNote').style.maxWidth = Math.min(w, 720) + 'px';
  Object.assign($('pStatus').style, { left: (x + w - 14) + 'px', top: (y + 14) + 'px' });
}
addEventListener('resize', () => { if (mode === 'photo') layoutPhotos(); });
{ let drag = false; const at = e => { phSplit = Math.min(1, Math.max(0, (e.clientX - phRect.x) / phRect.w)); layoutPhotos(); };   // drag anywhere on the frame
  $('p3d').addEventListener('pointerdown', e => { drag = true; $('p3d').setPointerCapture(e.pointerId); at(e); });
  $('p3d').addEventListener('pointermove', e => { if (drag) at(e); });
  $('p3d').addEventListener('pointerup', () => { drag = false; }); }

// ---------- staging: capture (inside the render loop, so nothing flickers), send, poll, show ----------
const stageState = {}, polling = new Set(), background = new Set();
function furnSig() { const a = []; for (const f of Object.values(furn)) for (const it of f.items) { const s = it.spec; a.push(`${s.id}|${(+s.x || 0).toFixed(2)}|${(+s.z || 0).toFixed(2)}|${Math.round(+s.rot_deg || 0)}|${(+s.y_m || 0).toFixed(2)}`); } return a.sort().join(';'); }
function hash(str) { let h = 2166136261 >>> 0; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; } return h.toString(36); }
function stageKey(i) { const p = PH.photos[i]; return `${unit}_${p.src.split('/').pop().replace(/\.jpg$/, '')}_${hash(furnSig() + JSON.stringify([p.pos, p.yaw, p.pitch, p.hfov, adjOf(i), STAGE_V]))}`; }
const hasFurniture = () => Object.values(furn).some(f => f.items.some(it => it.spec.category !== 'fixture'));
function stagePrompt(i) {
  const p = PH.photos[i], room = layout.rooms.find(r => r.id === p.room), kind = (room && room.type && room.type !== 'other' ? room.type.replace('living', 'living room') : 'room');
  const COL = /\b(white|black|beige|grey|gray|oak|birch|walnut|natural|green|blue|pink|brown|cream|ash|bamboo|rattan|linen|velvet|leather|jute|wool|brass|glass)\b/gi;
  const src = (furn[p.room] && furn[p.room].items.length ? [furn[p.room]] : Object.values(furn)).flatMap(f => f.items).filter(it => it.spec.category !== 'fixture')
    .sort((a, b) => (+b.spec.w_m || 0) * (+b.spec.d_m || 0) - (+a.spec.w_m || 0) * (+a.spec.d_m || 0));
  const items = [...new Set(src.map(it => { const n = shortName(it.spec.name), cols = [...new Set((n.variant.match(COL) || []).map(x => x.toLowerCase()))].slice(0, 2).join(' ');
    return `${cols} ${String(it.spec.category || n.name).replace(/_/g, ' ')}`.trim(); }))].slice(0, 9);
  return `professional real estate photograph of a bright ${kind}, ${items.join(', ')}, warm natural window light, soft natural shadows, photorealistic, sharp, high detail`;
}
let captureReq = null;
const captureStage = i => new Promise(res => { captureReq = { i, res }; });
function loadImg(src) { return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; }); }
function doCapture(i) {   // called from the render loop: furniture layer from the photo's camera, read back, then restore
  const p = PH.photos[i], aspect = p.aspect || 1.5, cw = renderer.domElement.width, ch = renderer.domElement.height, pr = renderer.getPixelRatio();
  let W = Math.min(1024, cw), H = Math.round(W / aspect); if (H > ch) { H = ch; W = Math.round(H * aspect); }
  const keep = new Set([apt.group, sun, sun.target, hemi, ...Object.values(furn).map(f => f.group)]), vis = new Map(), ceil = apt.ceilingMeshes.map(m => m.visible);
  const save = { pos: camera.position.clone(), quat: camera.quaternion.clone(), fov: camera.fov, aspect: camera.aspect, exp: renderer.toneMappingExposure, sunPos: sun.position.clone(),
    sunCol: sun.color.clone(), sunI: sun.intensity, sunV: sun.visible, hemiI: hemi.intensity, env: scene.environmentIntensity, fog: scene.fog ? scene.fog.density : 0, clip: clip.constant };
  const wasStaged = staged, tm = renderer.toneMapping, bg = scene.background; renderer.toneMapping = THREE.ACESFilmicToneMapping; scene.background = null;
  for (const o of scene.children) { vis.set(o, o.visible); o.visible = keep.has(o); }
  apt.ceilingMeshes.forEach(m => m.visible = true); clip.constant = 1e6; apt.section(null); if (scene.fog) scene.fog.density = 0;
  if (!wasStaged) stageMats(true); stageLight();
  const f = photoCam(i, camera); camera.clearViewOffset(); camera.aspect = aspect; camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(f) / 2) / aspect)); camera.updateProjectionMatrix();
  renderer.setRenderTarget(null); renderer.setScissorTest(true); renderer.setViewport(0, 0, W / pr, H / pr); renderer.setScissor(0, 0, W / pr, H / pr);
  renderer.setClearColor(0x000000, 0); renderer.clear(); renderer.render(scene, camera);
  const gl = renderer.getContext(), buf = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, buf);
  renderer.setScissorTest(false); renderer.setViewport(0, 0, innerWidth, innerHeight);
  if (!wasStaged) stageMats(false); renderer.toneMapping = tm; scene.background = bg;
  for (const [o, v] of vis) o.visible = v; apt.ceilingMeshes.forEach((m, k) => m.visible = ceil[k]);
  clip.constant = save.clip; apt.section(mode === 'doll' ? CUT : null); if (scene.fog) scene.fog.density = save.fog;
  renderer.toneMappingExposure = save.exp; sun.position.copy(save.sunPos); sun.color.copy(save.sunCol); sun.intensity = save.sunI; sun.visible = save.sunV; hemi.intensity = save.hemiI; scene.environmentIntensity = save.env;
  camera.position.copy(save.pos); camera.quaternion.copy(save.quat); camera.fov = save.fov; camera.aspect = save.aspect; if (mode === 'photo') camera.updateProjectionMatrix(); else frameView();
  return (async () => {   // photo crop + furniture layer (premultiplied, bottom-up) -> photo, composite and mask
    const img = await loadImg(p.src), c = p.crop || [0, 0, 1, 1], mk = n => Object.assign(document.createElement('canvas'), { width: W, height: H });
    const ph = mk(); ph.getContext('2d').drawImage(img, c[0] * img.naturalWidth, c[1] * img.naturalHeight, (c[2] - c[0]) * img.naturalWidth, (c[3] - c[1]) * img.naturalHeight, 0, 0, W, H);
    const layer = new ImageData(W, H), mask = new ImageData(W, H);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const s = ((H - 1 - y) * W + x) * 4, d = (y * W + x) * 4, a = buf[s + 3];
      if (a) { const k = 255 / a; layer.data[d] = Math.min(255, buf[s] * k); layer.data[d + 1] = Math.min(255, buf[s + 1] * k); layer.data[d + 2] = Math.min(255, buf[s + 2] * k); layer.data[d + 3] = a; }
      const m = a > 8 ? 255 : 0; mask.data[d] = mask.data[d + 1] = mask.data[d + 2] = m; mask.data[d + 3] = 255;
    }
    const lc = mk(); lc.getContext('2d').putImageData(layer, 0, 0); const comp = mk(), cx = comp.getContext('2d'); cx.drawImage(ph, 0, 0); cx.drawImage(lc, 0, 0);
    const mc = mk(); mc.getContext('2d').putImageData(mask, 0, 0);
    return { photo: ph.toDataURL('image/jpeg', 0.95), composite: comp.toDataURL('image/jpeg', 0.95), mask: mc.toDataURL('image/png') };
  })();
}
async function requestStage(i, force = false) {
  if (!PH || !hasFurniture()) { showStaged(); return; }
  const key = stageKey(i), st = stageState[key];
  if (!force && st && !['error', 'offline'].includes(st)) { if (st !== 'done') poll(key); showStaged(); return; }
  try { const s = await (await fetch(`${STAGE}/status/${key}`, { cache: 'no-store' })).json();
    if (!force && s.status === 'done') { stageState[key] = 'done'; showStaged(); return; }
    if (s.status === 'queued' || s.status === 'running') { stageState[key] = s.status; poll(key); showStaged(); return; } }
  catch (e) { stageState[key] = 'offline'; showStaged(); return; }
  stageState[key] = 'capturing'; showStaged();
  let pay; try { pay = await captureStage(i); } catch (e) { stageState[key] = 'error'; showStaged(); return; }
  try { const r = await (await fetch(`${STAGE}/stage`, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ key, ...pay, prompt: stagePrompt(i) }) })).json();
    stageState[key] = r.status === 'done' ? 'done' : 'queued'; } catch (e) { stageState[key] = 'offline'; }
  showStaged(); if (stageState[key] !== 'done' && stageState[key] !== 'offline') poll(key);
}
function poll(key) {
  if (polling.has(key)) return; polling.add(key);
  const t = setInterval(async () => {
    let s; try { s = await (await fetch(`${STAGE}/status/${key}`, { cache: 'no-store' })).json(); } catch (e) { return; }
    if (s.status === 'queued' || s.status === 'running') { if (stageState[key] !== s.status) { stageState[key] = s.status; showStaged(); } return; }
    clearInterval(t); polling.delete(key); stageState[key] = s.status === 'done' ? 'done' : 'error'; showStaged();
    if (s.status === 'done' && background.has(key) && mode !== 'photo') toast('Furnished photo ready in Photos');
  }, 1500);
}
function showStaged() {
  if (!PH || mode !== 'photo') return;
  const key = stageKey(phIdx), st = stageState[key], chip = $('pStatus');
  if (st === 'done') {
    const url = `${STAGE}/staged/${key}.jpg`;
    const ready = () => { if ($('pStaged').dataset.key !== stageKey(phIdx)) return; $('pStagedBox').hidden = false; if (!phReady) { phReady = true; layoutPhotos(); } };
    if ($('pStaged').dataset.key !== key) { $('pStaged').dataset.key = key; $('pStaged').onload = ready; $('pStaged').src = url; } else ready();
    chip.hidden = true; return;
  }
  $('pStagedBox').hidden = true; if (phReady) { phReady = false; layoutPhotos(); }
  const msg = !hasFurniture() ? 'Furnish the room to see it furnished here' : st === 'offline' ? 'Photo rendering is not running' : st === 'error' ? 'The render failed, try Render photo'
    : st === 'running' ? 'Rendering the furnished photo' : 'Preparing the furnished photo';
  const busy = ['capturing', 'queued', 'running', undefined].includes(st) && hasFurniture();
  chip.innerHTML = (busy ? '<span class="spin"></span>' : '') + esc(msg); chip.hidden = false;
}
function stageSoon(delay = 2500) {   // background: the best photo of each furnished room, the active room first
  clearTimeout(stageSoon.t); stageSoon.t = setTimeout(() => {
    if (!PH || running || homeRun || !hasFurniture()) return;
    const byRoom = {}; PH.photos.forEach((p, i) => (byRoom[p.room] ||= []).push(i));
    const picks = Object.entries(byRoom).filter(([rid]) => furn[rid] && furn[rid].items.length).map(([, idx]) =>
      idx.sort((a, b) => (PH.photos[b].source === 'metrology') - (PH.photos[a].source === 'metrology') || (PH.photos[b].confidence || 0) - (PH.photos[a].confidence || 0))[0]);
    picks.sort((a, b) => (PH.photos[b].room === activeRoom) - (PH.photos[a].room === activeRoom));
    for (const i of picks) { background.add(stageKey(i)); requestStage(i); }
  }, delay);
}
function renderPhotoFrame() {   // the 3D view only inside the right-hand frame, with the photo's lens
  const r = phRect, H = innerHeight; if (!r) return;
  renderer.setScissorTest(false); renderer.clear();
  camera.clearViewOffset(); camera.aspect = r.w / r.h; camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(phHfov) / 2) / camera.aspect)); camera.updateProjectionMatrix();
  renderer.setViewport(r.x, H - r.y - r.h, r.w, r.h); renderer.setScissor(r.x, H - r.y - r.h, r.w, r.h); renderer.setScissorTest(true);
  renderer.render(scene, camera); renderer.setScissorTest(false); renderer.setViewport(0, 0, innerWidth, innerHeight);
}
function roomWindowYaw(id, from) {   // face the largest window of this room (build.js tags each window with its room)
  let best = null; for (const o of layout.openings) { if (o.type !== 'window' || o.room !== id) continue; const w = layout.walls.find(x => x.id === o.wall); if (!w) continue;
    const L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1]) || 1, t = (o.s0 + o.s1) / 2 / L, wx = w.a[0] + (w.b[0] - w.a[0]) * t, wz = w.a[1] + (w.b[1] - w.a[1]) * t, width = o.s1 - o.s0;
    if (!best || width > best.width) best = { wx, wz, width }; }
  return best ? Math.atan2(best.wx - from.x, best.wz - from.z) * 180 / Math.PI : null;
}
function currentRoom() { let best = null, bd = Infinity; for (const [id, r] of Object.entries(apt.roomMeshes)) { const d = Math.hypot(r.center.x - camera.position.x, r.center.z - camera.position.z); if (d < bd) { bd = d; best = id; } } return best; }

// camera glide for room picks in the overview
let glide = null;
function flyTo(pos, target, ms = 900) { glide = { p0: camera.position.clone(), t0: orbit.target.clone(), p1: pos, t1: target, start: performance.now(), ms }; }
function flyToRoom(id) { const r = apt.roomMeshes[id]; if (!r) return; const m = layout.rooms.find(x => x.id === id); const e = Math.sqrt(m?.area_m2 || 12) * 1.7 + 2.5;
  flyTo(new THREE.Vector3(r.center.x + e * 0.45, e * 1.05, r.center.z + e * 0.6), new THREE.Vector3(r.center.x, 0.3, r.center.z)); }

// ---------- loop ----------
let roomTick = 0; const clock = new THREE.Clock();
// adaptive resolution: shading cost is per pixel (Safari on Retina was fill-bound), so trade sharpness for smoothness only when needed
const PR_MAX = () => Math.min(devicePixelRatio, mode === 'walk' ? 1.5 : 2); let prAvg = 1 / 60, prT = 0;
function adapt(raw) {
  if (raw > 0.25) return;   // tab switch, compile, alert: not a rendering cost
  prAvg += (raw - prAvg) * 0.05; if ((prT += raw) < 1.2) return; prT = 0;
  const pr = renderer.getPixelRatio(), max = PR_MAX(); queueMicrotask(() => { if (renderer.getPixelRatio() !== pr) amb?.resize(); });
  if (prAvg > 1 / 55 && pr > 1) renderer.setPixelRatio(Math.max(1, +(pr - 0.25).toFixed(2)));
  else if (prAvg < 1 / 75 && pr < max) renderer.setPixelRatio(Math.min(max, +(pr + 0.25).toFixed(2)));
  else if (pr > max) renderer.setPixelRatio(max);
}
let holdRender = true;   // until furniture and lamps are in: Safari compiles shaders serially, one light-count change = every material recompiled
renderer.setAnimationLoop(() => {
  const raw = clock.getDelta(), dt = Math.min(raw, 0.05); if (holdRender) return; adapt(raw);
  if (glide) { const k = Math.min(1, (performance.now() - glide.start) / glide.ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    camera.position.lerpVectors(glide.p0, glide.p1, e); orbit.target.lerpVectors(glide.t0, glide.t1, e); if (k >= 1) glide = null; }
  if (mode === 'doll') orbit.update();
  else if ((roomTick += dt) > 0.5) { roomTick = 0; const r = currentRoom(); if (r && r !== activeRoom) activateRoom(r); }
  if (mode === 'walk' || mode === 'photo') outside?.update();
  if (captureReq) { const c = captureReq; captureReq = null; try { c.res(doCapture(c.i)); } catch (e) { console.warn('[stage] capture', e); c.res(Promise.reject(e)); } }
  if (mode !== 'photo') { if (amb) amb.render(dt); else renderer.render(scene, camera); }   // photos mode draws no 3D (captures above still run)
  drawPlanMarker();
});
addEventListener('resize', frameView);
let outside = null, planName = '';
const amb = createAmbiance({ renderer, scene, camera, apt, layout, sun, hemi, center, ext, sunAz, furn, Furnish,
  outside: { get world() { return outside?.world; }, get sky() { return outside?.sky; }, setTime: h => outside?.setTime(h) } });
window.ambiance = amb;
for (const b of document.querySelectorAll('[data-mood]')) { b.setAttribute('aria-pressed', String(b.dataset.mood === amb.mood)); b.onclick = () => { amb.setMood(b.dataset.mood); for (const x of document.querySelectorAll('[data-mood]')) x.setAttribute('aria-pressed', String(x === b)); }; }
const listingId = unit.split('_plan_')[0];
const outsideReady = fetch('/map/listings.json').then(r => r.json()).then(d => (d.listings || []).find(l => l.id === listingId)).then(l => {
  outside = createOutside({ scene, camera, renderer, apt, layout, sun, hemi, lat: l ? +l.lat : NaN, lon: l ? +l.lon : NaN, planName: () => planName,
    onStatus: s => { if (s === 'measuring') toast('Bringing in the view outside…'); }, onLight: st => amb.fromOutside(st) });
  window.outside = outside; if (mode === 'walk') outside.enable(true);
}).catch(e => console.warn('[home] outside', e));
setDoll();
(async () => {
  await Promise.race([Promise.all(roomJobs), new Promise(r => setTimeout(r, 12000))]); hideAids(); amb.applyStyle($('style').value); amb.dress(); amb.budgetLights();
  try { await renderer.compileAsync(scene, camera); } catch (e) { renderer.compile(scene, camera); }
  holdRender = false; requestAnimationFrame(() => { $('loading').style.opacity = 0; setTimeout(() => $('loading').remove(), 700); });
})();

// ---------- title ----------
fetch('layouts/index.json').then(r => r.json()).then(units => {
  const u = units.find(x => x.unit === unit); if (!u) return; planName = u.plan_name || '';
  const beds = layout.rooms.filter(r => r.type === 'bedroom').length;
  $('title').textContent = [String(u.building || '').replace(/ Apartments.*$/, ''), u.plan_name].filter(Boolean).join(', ') || 'Your apartment';
  $('meta').textContent = `${beds ? beds + ' bedroom' + (beds > 1 ? 's' : '') : 'Studio'}, ${Math.round(u.area_m2)} m²`;
  document.title = `${$('title').textContent} · Move-in`;
}).catch(() => {});

// ---------- rooms menu, plan, help ----------
const ROOMS = [...layout.rooms].sort((a, b) => (b.area_m2 || 0) - (a.area_m2 || 0));
function closeMenus() { $('roomsMenu').hidden = true; $('roomsBtn').setAttribute('aria-expanded', 'false'); $('help').hidden = true; $('helpBtn').setAttribute('aria-expanded', 'false'); }
function placeAbove(menu, btn) { const r = btn.getBoundingClientRect(); menu.hidden = false; menu.style.left = Math.max(12, r.left + r.width / 2 - menu.offsetWidth / 2) + 'px'; menu.style.top = (r.top - menu.offsetHeight - 12) + 'px'; }
function refreshRoomUi() {
  $('roomsMenu').innerHTML = ROOMS.map(r => `<button role="menuitem" data-r="${r.id}" aria-current="${r.id === activeRoom}">${esc(r.name)}<span>${(r.area_m2 || 0).toFixed(1)} m²</span></button>`).join('');
  const rn = activeRoom ? roomName(activeRoom) : 'This room';
  $('scopeRoom').textContent = rn; $('budgetL').textContent = scope === 'home' ? 'Budget, whole home' : `Budget, ${rn.toLowerCase()}`;
  $('go').textContent = scope === 'home' ? 'Furnish whole home' : `Furnish ${rn.toLowerCase()}`;
  $('go').disabled = scope === 'home' ? !homeRooms().length : !furn[activeRoom];
  renderTotals();
}
$('roomsBtn').onclick = e => { e.stopPropagation(); const open = $('roomsMenu').hidden; closeMenus(); if (open) { refreshRoomUi(); placeAbove($('roomsMenu'), $('roomsBtn')); $('roomsBtn').setAttribute('aria-expanded', 'true'); } };
$('roomsMenu').onclick = e => { const b = e.target.closest('[data-r]'); if (!b) return; closeMenus(); const id = b.dataset.r; activateRoom(id); if (mode === 'walk') setWalk(id); else flyToRoom(id); };
$('helpBtn').onclick = e => { e.stopPropagation(); const open = $('help').hidden; closeMenus(); if (open) { placeAbove($('help'), $('helpBtn')); $('helpBtn').setAttribute('aria-expanded', 'true'); } };
addEventListener('click', e => { if (!e.target.closest('.menu,#help,#roomsBtn,#helpBtn')) closeMenus(); });
$('planBtn').onclick = () => { const on = $('planBtn').getAttribute('aria-pressed') !== 'true'; $('planBtn').setAttribute('aria-pressed', on); $('plan').hidden = !on; };

// floor plan with a you-are-here marker in walk view
const scl = layout.scale || {}, pimg = layout.plan_image || '', pi = pimg.indexOf('/listings/');
let planMarker = null;
if (pi < 0) { $('plan').hidden = true; $('planBtn').hidden = true; }
else {
  const img = $('planImg'); img.src = pimg.slice(pi);
  img.onload = () => { $('planSvg').setAttribute('viewBox', `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    $('planSvg').innerHTML = `<g id="pm" style="display:none"><path d="M0,0 L24,-11 L24,11 Z" fill="rgba(29,29,31,.28)"/><circle r="6" fill="#1d1d1f" stroke="#fff" stroke-width="2"/></g>`; planMarker = $('pm'); };
}
const dirV = new THREE.Vector3();
function drawPlanMarker() {
  if (!planMarker || !scl.m_per_px || !scl.origin_px) return;
  if (mode !== 'walk') { planMarker.style.display = 'none'; return; }
  const s = scl.image_scale || 1, [ox, oy] = scl.origin_px, img = $('planImg');
  const x = (camera.position.x / scl.m_per_px + ox) / s, y = (camera.position.z / scl.m_per_px + oy) / s; camera.getWorldDirection(dirV);
  planMarker.style.display = ''; planMarker.setAttribute('transform', `translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${(Math.atan2(dirV.z, dirV.x) * 180 / Math.PI).toFixed(1)}) scale(${(img.naturalWidth / (img.clientWidth || 1)).toFixed(3)})`);
}

// ---------- picking: click a piece or a floor to work on that room; hover shows name and price ----------
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(); let downAt = null;
function setNdc(e) { const r = renderer.domElement.getBoundingClientRect(); ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1); ray.setFromCamera(ndc, camera); }
function itemHit() { const hits = ray.intersectObjects(Object.values(furn).map(f => f.group), true); for (const h of hits) { let o = h.object; while (o && !o.userData?.item) o = o.parent; if (o) { const it = o.userData.item; const f = Object.values(furn).find(f => f.items.includes(it)); if (f) return { it, f }; } } return null; }
renderer.domElement.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', e => {
  if (!downAt || mode !== 'doll') return; const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]); downAt = null; if (moved > 4) return;
  setNdc(e); const hit = itemHit();
  if (hit) { const rid = hit.f.room.split('__')[1]; activateRoom(rid); hit.f.select(hit.it); return; }
  const floors = Object.entries(apt.roomMeshes).map(([id, r]) => { r.floor.userData.roomId = id; return r.floor; });
  const fh = ray.intersectObjects(floors, false)[0]; if (fh) activateRoom(fh.object.userData.roomId);
});
let hoverQueued = null;
renderer.domElement.addEventListener('pointermove', e => { hoverQueued = e; });
renderer.domElement.addEventListener('pointerleave', () => { $('tip').hidden = true; hoverQueued = null; });
(function hover() { requestAnimationFrame(hover); const e = hoverQueued; hoverQueued = null; if (!e) return;
  if (mode !== 'doll' || e.buttons) { $('tip').hidden = true; return; }
  setNdc(e); const hit = itemHit(); if (!hit) { $('tip').hidden = true; renderer.domElement.style.cursor = ''; return; }
  const n = shortName(hit.it.spec.name); $('tip').innerHTML = `<b>${esc(n.name)}</b>${hit.it.spec.price_usd ? money(+hit.it.spec.price_usd) : ''}`;
  $('tip').style.left = e.clientX + 'px'; $('tip').style.top = e.clientY + 'px'; $('tip').hidden = false; renderer.domElement.style.cursor = 'grab'; })();

// ---------- the design sheet ----------
const ag = id => document.getElementById(id);   // agent.js elements (its panel is hidden)
let budget = Math.max(500, +(Q.get('budget') || 3500)), tier = Q.get('tier') || 'any', scope = Q.get('scope') === 'home' || Q.get('furnish') === 'home' ? 'home' : 'room', homeRun = null;
const styleQ = Q.get('style'); if (styleQ && ![...$('style').options].some(o => o.value === styleQ.toLowerCase())) $('style').add(new Option(styleQ.replace(/\b\w/g, c => c.toUpperCase()), styleQ.toLowerCase()), 0);
if (styleQ) $('style').value = styleQ.toLowerCase();
function syncAgent() { if (ag('aiBudget')) ag('aiBudget').value = Math.max(0, Math.floor(scope === 'home' ? budget - spendOutside(activeRoom) : budget)); if (ag('aiStyle')) ag('aiStyle').value = $('style').value; if (ag('aiTier')) ag('aiTier').value = tier; }
function drawBudget() { $('budget').textContent = money(budget); renderTotals(); }
$('bMinus').onclick = () => { budget = Math.max(500, budget - 250); drawBudget(); syncAgent(); };
$('bPlus').onclick = () => { budget = Math.min(25000, budget + 250); drawBudget(); syncAgent(); };
window.setDesignBudget = v => { budget = Math.max(0, Math.min(25000, Math.floor(+v || 0))); drawBudget(); syncAgent(); };   // furnish/bank.js (Nessie)
$('style').onchange = () => { syncAgent(); amb?.applyStyle($('style').value); };
for (const b of $('scope').querySelectorAll('button')) { b.setAttribute('aria-pressed', b.dataset.v === scope); b.onclick = () => { if (homeRun) return; scope = b.dataset.v; for (const x of $('scope').querySelectorAll('button')) x.setAttribute('aria-pressed', x === b); refreshRoomUi(); syncAgent(); }; }
for (const b of $('tier').querySelectorAll('button')) { b.setAttribute('aria-pressed', b.dataset.v === tier); b.onclick = () => { tier = b.dataset.v; for (const x of $('tier').querySelectorAll('button')) x.setAttribute('aria-pressed', x === b); syncAgent(); }; }

const why = {}, rejected = {}, chat = []; let status = '', running = false;
function shortName(full) {   // "BESTÅ TV bench with drawers - white stained oak effect/Lappviken 47 1/4x16 "" -> name + finish
  const s = String(full || ''); const i = s.indexOf(' - '); const name = i > 0 ? s.slice(0, i) : s;
  let v = i > 0 ? s.slice(i + 3) : ''; v = v.split('/')[0].replace(/\s*\d[\d\s\/x'".,½¼¾]*["']?\s*$/, '').replace(/\s*\d[\d\s\/x'".,]*\s*$/, '').trim();
  return { name, variant: v };
}
function imgSrc(spec) { const s = spec.image; if (!s) return ''; return /^https?:\/\//.test(s) ? `/api/img?u=${encodeURIComponent(s)}` : '/' + s.replace(/^\.?\//, ''); }   // plan paths are relative to app/
function friendlyProblem(p) { if (/model missing/.test(p)) return null; if (/walking path|blocks/.test(p)) return 'Blocks the walkway'; if (/outside/.test(p)) return 'Sits outside the walls'; if (/overlap/.test(p)) return 'Overlaps another piece'; if (/door/.test(p)) return 'In the way of a door'; if (/window/.test(p)) return 'In front of a window'; return p.charAt(0).toUpperCase() + p.slice(1); }
function totals() { let sum = 0, n = 0; const rooms = []; for (const [rid, f] of Object.entries(furn)) { const items = f.items.filter(it => it.spec.category !== 'fixture'); if (!items.length) continue; rooms.push(f.room); for (const it of items) { sum += +it.spec.price_usd || 0; n++; } } return { sum, n, rooms }; }
const roomSpend = rid => (furn[rid]?.items || []).filter(it => it.spec.category !== 'fixture').reduce((s, it) => s + (+it.spec.price_usd || 0), 0);
const spendOutside = rid => Object.keys(furn).filter(k => k !== rid).reduce((s, k) => s + roomSpend(k), 0);
function renderTotals() {
  const t = totals(), shown = scope === 'home' ? t.sum : roomSpend(activeRoom), pct = budget ? shown / budget * 100 : 0;
  const n = scope === 'home' ? t.n : (furn[activeRoom]?.items || []).filter(it => it.spec.category !== 'fixture').length;
  $('spent').textContent = `${money(shown)} of ${money(budget)}`; $('spentL').textContent = (running || homeRun) && status ? status : (n ? `${n} piece${n > 1 ? 's' : ''}${scope === 'home' ? '' : ` in the ${roomName(activeRoom).toLowerCase()}`}` : 'Nothing yet');
  $('meter').querySelector('i').style.width = Math.min(100, pct) + '%'; $('meter').classList.toggle('over', pct > 100);
  const movein = new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10);
  $('order').classList.toggle('off', !t.rooms.length); $('orderTotal').textContent = t.rooms.length ? money(t.sum) : '';
  $('order').href = t.rooms.length ? `../checkout/order.html?rooms=${t.rooms.join(',')}&budget=${budget}&movein=${movein}` : '#';
}
function renderItems() {
  renderTotals();
  const order = [activeRoom, ...ROOMS.map(r => r.id).filter(id => id !== activeRoom)];
  let html = '';
  for (const rid of order) {
    const f = furn[rid]; if (!f) continue; const items = f.items.filter(it => it.spec.category !== 'fixture'); const rej = rejected[rid] || [];
    if (!items.length && !rej.length && rid !== activeRoom) continue;
    const sub = items.reduce((s, it) => s + (+it.spec.price_usd || 0), 0);
    html += `<div class="room"><span>${esc(roomName(rid))}</span><span>${items.length ? money(sub) : ''}</span></div>`;
    if (!items.length && !rej.length) html += `<div class="empty">${running ? 'The designer is choosing pieces…' : `Nothing in the ${esc(roomName(rid).toLowerCase())} yet.<br>Set a budget and style, then furnish it.`}</div>`;
    for (const it of items) { const n = shortName(it.spec.name), pr = (it.problems || []).map(friendlyProblem).filter(Boolean)[0], w = why[it.spec.name];
      html += `<div class="item${f.selected === it ? ' sel' : ''}" data-room="${rid}" data-id="${esc(it.spec.id)}">
        ${imgSrc(it.spec) ? `<div class="ph" style="background-image:url('${esc(imgSrc(it.spec))}')"></div>` : `<div class="ph none" aria-hidden="true">${esc(n.name.charAt(0))}</div>`}
        <div><div class="nm">${esc(n.name)}</div>${n.variant ? `<div class="vr">${esc(n.variant)}</div>` : ''}${w ? `<div class="why">${esc(w)}</div>` : ''}${pr ? `<div class="warn">${esc(pr)}</div>` : ''}
          <div class="acts"><button data-act="swap">Swap</button><button data-act="remove">Remove</button>${it.spec.product_url ? `<a class="muted" href="${esc(it.spec.product_url)}" target="_blank" rel="noopener" style="text-decoration:none">View</a>` : ''}</div></div>
        <div class="pr">${it.spec.price_usd ? money(+it.spec.price_usd) : ''}</div></div>`; }
    for (const r of rej) html += `<div class="line rejected">Left out ${esc(shortName(r.name).name)}: ${esc(r.reason)}</div>`;
  }
  for (const c of chat) html += `<div class="line ${c.who}">${esc(c.text)}</div>`;
  const feed = $('feed'), atEnd = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
  feed.innerHTML = html || `<div class="empty">Set a budget and style, then let the designer furnish a room.</div>`;
  if (chat.length && atEnd) feed.scrollTop = feed.scrollHeight;
}
$('feed').addEventListener('click', e => {
  const row = e.target.closest('.item'); if (!row) return; const f = furn[row.dataset.room]; const it = f && f.items.find(x => String(x.spec.id) === row.dataset.id); if (!it) return;
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'remove') { f.remove(it); changed(); return; }
  if (act === 'swap') { activateRoom(row.dataset.room); ask(`Swap the ${shortName(it.spec.name).name} for a different piece that fits the style and budget.`); return; }
  if (e.target.closest('a')) return;
  activateRoom(row.dataset.room); f.select(it); if (mode === 'doll') flyTo(camera.position.clone().lerp(new THREE.Vector3(it.spec.x, camera.position.y * 0.7, it.spec.z), 0.25), new THREE.Vector3(it.spec.x, 0.3, it.spec.z), 700);
});

// run, stop, chat: through agent.js
// whole home: one budget across the rooms worth furnishing, split by size and kind of room; what a room leaves unspent rolls on
const SKIP = new Set(['hallway', 'closet', 'bathroom', 'entry', 'laundry', 'balcony', 'patio', 'storage', 'utility']);
const KIND = { living: 1.35, bedroom: 1.15, dining: 0.95, office: 0.9, kitchen: 0.45 };
const homeRooms = () => layout.rooms.filter(r => furn[r.id] && !SKIP.has(r.type) && !/closet|hall|entry|laundry|bath|balcony|patio|storage/i.test(r.name));
const weight = r => Math.max(4, r.area_m2 || 10) * (KIND[r.type] ?? 0.8);
function runOne(rid, roomBudget) {   // one agent.js run for one room, resolved when its Stop button hides again
  return new Promise(resolve => {
    activateRoom(rid); ag('aiBudget').value = Math.max(0, Math.floor(roomBudget)); ag('aiStyle').value = $('style').value; if (ag('aiTier')) ag('aiTier').value = tier;
    rejected[rid] = []; ag('aiGo').click();
    let started = false; const t0 = performance.now();
    const tick = setInterval(() => { const on = ag('aiStop').style.display !== 'none'; if (on) started = true;
      if ((started && !on) || (!started && performance.now() - t0 > 4000)) { clearInterval(tick); resolve(); } }, 150);
  });
}
async function furnishHome() {
  const rooms = homeRooms().sort((a, b) => weight(b) - weight(a)); if (!rooms.length) return;
  homeRun = { cancelled: false }; const run = homeRun; $('go').hidden = true; $('stop').hidden = false;
  const others = Object.keys(furn).filter(k => !rooms.some(r => r.id === k)).reduce((s, k) => s + roomSpend(k), 0);   // pieces in rooms we leave alone still count
  let left = budget - others;
  for (let i = 0; i < rooms.length && !run.cancelled && left > 50; i++) {
    const rest = rooms.slice(i), share = left * weight(rooms[i]) / rest.reduce((s, r) => s + weight(r), 0);
    status = `${roomName(rooms[i].id)}: ${money(share)} of ${money(left)} left`; changed();
    await runOne(rooms[i].id, share);
    left -= roomSpend(rooms[i].id);
  }
  homeRun = null; status = ''; $('go').hidden = false; $('stop').hidden = true; refreshRoomUi(); changed();
  if (mode === 'doll') setDoll();   // the agent flies into each room it works on; end on the whole home
}
$('go').onclick = () => { if (scope === 'home') return furnishHome(); if (!furn[activeRoom]) return; syncAgent(); rejected[activeRoom] = []; ag('aiGo')?.click(); };
$('stop').onclick = () => { if (homeRun) homeRun.cancelled = true; ag('aiStop')?.click(); };
function ask(text) { if (!text || !ag('aiSend')) return; syncAgent(); chat.push({ who: 'you', text }); renderItems(); ag('aiChat').value = text; ag('aiSend').click(); }
$('ask').onsubmit = e => { e.preventDefault(); const t = $('msg').value.trim(); $('msg').value = ''; ask(t); };

function readAgentLine(node) {   // agent.js log lines -> sheet state
  const t = node.textContent.trim(), rid = activeRoom;
  let m;
  if ((m = /^✓ placed (.+?) · (.*)$/.exec(t))) { why[m[1].trim()] = m[2].trim(); status = `Placed ${shortName(m[1]).name}`; }
  else if ((m = /^✓ placed (.+)$/.exec(t))) status = `Placed ${shortName(m[1]).name}`;
  else if ((m = /^✗ rejected (.+?): (.*)$/.exec(t))) { (rejected[rid] ||= []).push({ name: m[1], reason: m[2] }); status = `Left out ${shortName(m[1]).name}`; }
  else if ((m = /^considering (.+?)(\s\$[\d.]+)?$/.exec(t))) status = `Considering ${shortName(m[1]).name}`;
  else if ((m = /^agent: ([\s\S]*)$/.exec(t))) chat.push({ who: 'agent', text: m[1] });
  else if (/^Palette:/.test(t)) status = 'Choosing a palette';
  else if (/^error/.test(t)) { status = ''; toast(t.replace(/^error:\s*/, '')); }
  changed();
}
function toast(msg) { const el = $('toast'); el.textContent = msg; el.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('show'), 2400); }
(async function hookAgent() {
  while (!ag('aiLog') || !ag('aiStop')) await new Promise(r => setTimeout(r, 100));
  syncAgent();
  new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) readAgentLine(n); }).observe(ag('aiLog'), { childList: true });
  const watchRun = () => { const on = ag('aiStop').style.display !== 'none'; if (on === running) return; running = on; if (!homeRun) { $('stop').hidden = !on; $('go').hidden = on; if (!on) status = ''; } changed(); };
  new MutationObserver(watchRun).observe(ag('aiStop'), { attributes: true, attributeFilter: ['style'] }); watchRun();
})();

// ---------- start ----------
drawBudget(); refreshRoomUi(); renderItems();
await Promise.all(roomJobs);
const startRoom = Q.get('room') || Q.get('agent') || (layout.rooms.find(r => r.type === 'living') || ROOMS[0]).id;
activateRoom(startRoom);
if (Q.get('view') === 'walk') setWalk(startRoom);
if (Q.get('furnish') === 'home') { while (!ag('aiGo')) await new Promise(r => setTimeout(r, 100)); furnishHome(); }   // landing: "Furnish this home"

