// polishcam.js: place the walk camera from URL parameters, for photo-matched renders (app/plan3d/polish/).
//   ?cam=x,y,z,yaw,pitch,hfov   metres; yaw in degrees in the walk convention (0 looks +z/south, 90 +x/east, 180 north),
//                               pitch degrees (+ looks up), hfov = HORIZONTAL field of view in degrees (vertical is derived
//                               from the window aspect). Also &room=<rid> to pick the furnished room panel (optional).
//   &hideui=1   hides every panel/HUD and the furniture editing overlays (labels, footprints, front markers)
//   &depth=1    renders a LINEAR depth pass instead of the shaded image: grey = 1 - (z - near)/(far - near) (z = camera-space
//               distance along the view axis, near white, beyond far black); &dnear= (default 0.3 m) &dfar= (default 10 m).
//               Use with &quality=low (no post-processing).
// Does nothing without ?cam=. Exposes window.polishcam {status(), pose}. Touches the page only through window.apartment,
// window.setWalk and window.walk (manual mode, so walk.js stops moving the player).
import * as THREE from 'three';
const Q = new URLSearchParams(location.search);
if (Q.has('cam')) {
  const until = (f) => new Promise(res => { const t = () => (f() ? res() : setTimeout(t, 80)); t(); });
  await until(() => window.apartment && window.apartment.apt && window.setWalk && window.walk);
  const { scene, camera, renderer, apt } = window.apartment;
  const [x, y, z, yaw, pitch, hfov] = Q.get('cam').split(',').map(Number);
  const hide = Q.get('hideui') === '1', depth = Q.get('depth') === '1';
  if (hide) { const st = document.createElement('style'); st.textContent = 'body > *:not(canvas){display:none !important}'; document.head.appendChild(st); }
  let room = Q.get('room'); if (!room) { let bd = Infinity; for (const [id, r] of Object.entries(apt.roomMeshes)) { const d = Math.hypot(r.center.x - x, r.center.z - z); if (d < bd) { bd = d; room = id; } } }
  window.setWalk(room); window.walk.manual = true;
  const pose = { x, y, z, yaw, pitch, hfov };
  function apply() {
    const a = THREE.MathUtils.degToRad(yaw), p = THREE.MathUtils.degToRad(pitch);
    camera.position.set(x, y, z); camera.up.set(0, 1, 0); camera.rotation.set(0, 0, 0);
    camera.lookAt(x + Math.sin(a) * Math.cos(p), y + Math.sin(p), z + Math.cos(a) * Math.cos(p));
    const vf = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(hfov) / 2) / camera.aspect);
    const vfd = THREE.MathUtils.radToDeg(vf); if (Math.abs(camera.fov - vfd) > 1e-4) { camera.fov = vfd; camera.updateProjectionMatrix(); }
  }
  function overlays() {   // furniture editing aids and labels are not part of the scene a photographer would see
    scene.traverse(o => {
      if (o.isSprite || o.isLine) o.visible = false;
      else if (o.isMesh && o.material && o.material.isMeshBasicMaterial && o.material.color && o.material.color.getHex() === 0x9fe3c0) o.visible = false;
    });
  }
  const near = +(Q.get('dnear') || 0.3), far = +(Q.get('dfar') || 10);
  const depthMat = new THREE.ShaderMaterial({
    uniforms: { uNear: { value: near }, uFar: { value: far } },
    vertexShader: 'varying float vZ; void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); vZ = -mv.z; gl_Position = projectionMatrix * mv; }',
    fragmentShader: 'uniform float uNear; uniform float uFar; varying float vZ; void main(){ float d = clamp(1.0 - (vZ - uNear) / (uFar - uNear), 0.0, 1.0); gl_FragColor = vec4(vec3(d), 1.0); }',
    side: THREE.DoubleSide,
  });
  let frames = 0;
  const orig = renderer.render.bind(renderer);
  renderer.render = (s, c) => {
    if (c === camera) { apply(); if (hide || depth) overlays(); }
    if (depth && s === scene) {
      const bg = s.background, ov = s.overrideMaterial, tm = renderer.toneMapping;
      s.background = null; s.overrideMaterial = depthMat; renderer.toneMapping = THREE.NoToneMapping; renderer.setClearColor(0x000000, 1);
      orig(s, c); s.background = bg; s.overrideMaterial = ov; renderer.toneMapping = tm;
    } else orig(s, c);
    frames++;
  };
  if (depth) { renderer.shadowMap.enabled = false; }
  const items = () => { let n = 0; scene.traverse(o => { if (o.isMesh && o.userData && o.userData.item) n++; }); return n; };
  window.polishcam = { pose, status: () => ({ frames, itemMeshes: items(), room, fov: camera.fov, aspect: camera.aspect }) };
}
