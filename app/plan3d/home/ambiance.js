// Ambiance for the customer apartment page: light with contrast, a photographic post chain, and materials that answer the light.
//  - mood: 'day' or 'golden' (toggle). Overview sets its own sun; Walk takes the real sun for the address from outside.js
//    (hour per mood) and this module re-balances it (strong sun, low fill), via fromOutside().
//  - window light: a FIXED pool of 3 rect area lights at the windows of the room you are in (soft daylight spilling into the
//    room); only positions and intensities change, never the light count, so no shader ever recompiles.
//  - post: render -> ground-truth AO at half resolution (the city tiles are left out of the AO pass) -> bloom at half
//    resolution (windows, lamps) -> output (AgX tone curve) -> grade (saturation, warm highlights / cool shadows, vignette,
//    fine grain).
//  - walls from the chosen style (one base tone + one accent wall in the main room); fabrics get sheen, wood a soft clearcoat,
//    wood floors a little gloss.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

const STYLE_WALLS = {   // base wall tone, accent wall tone (soft, chalky paints)
  'warm scandinavian': ['#ede6dc', '#c8b6a0'], 'japandi': ['#ebe4d9', '#b5987c'], 'mid-century modern': ['#eee7db', '#7f8d70'],
  'quiet minimal': ['#f0eee9', '#d6d1c7'], 'coastal': ['#eef0ec', '#9fb6bf'], default: ['#ece7df', '#cbbba8'],
};
const MOODS = {
  // overview: sun / fill / exposure; walk (w*): the sun enters through the room's biggest window, little fill, strong window light
  day:    { hour: 13.0, elev: 52, sun: 0xfff3e2, sunI: 3.6, hemi: 0.42, env: 0.5, exp: 1.0, win: 0, winCol: 0xeef4ff, lamps: 0.15, bloom: 0.18, warm: 0.35, sat: 1.08, con: 0.3, bg: ['#ffffff', '#ecebe8'],
            wElev: 36, wSun: 0xfff1de, wSunI: 12, wHemi: 0.1, wEnv: 0.18, wWin: 5, wExp: 1.05 },
  golden: { hour: 17.7, elev: 13, sun: 0xffa75e, sunI: 4.4, hemi: 0.22, env: 0.3, exp: 0.95, win: 0, winCol: 0xffd9b0, lamps: 0.9, bloom: 0.32, warm: 1.0, sat: 1.12, con: 0.38, bg: ['#fff8f0', '#efe4d8'],
            wElev: 22, wSun: 0xffa45c, wSunI: 18, wHemi: 0.06, wEnv: 0.12, wWin: 3.5, wExp: 1.05 },
};
const FABRIC = /sofa|armchair|chair|bed|rug|cushion|pouf|ottoman|bench|stool|headboard|throw|duvet/, WOOD = /table|desk|dresser|nightstand|tv_bench|bookcase|shelf|sideboard|cabinet|wardrobe|chest/;

export function createAmbiance({ renderer, scene, camera, apt, layout, sun, hemi, center, ext, sunAz, furn, outside, Furnish }) {
  const mood = { name: localStorage.getItem('mood') === 'day' ? 'day' : 'golden', mode: 'doll' };
  renderer.toneMapping = THREE.AgXToneMapping;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.map?.dispose(); sun.shadow.map = null;   // room-scale shadows stay crisp at 2k; 4k cost a full frame in Safari

  // ---------- background for the overview (the composer needs an opaque frame) ----------
  const bgCanvas = document.createElement('canvas'); bgCanvas.width = 4; bgCanvas.height = 256; const bgTex = new THREE.CanvasTexture(bgCanvas); bgTex.colorSpace = THREE.SRGBColorSpace;
  function paintBg(c0, c1) { const g = bgCanvas.getContext('2d'), gr = g.createLinearGradient(0, 0, 0, 256); gr.addColorStop(0, c0); gr.addColorStop(1, c1); g.fillStyle = gr; g.fillRect(0, 0, 4, 256); bgTex.needsUpdate = true; }

  // ---------- window lights: fixed pool ----------
  // spot lights, not rect area lights: the same soft inward spill at a fraction of the per-pixel cost (area lights cost 30% of a frame)
  const pool = [0, 1, 2].map(() => { const l = new THREE.SpotLight(0xffffff, 0, 9, THREE.MathUtils.degToRad(68), 1.0, 1.6); scene.add(l, l.target); return l; });
  const walls = new Map(layout.walls.map(w => [w.id, w]));
  const centroid = r => r.polygon.reduce((s, p) => s.add(new THREE.Vector2(p[0], p[1])), new THREE.Vector2()).multiplyScalar(1 / r.polygon.length);
  function windowsOf(roomId) {
    const out = [];
    for (const o of layout.openings) {
      if (o.type !== 'window') continue; const w = walls.get(o.wall); if (!w) continue;
      const a = new THREE.Vector2(...w.a), b = new THREE.Vector2(...w.b), d = b.clone().sub(a); const L = d.length() || 1; d.divideScalar(L);
      const mid = a.clone().add(d.clone().multiplyScalar((o.s0 + o.s1) / 2)); let n = new THREE.Vector2(-d.y, d.x);
      const room = layout.rooms.find(r => r.id === o.room) || null; const c = room ? centroid(room) : new THREE.Vector2(center.x, center.z);
      if (c.clone().sub(mid).dot(n) < 0) n.negate();   // n points into the room
      const sill = o.sill_m ?? 0.9, h = o.height_m ?? 1.3, t = w.thickness_m || 0.15;
      out.push({ room: o.room, w: o.s1 - o.s0, h, pos: new THREE.Vector3(mid.x + n.x * (t / 2 + 0.04), sill + h / 2, mid.y + n.y * (t / 2 + 0.04)), n });
    }
    const mine = out.filter(x => x.room === roomId).sort((p, q) => q.w - p.w), rest = out.filter(x => x.room !== roomId).sort((p, q) => q.w - p.w);
    return [...mine, ...rest].slice(0, 3);
  }
  let winRoom = null;
  function placeWindowLights(roomId, force = false) {
    if (roomId === winRoom && !force) return; winRoom = roomId; const M = MOODS[mood.name], ws = windowsOf(roomId);
    pool.forEach((l, i) => { const w = ws[i];
      if (!w) { l.intensity = 0; return; }
      l.position.copy(w.pos); l.target.position.set(w.pos.x + w.n.x * 2.5, 0.2, w.pos.z + w.n.y * 2.5);
      l.color.setHex(M.winCol); l.intensity = (mood.mode === "walk" ? M.wWin : M.win) * 2.2 * Math.max(0.6, w.w * w.h / 1.6) * (w.room === roomId ? 1 : 0.35); });
    if (mood.mode === 'walk') aimSun();
  }

  // ---------- post chain ----------
  const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 2 }));
  const renderPass = new RenderPass(scene, camera); composer.addPass(renderPass);
  const gtao = new GTAOPass(scene, camera, 2, 2); gtao.output = GTAOPass.OUTPUT.Default; gtao.blendIntensity = 0.85;
  gtao.updateGtaoMaterial({ radius: 0.6, distanceExponent: 1.4, thickness: 1.2, scale: 1.4, samples: 8, distanceFallOff: 0.8, screenSpaceRadius: false });
  gtao.updatePdMaterial({ lumaPhi: 8, depthPhi: 2.5, normalPhi: 3, radius: 8, rings: 2, samples: 8 });
  const gtaoRender = gtao.render.bind(gtao), gtaoSize = gtao.setSize.bind(gtao);
  gtao.render = (...a) => {   // AO without the city: far, hazed, and a million triangles
    const w = outside?.world, s = outside?.sky, wv = w && w.visible, sv = s && s.visible, bg = scene.background;
    if (w) w.visible = false; if (s) s.visible = false; scene.background = null;
    try { gtaoRender(...a); } finally { if (w) w.visible = wv; if (s) s.visible = sv; scene.background = bg; }
  };
  gtao.setSize = (w, h) => gtaoSize(Math.max(2, Math.round(w / 2)), Math.max(2, Math.round(h / 2)));   // half resolution
  composer.addPass(gtao);
  const bloom = new UnrealBloomPass(new THREE.Vector2(2, 2), 0.25, 0.55, 0.92); const bloomSize = bloom.setSize.bind(bloom);
  bloom.setSize = (w, h) => bloomSize(Math.max(2, Math.round(w / 2)), Math.max(2, Math.round(h / 2))); composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const grade = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uSat: { value: 1.1 }, uWarm: { value: 1 }, uVig: { value: 0.28 }, uGrain: { value: 0.022 }, uCon: { value: 0.35 } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime, uSat, uWarm, uVig, uGrain, uCon; varying vec2 vUv;
      float rnd(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main(){ vec4 c = texture2D(tDiffuse, vUv); vec3 col = c.rgb; float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
        col = mix(vec3(l), col, uSat);
        col = mix(col, col * col * (3.0 - 2.0 * col), uCon);   // gentle S-curve: deeper shade, brighter light
        col += uWarm * (vec3(0.045, 0.018, -0.03) * smoothstep(0.4, 1.0, l) + vec3(-0.012, 0.0, 0.022) * (1.0 - smoothstep(0.0, 0.42, l)));   // warm light, cool shade
        vec2 d = vUv - 0.5; col *= 1.0 - uVig * dot(d, d) * 1.7;
        col += (rnd(vUv * vec2(1733.0, 977.0) + fract(uTime)) - 0.5) * uGrain;
        gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0); }`,
  });
  composer.addPass(grade);
  function resize() { composer.setPixelRatio(renderer.getPixelRatio()); composer.setSize(innerWidth, innerHeight); }
  resize();

  // ---------- materials ----------
  function applyStyle(style) {
    const [base, accent] = STYLE_WALLS[String(style || '').toLowerCase()] || STYLE_WALLS.default;
    const src = apt.wallMeshes[0]?.material; if (!src) return;
    const baseM = src.clone(); baseM.color.set(base); baseM.roughness = 0.9;
    const accM = src.clone(); accM.color.set(accent); accM.roughness = 0.92;
    // accent: in the main room, the longest wall stretch without openings (prefer one with nothing on the other side)
    const main = layout.rooms.find(r => r.type === 'living') || [...layout.rooms].sort((a, b) => (b.area_m2 || 0) - (a.area_m2 || 0))[0];
    const busy = new Set(layout.openings.map(o => o.wall)); let best = null;
    if (main) for (const w of layout.walls) {
      if (busy.has(w.id)) continue; const a = new THREE.Vector2(...w.a), b = new THREE.Vector2(...w.b), m = a.clone().add(b).multiplyScalar(0.5), len = a.distanceTo(b);
      if (len < 1.8) continue; const near = main.polygon.some((p, i) => { const q = main.polygon[(i + 1) % main.polygon.length], e = new THREE.Vector2(q[0] - p[0], q[1] - p[1]), t = Math.max(0, Math.min(1, m.clone().sub(new THREE.Vector2(...p)).dot(e) / (e.lengthSq() || 1))); return m.distanceTo(new THREE.Vector2(p[0] + e.x * t, p[1] + e.y * t)) < 0.35; });
      if (!near) continue; const score = len + (w.exterior ? 2 : 0); if (!best || score > best.score) best = { id: w.id, score };
    }
    for (const m of apt.wallMeshes) m.material = best && m.userData.wall === best.id ? accM : baseM;
    apt.group.traverse(o => { if (/^pfloor_/.test(o.name) && o.material && o.material.userData && o.material.userData.category === 'wood_floor' && !o.material.userData.amb) {
      o.material.userData.amb = true; o.material.roughness = Math.min(o.material.roughness, 0.38); o.material.envMapIntensity = 1.0; } });
  }
  function budgetLights(maxLamps = 6) {   // per-pixel cost grows with every light, even at zero intensity: fixed budget before the compile
    for (const l of apt.lights) l.parent?.remove(l); apt.lights.length = 0;   // room ceiling-fixture lights (their glowing discs stay)
    const lamps = []; for (const f of Object.values(furn)) for (const it of f.items) if (it.lamp && it.lamp.light) lamps.push(it);
    lamps.sort((a, b) => (b.lamp.base || 0) - (a.lamp.base || 0));
    lamps.forEach((it, i) => { if (i >= maxLamps) { it.lamp.light.parent?.remove(it.lamp.light); it.lamp.light.intensity = 0; } });   // halo and glow stay
  }
  function dress() {   // furniture finishes: fabric sheen, wood clearcoat (once per material)
    for (const f of Object.values(furn)) for (const it of f.items) {
      const cat = String(it.spec.category || ''); const fab = FABRIC.test(cat), wood = WOOD.test(cat); if (!fab && !wood) continue;
      it.obj.traverse(o => {
        if (!o.isMesh || !o.material || o.userData.ambDone) return; let prop = false; for (let p = o; p; p = p.parent) if (p.userData && p.userData.prop) { prop = true; break; }
        if (prop) return; o.userData.ambDone = true;
        const conv = m => {
          if (!m || !m.isMeshStandardMaterial || m.metalness > 0.3) return m;
          const p = m.isMeshPhysicalMaterial ? m : (() => { const n = new THREE.MeshPhysicalMaterial(); THREE.MeshStandardMaterial.prototype.copy.call(n, m); return n; })();
          if (fab && m.roughness > 0.45) { p.sheen = 0.55; p.sheenRoughness = 0.75; p.sheenColor = p.color.clone().lerp(new THREE.Color(1, 1, 1), 0.35); }
          else if (wood) { p.clearcoat = 0.22; p.clearcoatRoughness = 0.38; p.roughness = Math.min(p.roughness, 0.6); }
          return p;
        };
        o.material = Array.isArray(o.material) ? o.material.map(conv) : conv(o.material);
      });
    }
  }

  // ---------- mood ----------
  function setMood(name) { if (MOODS[name]) { mood.name = name; localStorage.setItem('mood', name); } apply(); }
  function apply() {
    const M = MOODS[mood.name];
    bloom.strength = M.bloom; grade.uniforms.uWarm.value = M.warm; grade.uniforms.uSat.value = M.sat; Furnish?.setLampLevel?.(M.lamps);
    grade.uniforms.uCon.value = M.con;
    if (mood.mode === 'walk') { outside?.setTime?.(M.hour); aimSun(); }
    else if (mood.mode === 'doll') {
      sun.target.position.copy(center);
      paintBg(...M.bg); scene.background = bgTex;
      const el = THREE.MathUtils.degToRad(M.elev); sun.color.setHex(M.sun); sun.intensity = M.sunI; sun.visible = true;
      sun.position.copy(center).add(new THREE.Vector3(Math.sin(sunAz) * Math.cos(el), Math.sin(el), Math.cos(sunAz) * Math.cos(el)).multiplyScalar(ext * 2.5));
      hemi.intensity = M.hemi; scene.environmentIntensity = M.env; renderer.toneMappingExposure = M.exp;
      for (const l of apt.lights) { l.userData.base ??= l.intensity; l.intensity = mood.name === 'golden' ? l.userData.base * 0.25 : 0; }
    }
    placeWindowLights(winRoom, true);
  }
  function aimSun() {   // walk: the light comes in through the biggest window of the room you are in (the sky keeps the real sun)
    const M = MOODS[mood.name], w = windowsOf(winRoom)[0]; if (!w) return;
    const out = new THREE.Vector2(-w.n.x, -w.n.y).rotateAround(new THREE.Vector2(), THREE.MathUtils.degToRad(mood.name === 'golden' ? 28 : 18));
    const el = THREE.MathUtils.degToRad(M.wElev), dir = new THREE.Vector3(out.x * Math.cos(el), Math.sin(el), out.y * Math.cos(el)).normalize();
    sun.target.position.copy(w.pos).setY(0); sun.position.copy(sun.target.position).addScaledVector(dir, ext * 2.5); sun.color.setHex(M.wSun); sun.intensity = M.wSunI; sun.visible = true;
    hemi.intensity = M.wHemi; scene.environmentIntensity = M.wEnv; renderer.toneMappingExposure = M.wExp;
  }
  function fromOutside(s) { if (mood.mode === 'walk') aimSun(); }   // outside.js re-lit for the hour: put the room's light back
  function setMode(m) { mood.mode = m; if (m !== 'doll') scene.background = null; resize(); apply(); }
  function render(dt) { grade.uniforms.uTime.value += dt; composer.render(dt); }

  return { setMood, setMode, render, resize, dress, budgetLights, applyStyle, placeWindowLights, fromOutside, get mood() { return mood.name; }, composer, pool, gtao, bloom, grade, MOODS };
}
