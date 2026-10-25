// Light stage for the landing page and its thumbnails: one apartment as a dollhouse in low sun on a transparent canvas,
// shadows caught on the page itself. Reuses the plan engine (build.js) and the furnishing layer read-only.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { Apartment, MaterialLib } from '../build.js';
import { Furnish } from '../../furnish/furnish.js';

const D2R = Math.PI / 180;

export async function mountStage(host, o = {}) {
  const opt = { unit: 'gs-22612_plan_03', furnish: true, cut: 1.2, view: 35, pitch: 50, fov: 26, fit: 1.0, shiftX: 0, shiftY: 0,
    sunTurn: 65, sunElevation: 30, exposure: 1.0, sway: 0, interactive: false, preserve: false, shadowSize: 4096,
    pixelRatio: Math.min(devicePixelRatio, 2), ...o };
  const size = () => [Math.max(1, host.clientWidth), Math.max(1, host.clientHeight)];
  let [W, H] = size();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: opt.preserve });
  renderer.setPixelRatio(opt.pixelRatio); renderer.setSize(W, H); renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.localClippingEnabled = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = opt.exposure; renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(opt.fov, W / H, 0.1, 500);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; scene.environmentIntensity = 0.42;

  const lib = await new MaterialLib('/furnish/materials/').load();
  const layout = await (await fetch(`/plan3d/layouts/${opt.unit}.json`)).json();
  const apt = new Apartment(layout, lib); scene.add(apt.group);
  apt.labels.forEach(l => l.visible = false); apt.ceilingMeshes.forEach(m => m.visible = false);
  const clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), opt.cut); apt.section(opt.cut);
  apt.group.traverse(m => { if (m.isMesh && m.material && m.userData.kind !== 'wall') for (const mm of [].concat(m.material)) { mm.clippingPlanes = [clip]; mm.clipShadows = true; } });

  const bb = apt.bounds, c = bb.getCenter(new THREE.Vector3()), s = bb.getSize(new THREE.Vector3());
  const radius = Math.hypot(s.x, s.z) / 2, target = new THREE.Vector3(c.x, 0.3, c.z);

  // low sun from the camera's side, so facades are lit and the shadows run across the page
  const sun = new THREE.DirectionalLight(0xffdcb4, 3.1); sun.castShadow = true;
  sun.shadow.mapSize.set(opt.shadowSize, opt.shadowSize); sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.03; sun.shadow.radius = 4;
  const sc = sun.shadow.camera; sc.left = sc.bottom = -radius * 2.2; sc.right = sc.top = radius * 2.2; sc.near = 0.5; sc.far = radius * 12; sc.updateProjectionMatrix();
  scene.add(sun, sun.target); sun.target.position.copy(target);
  scene.add(new THREE.HemisphereLight(0xe9f0ff, 0xf2e6d6, 0.7));   // cool sky fill against the warm sun, the way late light looks
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(radius * 30, radius * 30), new THREE.ShadowMaterial({ color: 0x4a3a2c, opacity: 0.2 }));
  ground.rotation.x = -Math.PI / 2; ground.position.set(c.x, -0.004, c.z); ground.receiveShadow = true; scene.add(ground);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enabled = opt.interactive; controls.enableZoom = false; controls.enablePan = false; controls.enableDamping = true; controls.dampingFactor = 0.06;
  controls.minPolarAngle = 20 * D2R; controls.maxPolarAngle = 70 * D2R; controls.target.copy(target);
  let touched = false; controls.addEventListener('start', () => { touched = true; });

  function frame(az) {
    const el = opt.pitch * D2R, vf = camera.fov * D2R, hf = 2 * Math.atan(Math.tan(vf / 2) * camera.aspect);
    const dist = radius / Math.sin(Math.min(vf, hf) / 2) * opt.fit;
    camera.position.set(target.x + Math.sin(az) * Math.cos(el) * dist, target.y + Math.sin(el) * dist, target.z + Math.cos(az) * Math.cos(el) * dist);
    camera.lookAt(target); controls.update();
  }
  function place() {
    [W, H] = size(); renderer.setSize(W, H, false); renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
    camera.aspect = W / H; camera.clearViewOffset();
    if (opt.shiftX || opt.shiftY) camera.setViewOffset(W, H, -opt.shiftX * W, -opt.shiftY * H, W, H);
    camera.updateProjectionMatrix(); if (!touched) frame(opt.view * D2R);
  }
  const sunAz = (opt.view + opt.sunTurn) * D2R, sel = opt.sunElevation * D2R;
  sun.position.copy(target).add(new THREE.Vector3(Math.sin(sunAz) * Math.cos(sel), Math.sin(sel), Math.cos(sunAz) * Math.cos(sel)).multiplyScalar(radius * 5));
  place(); new ResizeObserver(place).observe(host);

  // furniture: the saved plans of this unit's rooms, models only (no labels, footprints or fit colours)
  const furns = [];
  if (opt.furnish) for (const r of layout.rooms) {
    try { const res = await fetch(`/rooms/${layout.unit}__${r.id}.json`); if (!res.ok) continue;
      const f = new Furnish({ scene, camera, renderer, controls, panelEl: null, toastEl: null, active: false });
      await f.setRoom(`${layout.unit}__${r.id}`, await res.json()); f.setClipping([clip]); furns.push(f);
    } catch (e) { console.warn('[stage] furnish', r.id, e); }
  }
  for (const f of furns) for (const it of f.items) { it.label.visible = false; it.fp.visible = false; it.fm.visible = false; }

  // render only while on screen; a slow sway unless reduced motion is asked for or the visitor has taken the camera
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches; let onScreen = true, t0 = performance.now();
  new IntersectionObserver(es => { onScreen = es[0].isIntersecting; }).observe(host);
  (function loop(now) {
    requestAnimationFrame(loop); if (!onScreen) return;
    if (opt.sway && !still && !touched) frame((opt.view + Math.sin((now - t0) / 1000 * 0.12) * opt.sway) * D2R);
    else controls.update();
    renderer.render(scene, camera);
  })(t0);
  renderer.render(scene, camera);
  host.dataset.ready = '1';
  return { renderer, scene, camera, apt, layout, furns };
}
