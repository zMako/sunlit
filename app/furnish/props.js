// Props kit: lived-in decor on top of a furniture plan. Props are never plan items: no fit check, no walking path, no cart, no selection.
// Textiles (bedding, cushions, throws, curtains) are procedural so they fit each piece and take the room's colours; small objects are
// CC0 Poly Haven photoscans (props/props.json); wall art is public-domain paintings from the Art Institute of Chicago (art/art.json),
// chosen by the room palette. Heights come from the furniture model itself: rays straight down find the mattress, the seat, the arms,
// the tabletop and every shelf, so a pillow lands on the mattress whatever the catalogue box says.
import * as THREE from 'three';

const DEG = Math.PI / 180;
export const propsOn = () => localStorage.getItem('props') !== '0';

// ---------- seeded randomness: the same room dresses the same way on every load ----------
function rngFor(str) {
  let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return () => { h += 0x6D2B79F5; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const jit = (r, a) => (r() * 2 - 1) * a;
const pick = (r, a) => a[Math.floor(r() * a.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// ---------- room palette: hex from the agent when it gave them, else colour words from the brief ----------
const WORDS = Object.entries({
  oatmeal: '#d8ccb4', linen: '#e4dccb', cream: '#efe8da', ivory: '#f1ece0', 'off-white': '#eeebe4', white: '#f1efea', sand: '#d6c4a3', beige: '#d9ccb5', taupe: '#a89a8a',
  greige: '#b8b0a4', stone: '#bdb6aa', mushroom: '#b3a594', oak: '#c49a6c', walnut: '#6b4a33', teak: '#9a6a3e', grey: '#9a9a98', gray: '#9a9a98', charcoal: '#3a3b3d', black: '#262626',
  ochre: '#c58b2b', mustard: '#c9a03a', saffron: '#d39b2f', terracotta: '#b5603f', rust: '#a4522f', clay: '#b9775a', blush: '#dcb3a8', pink: '#d9a6a6', rose: '#c98b8b',
  sage: '#9caa8c', olive: '#7a7d4a', green: '#5f7a5c', forest: '#3f5a45', moss: '#6f7a4a', eucalyptus: '#8fa596', navy: '#2f3e57', blue: '#5a7394', denim: '#5d7591',
  teal: '#3e7470', sky: '#a8c0d6', lavender: '#b3a9c9', burgundy: '#6e2f36', plum: '#6a4a5e', cognac: '#9a5b2e', caramel: '#b07a45', honey: '#c99a52', brass: '#b8954a',
  gold: '#c4a24c', coral: '#d9826b', peach: '#e6b89c', yellow: '#d8b74a', red: '#a8453b', brown: '#6f4e37', chocolate: '#4e342e', slate: '#6b7480', indigo: '#3d4a6b', cognac_: '#9a5b2e',
});
const isHex = h => typeof h === 'string' && /^#?[0-9a-f]{6}$/i.test(h.trim());
const col = h => new THREE.Color(h.trim().startsWith('#') ? h.trim() : '#' + h.trim());
const SRGB = THREE.SRGBColorSpace; const L = c => c.getHSL({}, SRGB).l, S = c => c.getHSL({}, SRGB).s;   // perceptual (sRGB) lightness, not linear
function wordColours(text) {
  const t = (text || '').toLowerCase(); const found = [];
  for (const [w, hex] of WORDS) { const i = t.search(new RegExp('\\b' + w.replace('_', '') + '\\b')); if (i >= 0) found.push([i, hex, w]); }
  return found.sort((a, b) => a[0] - b[0]);
}
export function roomPalette(plan = {}, meta = {}) {
  const brief = [plan.palette, plan.style, plan.notes].filter(Boolean).join(' . ');
  const words = wordColours(brief); const hexes = (plan.palette_hex || []).filter(isHex).map(col);
  const cols = hexes.length ? hexes : words.filter(w => !['oak', 'walnut', 'teak'].includes(w[2])).map(w => col(w[1]));
  let accent = isHex(plan.accent_hex) ? col(plan.accent_hex) : null;
  if (!accent) { const m = brief.toLowerCase().match(/([a-z-]+)\s+(?:and\s+[a-z-]+\s+)?accents?/) || (plan.accent || '').toLowerCase().match(/[a-z-]+/); const hx = m && WORDS.find(([w]) => w === (m[1] || m[0])); if (hx) accent = col(hx[1]); }
  if (!accent && plan.accent) { const w = wordColours(plan.accent)[0]; if (w) accent = col(w[1]); }
  if (!accent) { const ch = cols.filter(c => S(c) > 0.3 && L(c) > 0.2 && L(c) < 0.8).sort((a, b) => S(b) - S(a))[0]; if (ch) accent = ch.clone(); }
  const wood = isHex(plan.wood_hex) ? col(plan.wood_hex) : col((wordColours([plan.wood, brief].join(' ')).find(w => ['oak', 'walnut', 'teak', 'honey', 'caramel'].includes(w[2])) || [0, '#b48a5e'])[1]);
  const byL = cols.slice().sort((a, b) => L(b) - L(a));
  const light = (byL.find(c => L(c) > 0.72) || col('#ebe5d9')).clone();
  const mid = (byL.find(c => L(c) > 0.35 && L(c) < 0.75) || light.clone().lerp(col('#a89a8a'), 0.45)).clone();
  const dark = (byL.slice().reverse().find(c => L(c) < 0.4) || mid.clone().multiplyScalar(0.55)).clone();
  return { light, mid, dark, accent, accentExplicit: !!accent, wood, cols };
}
// sRGB -> CIE Lab, for matching art to the room
function lab(c) {
  const f = v => (v > 0.04045 ? ((v + 0.055) / 1.055) ** 2.4 : v / 12.92); const r = f(c.r), g = f(c.g), b = f(c.b);   // THREE.Color is linear when ColorManagement is on: undo below
  let X = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047, Y = r * 0.2126 + g * 0.7152 + b * 0.0722, Z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883;
  const h = t => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116); X = h(X); Y = h(Y); Z = h(Z); return [116 * Y - 16, 500 * (X - Y), 200 * (Y - Z)];
}
const labHex = hex => { const c = new THREE.Color(); c.setStyle(hex); const s = c.clone().convertLinearToSRGB(); return lab(s); };
const labCol = c => lab(c.clone().convertLinearToSRGB());
const dLab = (a, b) => Math.hypot(a[0] - b[0], 1.4 * (a[1] - b[1]), 1.4 * (a[2] - b[2]));   // chroma counts more than lightness: a painting is a colour statement

// ---------- data ----------
let DATA = null;
export function propData() {
  return DATA ||= Promise.all(['/furnish/props/props.json', '/furnish/art/art.json'].map(u => fetch(u).then(r => (r.ok ? r.json() : { items: [] })).catch(() => ({ items: [] }))))
    .then(([p, a]) => ({ props: p.items || [], art: a.items || [] }));
}
const GLB = new Map();
function loadGlb(loader, e) {   // one load per page; re-based so the object stands centred on its own origin
  if (!GLB.has(e.id)) GLB.set(e.id, loader.loadAsync('/' + e.file).then(g => {
    const s = g.scene; const bb = new THREE.Box3().setFromObject(s); const c = bb.getCenter(new THREE.Vector3()); s.position.set(-c.x, -bb.min.y, -c.z);
    const root = new THREE.Group(); root.add(s); const sz = bb.getSize(new THREE.Vector3()); root.userData.size = [sz.x, sz.z, sz.y]; return root;
  }).catch(() => null));
  return GLB.get(e.id);
}
function proto(f, e) {   // per room: own material copies (clip planes and highlights are per room)
  f._protos ||= new Map();
  if (!f._protos.has(e.id)) f._protos.set(e.id, loadGlb(f.loader, e).then(root => { if (!root) return null; const p = root.clone(true); p.userData.size = root.userData.size; p.traverse(o => { if (o.isMesh) { o.material = o.material.clone(); o.castShadow = true; o.receiveShadow = true; } }); return p; }));
  return f._protos.get(e.id);
}
const TEX = new Map();
function texture(url, srgb = true, repeat = 1) {
  if (!TEX.has(url)) { const t = new THREE.TextureLoader().load(url); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat); t.anisotropy = 4; TEX.set(url, t); }
  return TEX.get(url);
}
function fabric(f, c, o = {}) {   // matte woven textile with the CC0 weave normal map; cached per room and colour
  f._fabrics ||= new Map(); const key = c.getHexString() + JSON.stringify(o);
  if (!f._fabrics.has(key)) {
    const m = new THREE.MeshPhysicalMaterial({ color: c.clone(), roughness: o.rough ?? 0.93, metalness: 0, sheen: o.sheen ?? 0.45, sheenRoughness: 0.75, sheenColor: c.clone().lerp(new THREE.Color(0xffffff), 0.45),
      side: o.side ?? THREE.FrontSide, transparent: !!o.opacity, opacity: o.opacity ?? 1, depthWrite: !o.opacity });
    m.normalMap = texture(`/furnish/materials/${o.boucle ? 'Fabric022' : 'Fabric019'}/normal.jpg`, false); m.normalScale.set(o.bump ?? 0.5, o.bump ?? 0.5);
    f._fabrics.set(key, m);
  }
  return f._fabrics.get(key);
}
const mute = (c, s = 0.8, l = 0) => { const h = c.getHSL({}, SRGB); return new THREE.Color().setHSL(h.h, h.s * s, clamp(h.l + l, 0.04, 0.96), SRGB); };
function mark(o) { o.traverse(m => { m.userData.prop = true; if (m.isMesh) m.raycast = () => {}; }); return o; }

// ---------- reading the furniture model ----------
class Probe {
  constructor(it) {
    this.it = it; this.targets = []; (it.model || new THREE.Group()).traverse(o => { if (o.isMesh) this.targets.push(o); }); if (it.mattress) this.targets.push(it.mattress);
    this.ray = new THREE.Raycaster(); it.obj.updateWorldMatrix(true, true); this.cache = new Map();
  }
  _cast(o, d, far) {   // item-local origin and direction
    const ob = this.it.obj; const a = ob.localToWorld(o.clone()); const b = ob.localToWorld(o.clone().add(d)); this.ray.set(a, b.sub(a).normalize()); this.ray.far = far;
    return this.ray.intersectObjects(this.targets, false).map(h => ob.worldToLocal(h.point.clone()));
  }
  down(x, z) {   // every surface under (x, z), top first; the two faces of a thin board merge into one
    const k = `${x.toFixed(3)},${z.toFixed(3)}`; if (this.cache.has(k)) return this.cache.get(k);
    const ys = this._cast(new THREE.Vector3(x, 4, z), new THREE.Vector3(0, -1, 0), 5).map(p => p.y); const out = [];
    for (const y of ys) if (!out.length || out[out.length - 1] - y > 0.03) out.push(y);
    this.cache.set(k, out); return out;
  }
  top(x, z) { const d = this.down(x, z); return d.length ? d[0] : null; }
  up(x, y, z) { const h = this._cast(new THREE.Vector3(x, y, z), new THREE.Vector3(0, 1, 0), 3); return h.length ? h[0].y - y : Infinity; }
  side(y, z, s) { const h = this._cast(new THREE.Vector3(0, y, z), new THREE.Vector3(s, 0, 0), 3); return h.length ? h[0].x : null; }
}

// ---------- procedural textiles ----------
function pillowGeo(w, t, d, flat = 0.55) {   // superquadric: boxy in plan, rounded in section, thinner towards the seams
  const g = new THREE.SphereGeometry(1, 40, 24); const p = g.attributes.position; const sp = (v, e) => Math.sign(v) * Math.abs(v) ** e;
  for (let i = 0; i < p.count; i++) {
    const x = sp(p.getX(i), 0.3) * w / 2, z = sp(p.getZ(i), 0.3) * d / 2; let y = sp(p.getY(i), 0.85) * t / 2;
    const nx = Math.abs(x) / (w / 2), nz = Math.abs(z) / (d / 2); y *= (1 - flat * nx ** 3) * (1 - flat * nz ** 3); p.setXYZ(i, x, y, z);
  }
  g.computeVertexNormals(); return g;
}
// cloth lying on [x0,x1]x[z0,z1] at height hf(x,z) and falling over the chosen edges (l, r = -x/+x, b, f = -z/+z), pooling at the floor
function drapeGeo(x0, x1, z0, z1, drops, hf, r, rad = 0.05, floorY = 0.015, seg = 0.035) {
  const X0 = x0 - (drops.l || 0), X1 = x1 + (drops.r || 0), Z0 = z0 - (drops.b || 0), Z1 = z1 + (drops.f || 0);
  const nx = Math.max(2, Math.round((X1 - X0) / seg)), nz = Math.max(2, Math.round((Z1 - Z0) / seg)); const ph = r() * 6.28, ph2 = r() * 6.28;
  const pos = [], uv = [], idx = []; const arc = rad * Math.PI / 2;
  for (let j = 0; j <= nz; j++) for (let i = 0; i <= nx; i++) {
    const x = X0 + (X1 - X0) * i / nx, z = Z0 + (Z1 - Z0) * j / nz; const ex = clamp(x, x0, x1), ez = clamp(z, z0, z1); const dx = x - ex, dz = z - ez; const s = Math.hypot(dx, dz);
    let px = ex, pz = ez, py = hf(ex, ez);
    if (s > 1e-6) {
      const ux = dx / s, uz = dz / s;
      if (s <= arc) { const a = s / rad; px += ux * rad * Math.sin(a); pz += uz * rad * Math.sin(a); py -= rad * (1 - Math.cos(a)); }
      else { const hang = s - arc; const along = Math.abs(ux) > Math.abs(uz) ? z : x; const wave = 0.014 * Math.sin(along * 17 + ph) * Math.min(1, hang / 0.12) + 0.006 * Math.sin(along * 41 + ph2);   // folds in the hanging part
        px += ux * (rad + wave); pz += uz * (rad + wave); py -= rad + hang; }
      if (py < floorY) { const extra = floorY - py; py = floorY; px += ux * extra * 0.5; pz += uz * extra * 0.5; }
    }
    pos.push(px, py, pz); uv.push(x * 3, z * 3);
  }
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) { const a = j * (nx + 1) + i; idx.push(a, a + nx + 1, a + 1, a + 1, a + nx + 1, a + nx + 2); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); g.setIndex(idx); g.computeVertexNormals(); return g;
}
function mesh(geo, mat, shadow = true) { const m = new THREE.Mesh(geo, mat); m.castShadow = shadow; m.receiveShadow = true; return m; }

// ---------- books ----------
const BOOKMAT = new Map();
function bookMats(f, c) {   // cover/spine colour on five faces, cream page block on the opening side
  const key = (f.room || '') + c.getHexString(); if (BOOKMAT.has(key)) return BOOKMAT.get(key);
  const cover = new THREE.MeshStandardMaterial({ color: c, roughness: 0.75 }); const pages = new THREE.MeshStandardMaterial({ color: 0xeee6d4, roughness: 0.9 });
  const m = { flat: [pages, cover, cover, cover, pages, pages], standing: [cover, cover, pages, pages, cover, pages] };   // box faces: +x -x +y -y +z -z
  BOOKMAT.set(key, m); return m;
}
function spineColours(pal, r) {
  const base = [mute(pal.mid, 0.7, -0.12), mute(pal.dark, 0.8, 0.05), col('#e9e2d3'), col('#2f3a48'), mute(pal.wood, 0.7, -0.05), col('#7a2f2a').lerp(pal.mid, 0.3), col('#47614f').lerp(pal.mid, 0.3)];
  if (pal.accent) base.push(mute(pal.accent, 0.75), mute(pal.accent, 0.6, 0.12));
  const out = []; for (let i = 0; i < 3; i++) out.push(pick(r, base)); return out;
}
function bookStack(f, pal, r, n, maxW = 0.32, maxD = 0.24) {
  const g = new THREE.Group(); let y = 0; const cs = spineColours(pal, r);
  for (let i = 0; i < n; i++) {
    const w = clamp(0.19 + r() * 0.12, Math.min(0.14, maxW), maxW), d = Math.min(maxD, 0.15 + r() * 0.09), t = 0.018 + r() * 0.022;
    const b = mesh(new THREE.BoxGeometry(w, t, d), bookMats(f, cs[i % cs.length]).flat); b.position.set(jit(r, 0.015), y + t / 2, jit(r, 0.015)); b.rotation.y = jit(r, 0.18); y += t; g.add(b);
  }
  g.userData.h = y; return g;
}

// ---------- the kit ----------
export class Props {
  // rebuild everything for a room (after a plan loads); cheap to call again
  static async build(f) {
    Props.clear(f); if (!f.room || !f.meta || !propsOn()) return;
    const token = (f._propToken = (f._propToken || 0) + 1);
    const data = await propData(); if (token !== f._propToken) return;
    f._pal = roomPalette(f.plan || {}, f.meta); f._propUsed = new Set();
    // wall art first: its strongest colour becomes the room accent when the brief named none
    f._artPick = Props._chooseArt(f, data.art, rngFor(f.room + ':art'));
    if (!f._pal.accentExplicit && f._artPick[0]) { const ac = (f._artPick[0].palette || []).map(p => col(p.hex)).filter(c => S(c) > 0.25 && L(c) > 0.18 && L(c) < 0.8).sort((a, b) => S(b) - S(a))[0]; if (ac) f._pal.accent = mute(ac, 0.85); }
    if (!f._pal.accent) f._pal.accent = col('#a8664a');
    f._propData = data; f._artIdx = -1;
    const room = new THREE.Group(); room.name = 'props:room'; room.userData.prop = true; f._roomProps = room; f.group.add(room);
    Props._curtains(f, room);
    for (const it of f.items) await Props.forItem(f, it, token);
    f._applyClip(room); Props.setVisible(propsOn());
  }
  static clear(f) {
    if (f._roomProps) { f.group.remove(f._roomProps); f._roomProps = null; }
    for (const it of f.items || []) if (it.props) { it.obj.remove(it.props); it.props = null; }
    if (f._artPick) for (const a of f._artPick) Props.USED_ART.delete(a.id);
    f._artPick = null;
  }
  static setVisible(on) { for (const f of window.furnishInstances || []) { if (f._roomProps) f._roomProps.visible = on; for (const it of f.items || []) if (it.props) it.props.visible = on; } }
  static async toggle(on) { localStorage.setItem('props', on ? '1' : '0'); for (const f of window.furnishInstances || []) { if (on && !f._roomProps) await Props.build(f); } Props.setVisible(on); }

  static async forItem(f, it, token = f._propToken) {
    if (!f._pal || it.modelFailed || !it.model || !propsOn()) return;
    if (it.props) { it.obj.remove(it.props); it.props = null; }
    const g = new THREE.Group(); g.name = 'props'; g.userData.prop = true; it.props = g; it.obj.add(g);
    const r = rngFor(f.room + ':' + (it.spec.id || '') + ':' + Math.round((+it.spec.x || 0) * 100) + ':' + Math.round((+it.spec.z || 0) * 100)); const P = new Probe(it); const cat = it.spec.category;
    try {
      if (cat === 'bed') Props._bed(f, it, P, g, r);
      else if (cat === 'sofa' || cat === 'armchair') Props._seat(f, it, P, g, r, cat === 'sofa');
      else if (cat === 'bookcase') await Props._shelves(f, it, P, g, r);
      else if (['coffee_table', 'side_table', 'nightstand', 'dining_table', 'dresser', 'tv_bench', 'desk'].includes(cat)) await Props._surface(f, it, P, g, r, cat);
      else if (cat === 'wardrobe') await Props._wardrobeTop(f, it, P, g, r);
      if ((cat === 'bed' || cat === 'sofa') && f._artPick) await Props._art(f, it, P, g, r);
    } catch (e) { console.warn('[props]', it.spec.id, e); }
    if (token !== f._propToken) { it.obj.remove(g); return; }
    mark(g); f._applyClip(g); g.visible = propsOn();
  }

  // ---------- bed: duvet with a turned-back fold, pillows, cushions, a throw across the foot ----------
  static _bed(f, it, P, g, r) {
    const w = +it.spec.w_m, d = +it.spec.d_m, pal = f._pal; const zc = d * 0.12;
    const top = Math.max(...[0, -0.2, 0.2].map(x => P.top(x * w, zc) ?? -1)); if (top < 0.15 || top > 0.95) return;
    const near = (x, z) => { const y = P.top(x, z); return y != null && Math.abs(y - top) < 0.07; };
    let xl = -w / 2 + 0.03, xr = w / 2 - 0.03, zh = -d / 2 + 0.03, zf = d / 2 - 0.03;
    for (let x = -w / 2 + 0.01; x < 0; x += 0.02) if (near(x, zc)) { xl = x; break; }
    for (let x = w / 2 - 0.01; x > 0; x -= 0.02) if (near(x, zc)) { xr = x; break; }
    for (let z = -d / 2 + 0.01; z < 0; z += 0.02) if (near(0, z)) { zh = z; break; }
    for (let z = d / 2 - 0.01; z > 0; z -= 0.02) if (near(0, z)) { zf = z; break; }
    it._sleepTop = top + 0.045;   // walk.js stands (and bounces) on the duvet
    const W = xr - xl, headboard = Math.max(P.top(0, -d / 2 + 0.03) ?? 0, P.top(0, zh - 0.04) ?? 0) > top + 0.12;
    const loft = 0.035 + r() * 0.015; const a1 = r() * 6, a2 = r() * 6;
    const hf = (x, z) => top + 0.018 + loft * Math.sin(Math.PI * clamp((x - xl) / W, 0, 1)) ** 0.45 + 0.006 * Math.sin(x * 9 + a1) * Math.sin(z * 7 + a2);
    const drop = clamp(top - 0.06, 0.12, 0.34);
    const duvetC = pal.light.clone().lerp(col('#f4f1ea'), 0.35); const zd0 = zh + clamp((zf - zh) * 0.3, 0.5, 0.66);
    g.add(mesh(drapeGeo(xl, xr, zd0, zf, { l: drop, r: drop, f: drop, b: 0.03 }, hf, r), fabric(f, duvetC, { side: THREE.DoubleSide, bump: 0.35 })));
    // the top edge turned back: a lighter band, thickest at the fold, tucked down onto the duvet at its lower edge (no floating edge, no shadow line)
    const b0 = zd0 - 0.02, b1 = zd0 + 0.26;
    g.add(mesh(drapeGeo(xl + 0.01, xr - 0.01, b0, b1, { l: 0.05, r: 0.05, f: 0.02, b: 0.02 }, (x, z) => hf(x, z) + 0.004 + 0.012 * (1 - clamp((z - b0) / (b1 - b0), 0, 1)), r, 0.012), fabric(f, col('#f5f2ec'), { side: THREE.DoubleSide, bump: 0.3 }), false));
    // sleeping pillows against the head, decorative cushions in front on wide beds
    const nP = W >= 1.25 ? 2 : 1; const pw = Math.min(0.66, (W - 0.1) / nP - 0.04); const pd = 0.44; const tilt = headboard ? 22 + r() * 10 : 7;
    for (let i = 0; i < nP; i++) {
      const x = xl + W * (i + 0.5) / nP; const p = mesh(pillowGeo(pw, 0.17, pd), fabric(f, col('#f6f3ee'), { bump: 0.3 }));
      p.rotation.set(tilt * DEG, jit(r, 4 * DEG), jit(r, 3 * DEG)); p.position.set(x + jit(r, 0.02), top + 0.075 + Math.sin(tilt * DEG) * pd * 0.32, zh + pd / 2 * Math.cos(tilt * DEG) + 0.02); g.add(p);
    }
    if (W >= 1.35) {
      const cs = [pal.accent, mute(pal.mid, 0.9, 0.05)]; const n = W >= 1.55 ? 2 : 1;
      for (let i = 0; i < n; i++) { const x = n === 1 ? (xl + xr) / 2 : xl + W * (0.33 + 0.34 * i); const c = mesh(pillowGeo(0.44, 0.15, 0.44, 0.6), fabric(f, mute(cs[i % 2], 0.85), { bump: 0.6 }));
        c.rotation.set((70 + r() * 10) * DEG, jit(r, 9 * DEG), jit(r, 5 * DEG)); c.position.set(x + jit(r, 0.03), top + 0.27, zh + pd + 0.04); g.add(c); }
    }
    // a throw across the foot, falling over the sides and the foot end
    const tc = mute(pal.accent, 0.7, 0.04); const z0 = zf - 0.42 - r() * 0.1;
    g.add(mesh(drapeGeo(xl - 0.005, xr + 0.005, z0, zf, { l: drop * 0.7, r: drop * 0.7, f: drop * 0.75 }, (x, z) => hf(x, z) + 0.016, r, 0.066), fabric(f, tc, { side: THREE.DoubleSide, bump: 0.8, boucle: r() < 0.4 })));
  }

  // ---------- sofa and armchair: cushions leaning on the back, a throw over one arm ----------
  static _seat(f, it, P, g, r, sofa) {
    const w = +it.spec.w_m, d = +it.spec.d_m, pal = f._pal;
    const hz = z => Math.max(...[0, 0.15, -0.15].map(k => P.top(k * w, z) ?? -1));
    const seat = hz(d * 0.22); it._propDbg = { seat, profZ: [-0.48, -0.4, -0.3, -0.15, 0, 0.15, 0.3, 0.48].map(k => +hz(k * d).toFixed(2)), profX: [-0.48, -0.4, -0.3, 0, 0.3, 0.4, 0.48].map(k => +(P.top(k * w, 0) ?? -1).toFixed(2)) }; if (seat < 0.22 || seat > 0.7) return;
    // the back: its highest point in the rear half, then forward until the seat (upholstery is rounded, so the very edge reads low)
    let backTop = -1, zPeak = -d / 2; for (let z = -d / 2 + 0.01; z < 0; z += 0.02) { const y = hz(z); if (y > backTop) { backTop = y; zPeak = z; } }
    let zb = null; for (let z = zPeak; z < d / 2; z += 0.02) if (hz(z) < seat + 0.06 && hz(z) > seat - 0.12) { zb = z; break; }
    it._backTop = backTop > seat + 0.1 ? backTop : seat + 0.35;
    Object.assign(it._propDbg, { zb, backTop });   // what the probes found (debugging aid, read from the console)
    if (zb == null || backTop < seat + 0.12) return;   // backless bench or daybed: nothing leans
    const zm = (zb + d / 2) / 2; const armAt = x => P.top(x, zm) ?? -1;
    const arm = side => { let top = -1, xp = side * (w / 2 - 0.01); for (let x = side * (w / 2 - 0.01); side * x > w / 4; x -= side * 0.02) { const y = armAt(x); if (y > top) { top = y; xp = x; } }
      if (top < seat + 0.1) return side * (w / 2 - 0.03);   // armless side
      for (let x = xp; side * x > 0; x -= side * 0.02) if (armAt(x) < seat + 0.06) return x; return side * (w / 2 - 0.03); };
    const xl = arm(-1), xr = arm(1);
    const span = xr - xl; const s = sofa ? 0.46 : 0.42;
    const cols = [pal.accent, mute(pal.mid, 0.9, 0.08), pal.light.clone().lerp(col('#f2eee6'), 0.3), mute(pal.dark, 0.8, 0.1)];
    const place = (x, c, size, lean) => { const m = mesh(pillowGeo(size, 0.15, size, 0.6), fabric(f, mute(c, 0.85), { bump: 0.65, boucle: r() < 0.3 }));
      m.rotation.set((90 - lean) * DEG, jit(r, 8 * DEG), jit(r, 6 * DEG)); m.position.set(x, seat + size / 2 * Math.sin((90 - lean) * DEG) + 0.02, zb + 0.09 + size / 2 * Math.cos((90 - lean) * DEG)); g.add(m); };
    if (!sofa) { if (span > 0.35) place((xl + xr) / 2 + jit(r, 0.03), cols[0], Math.min(s, span - 0.05), 14 + r() * 6); return; }
    if (span < 0.8) { place((xl + xr) / 2, cols[0], s, 15); return; }
    place(xl + s / 2 + 0.03, cols[2], s, 13 + r() * 5); place(xl + s / 2 + 0.2, cols[0], s * 0.85, 22 + r() * 6);   // a pair in one corner: a big light one behind, the accent in front
    place(xr - s / 2 - 0.03, cols[2], s, 13 + r() * 5); if (span >= 1.9) place(xr - s / 2 - 0.2, cols[1], s * 0.85, 22 + r() * 6);
    // throw folded over one arm
    const left = r() < 0.5; const armX = left ? xl : xr; const outer = left ? -w / 2 : w / 2;
    const armTop = P.top((armX + outer) / 2, zm) ?? seat;
    if (Math.abs(outer - armX) > 0.06 && armTop > seat + 0.08 && r() < 0.75) {
      const xa = Math.min(armX, outer) - 0.005, xb = Math.max(armX, outer) + 0.005; const za = zb + 0.05 + r() * 0.1, zz = za + 0.5;
      const hf = (x, z) => (P.top(clamp(x, xa + 0.01, xb - 0.01), z) ?? armTop) + 0.012;
      g.add(mesh(drapeGeo(xa, xb, za, zz, left ? { l: Math.min(0.4, armTop - 0.05), r: armTop - seat - 0.02 } : { r: Math.min(0.4, armTop - 0.05), l: armTop - seat - 0.02 }, hf, r, 0.045),
        fabric(f, mute(pal.accent, 0.6, 0.12), { side: THREE.DoubleSide, bump: 0.9, boucle: true })));
    }
  }

  // ---------- small objects ----------
  static _entry(f, roles, r, lim = {}) {
    const { maxW = 9, maxD = 9, maxH = 9, minH = 0 } = lim; const used = f._propUsed;
    const c = f._propData.props.filter(e => roles.includes(e.role) && !used.has(e.id) && e.dims_m[0] <= maxW && e.dims_m[1] <= maxD && e.dims_m[2] <= maxH && e.dims_m[2] >= minH);
    const e = c.length ? pick(r, c) : null; if (e && e.role !== 'fruit') used.add(e.id); return e;
  }
  static async _put(f, g, e, x, y, z, yaw) { const p = await proto(f, e); if (!p) return null; const o = p.clone(true); o.position.set(x, y, z); o.rotation.y = yaw + (Props.FACING[e.id] || 0); g.add(o); return o; }
  static async _fruitBowl(f, g, r, x, y, z, maxW) {
    const bowl = Props._entry(f, ['bowl'], r, { maxW, maxH: 0.12, minH: 0.06 }); if (!bowl) return;
    await Props._put(f, g, bowl, x, y, z, r() * 6.28); const n = 3 + Math.floor(r() * 3); const R = bowl.dims_m[0] * 0.2;
    const kind = Props._entry(f, ['fruit'], r);
    for (let i = 0; i < n && kind; i++) { const a = i / n * 6.28 + r(); await Props._put(f, g, kind, x + Math.cos(a) * R * (i ? 1 : 0), y + bowl.dims_m[2] * 0.35 + (i ? 0 : 0.03), z + Math.sin(a) * R * (i ? 1 : 0), r() * 6.28); }
  }
  // tables, nightstands, dressers: real objects where the top really is, clear of lamps standing on it
  static async _surface(f, it, P, g, r, cat) {
    const w = +it.spec.w_m, d = +it.spec.d_m, pal = f._pal;
    const top = Math.max(...[[0, 0], [0.2, 0], [-0.2, 0], [0, 0.2]].map(([a, b]) => P.top(a * w, b * d) ?? -1)); if (top < 0.25) return;
    const flat = (x, z, rr) => [[0, 0], [rr, 0], [-rr, 0], [0, rr], [0, -rr]].every(([a, b]) => { const y = P.top(x + a, z + b); return y != null && Math.abs(y - top) < 0.015; });
    const occ = []; const wp = new THREE.Vector3(); it.obj.updateWorldMatrix(true, false);
    for (const o of f.items) { if (o === it) continue; o.obj.getWorldPosition(wp); const lp = it.obj.worldToLocal(wp.clone()); if (Math.abs(lp.x) < w / 2 + 0.05 && Math.abs(lp.z) < d / 2 + 0.05 && Math.abs((+o.spec.y_m || 0) - (+it.spec.y_m || 0) - top) < 0.12) occ.push({ x: lp.x, z: lp.z, r: Math.max(+o.spec.w_m, +o.spec.d_m) / 2 * (/lamp/.test(o.spec.category) ? 0.55 : 1) /* a lamp blocks its base, not its shade */ }); }
    const tight = w < 0.6 || d < 0.42; const edge = tight ? 0.01 : 0.03;   // small tops (nightstands): things sit closer to the edge and to the lamp
    const free = (x, z, rr) => occ.every(o => Math.hypot(x - o.x, z - o.z) > o.r + rr + edge) && flat(x, z, rr);
    it._propDbg = { top, occ: occ.map(o => [+o.x.toFixed(2), +o.z.toFixed(2), +o.r.toFixed(2)]) };
    const ceilGap = ((+f.meta.ceiling_m || 2.6) - (+it.spec.y_m || 0) - top) - 0.3;
    const spot = (fx, fz, rr) => {   // nearest free spot to a preferred point (fractions of the top)
      let best = null; for (let k = 0; k < 40; k++) { const x = clamp(fx * w / 2 + jit(r, w * 0.25) * (k > 0), -w / 2 + rr + edge, w / 2 - rr - edge), z = clamp(fz * d / 2 + jit(r, d * 0.25) * (k > 0), -d / 2 + rr + edge, d / 2 - rr - edge); if (free(x, z, rr)) { best = [x, z]; break; } }
      if (best) occ.push({ x: best[0], z: best[1], r: rr }); return best;
    };
    const obj = async (roles, fx, fz, lim) => { const e = Props._entry(f, roles, r, { ...lim, maxH: Math.min(ceilGap, lim.maxH ?? 9) }); if (!e) return; const rr = Math.max(e.dims_m[0], e.dims_m[1]) / 2; const s = spot(fx, fz, rr); if (!s) { f._propUsed.delete(e.id); return; } await Props._put(f, g, e, s[0], top, s[1], jit(r, 0.6) + (e.role === 'frame' || e.role === 'clock' ? 0 : r() * 6.28)); };
    const books = (fx, fz, n) => { const bw = tight ? 0.17 : Math.min(0.32, w * 0.45); const st = bookStack(f, pal, r, n, bw, tight ? 0.13 : 0.24); const s = spot(fx, fz, tight ? 0.085 : Math.min(0.17, bw * 0.55)); if (!s) return; st.position.set(s[0], top, s[1]); st.rotation.y = jit(r, 0.3); g.add(st); };
    const small = { maxW: Math.min(0.35, w * 0.4), maxD: Math.min(0.35, d * 0.6) };
    if (cat === 'coffee_table') { books(-0.45, jit(r, 0.2), 2 + Math.floor(r() * 2)); if (r() < 0.45 && w > 0.8) await Props._fruitBowlAt(f, g, r, spot, top, 0.4); else await obj(['vessel', 'candle', 'sculpture', 'bowl'], 0.45, 0, { ...small, maxH: 0.42 }); }
    else if (cat === 'side_table') { if (r() < 0.5) await obj(['plant'], 0, 0, { ...small, maxH: 0.35 }); else await obj(['vessel', 'candle', 'sculpture'], 0, 0, { ...small, maxH: 0.45 }); }
    else if (cat === 'nightstand') { books(r() < 0.5 ? -0.5 : 0.5, 0.5, 1 + Math.floor(r() * 2)); await obj(['clock', 'vessel', 'candle', 'plant'], 0.6, -0.4, { ...small, maxH: 0.3 }); }
    else if (cat === 'dining_table') { if (r() < 0.55) await Props._fruitBowlAt(f, g, r, spot, top, 0); else await obj(['vessel', 'candle'], 0, 0, { maxW: 0.3, maxD: 0.3, maxH: 0.5 }); if (w > 1.4 && r() < 0.5) await obj(['candle', 'vessel'], 0.35, 0, { maxW: 0.2, maxD: 0.2, maxH: 0.45 }); }
    else if (cat === 'desk') { books(-0.6, -0.3, 2 + Math.floor(r() * 2)); await obj(['plant', 'vessel', 'clock'], 0.65, -0.4, { ...small, maxH: 0.35 }); }
    else { /* dresser, tv bench: a small composition */ books(-0.55, jit(r, 0.2), 2 + Math.floor(r() * 3)); await obj(['vessel', 'plant'], 0.5, -0.1, { maxW: 0.35, maxD: Math.min(0.35, d * 0.7), maxH: 0.6 }); if (w > 1.0) await obj(['sculpture', 'candle', 'clock', 'bowl'], 0.05, -0.15, { maxW: 0.35, maxD: Math.min(0.3, d * 0.6), maxH: 0.45 }); }
  }
  static async _fruitBowlAt(f, g, r, spot, top, fx) { const s = spot(fx, 0, 0.17); if (s) await Props._fruitBowl(f, g, r, s[0], top, s[1], 0.34); }
  static async _wardrobeTop(f, it, P, g, r) {
    const top = P.top(0, 0); const ceil = +f.meta.ceiling_m || 2.6; if (top == null || ceil - top < 0.3) return;
    const e = Props._entry(f, ['basket'], r, { maxW: +it.spec.w_m * 0.6, maxH: ceil - top - 0.08 }); if (e) await Props._put(f, g, e, jit(r, +it.spec.w_m * 0.2), top, 0, jit(r, 0.3));
  }

  // ---------- bookcase: every shelf the model really has, runs of books with gaps, an object here and there ----------
  static async _shelves(f, it, P, g, r) {
    const w = +it.spec.w_m, d = +it.spec.d_m, pal = f._pal; const zc = Math.min(0.02, d * 0.05); const ceil = +f.meta.ceiling_m || 2.6;
    const surfaces = P.down(0, zc).filter(y => y > 0.03 && y < 2.1);
    const mats = new Map(); const geo = new THREE.BoxGeometry(1, 1, 1); const books = [];
    const cs = spineColours(pal, r).concat(spineColours(pal, r));
    for (const y of surfaces) {
      const clear = Math.min(P.up(0, y + 0.005, zc), ceil - (+it.spec.y_m || 0) - y - 0.1); if (clear < 0.16) continue;
      const lx = P.side(y + 0.06, zc, -1), rx = P.side(y + 0.06, zc, 1); const x0 = (lx ?? -w / 2) + 0.015, x1 = (rx ?? w / 2) - 0.015; if (x1 - x0 < 0.2) continue;
      const hMax = Math.min(clear - 0.025, 0.32); const isTop = clear > 0.6;
      if (isTop) { const e = Props._entry(f, ['vessel', 'plant', 'sculpture'], r, { maxW: (x1 - x0) * 0.4, maxD: d, maxH: Math.min(0.45, clear - 0.1) }); if (e) await Props._put(f, g, e, x0 + (x1 - x0) * (0.25 + r() * 0.5), y, zc, r() * 6.28); continue; }
      let x = x0 + r() * 0.06; let objPlaced = false;
      while (x < x1 - 0.03) {
        const roll = r();
        if (roll < 0.22 && !objPlaced && x1 - x > 0.25) {   // an object in the gap
          const e = Props._entry(f, ['vessel', 'sculpture', 'basket', 'plant', 'clock'], r, { maxW: Math.min(0.3, x1 - x - 0.03), maxD: d - 0.02, maxH: hMax }); if (e) { await Props._put(f, g, e, x + e.dims_m[0] / 2 + 0.02, y, zc + jit(r, 0.02), e.role === 'frame' || e.role === 'clock' ? jit(r, 0.3) : r() * 6.28); x += e.dims_m[0] + 0.06; objPlaced = true; continue; }
        }
        if (roll < 0.34) { x += 0.05 + r() * 0.12; continue; }   // a gap
        const run = 4 + Math.floor(r() * 9); const c2 = [pick(r, cs), pick(r, cs)]; const hBase = hMax * (0.72 + r() * 0.22);
        for (let i = 0; i < run && x < x1 - 0.03; i++) {
          const t = 0.018 + r() * 0.026; const h = Math.min(hMax, hBase * (0.85 + r() * 0.2)); const bd = Math.min(d - 0.04, 0.15 + r() * 0.08); const c = c2[r() < 0.7 ? 0 : 1];
          const m = new THREE.Matrix4().compose(new THREE.Vector3(x + t / 2, y + h / 2, zc), new THREE.Quaternion(), new THREE.Vector3(t, h, bd));
          books.push([m, c]); x += t + (r() < 0.1 ? 0.004 : 0.001);
        }
        if (r() < 0.35 && x < x1 - 0.12) { const t = 0.022, h = hBase * 0.95, lean = (8 + r() * 10) * DEG; const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -lean);   // the last one leaning
          books.push([new THREE.Matrix4().compose(new THREE.Vector3(x + Math.sin(lean) * h / 2 + t / 2, y + Math.cos(lean) * h / 2, zc), q, new THREE.Vector3(t, h, Math.min(d - 0.04, 0.19))), pick(r, cs)]); x += Math.sin(lean) * h + 0.03; }
        x += 0.02 + r() * 0.08;
      }
    }
    if (books.length) {   // one draw call per bookcase
      const im = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({ roughness: 0.78 }), books.length); im.castShadow = true; im.receiveShadow = true;
      books.forEach(([m, c], i) => { im.setMatrixAt(i, m); im.setColorAt(i, c); }); im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true; g.add(im);
    }
  }

  // ---------- wall art above the sofa and the bed, on the wall behind it ----------
  static _chooseArt(f, list, r) {
    if (!list.length) return [];
    const anchors = f.items.filter(it => it.spec.category === 'bed' || it.spec.category === 'sofa'); if (!anchors.length) return [];
    const pal = f._pal; const target = [pal.light, pal.mid, pal.dark, ...(pal.accent ? [pal.accent, pal.accent] : []), ...pal.cols].map(labCol);
    const score = a => (a.palette || []).reduce((s, p) => s + p.share * Math.min(...target.map(t => dLab(labHex(p.hex), t))), 0) + (Props.USED_ART.has(a.id) ? 1000 : 0);
    const ranked = list.slice().sort((a, b) => score(a) - score(b)); const out = [];
    for (let i = 0; i < anchors.length; i++) { const pool = ranked.filter(a => !out.includes(a)).slice(0, 3); const a = pick(r, pool); if (a) { out.push(a); Props.USED_ART.add(a.id); } }
    return out;
  }
  static async _art(f, it, P, g, r) {
    const a = f._artPick[f._artIdx = ((f._artIdx ?? -1) + 1)] || f._artPick[0]; if (!a) return;
    const w = +it.spec.w_m, d = +it.spec.d_m, rot = -(+it.spec.rot_deg || 0) * DEG;
    // the wall behind the piece: parallel, within 40 cm of its back
    const bx = +it.spec.x - (d / 2) * Math.sin(rot), bz = +it.spec.z - (d / 2) * Math.cos(rot); const back = new THREE.Vector2(-Math.sin(rot), -Math.cos(rot)); let gap = null;
    for (const e of f.edges || []) { if (e.n.dot(back) < 0.92) continue; const p = new THREE.Vector2(bx, bz); const dist = p.clone().sub(e.a).dot(e.n); if (dist > 0.05 || dist < -0.4) continue;
      const dir = e.b.clone().sub(e.a); const t = p.clone().sub(e.a).dot(dir) / dir.lengthSq(); if (t < 0.05 || t > 0.95) continue; if (gap == null || -dist < gap) gap = Math.max(0, -dist); }
    if (gap == null) return;
    const ceil = (+f.meta.ceiling_m || 2.6) - (+it.spec.y_m || 0);
    const under = it.spec.category === 'sofa' ? (it._backTop ?? 0.85) : Math.max(P.top(0, -d / 2 + 0.03) ?? 0, (P.top(0, 0) ?? 0.5) + 0.35);
    const bottom = Math.max(under + 0.22, it.spec.category === 'bed' ? 1.05 : 0.95);
    const asp = a.aspect || (a.w_px / a.h_px) || 1.4; let aw = clamp(w * (it.spec.category === 'bed' ? 0.6 : 0.55), 0.5, 1.15), ah = aw / asp;
    if (ah > 0.85) { ah = 0.85; aw = ah * asp; } const room = ceil - 0.28 - bottom; if (ah > room) { ah = room; aw = ah * asp; } if (ah < 0.3) return;
    const fr = 0.028, depth = 0.032, matB = 0.06 * Math.min(aw, ah); const frameC = r() < 0.5 ? mute(f._pal.wood, 0.9) : col('#1f1e1c');
    const grp = new THREE.Group(); grp.position.set(0, bottom + ah / 2, -d / 2 - gap + depth / 2 + 0.004);
    const fm = new THREE.MeshStandardMaterial({ color: frameC, roughness: 0.55 });
    for (const [x, y, sw, sh] of [[0, ah / 2 - fr / 2, aw, fr], [0, -ah / 2 + fr / 2, aw, fr], [-aw / 2 + fr / 2, 0, fr, ah], [aw / 2 - fr / 2, 0, fr, ah]]) { const b = mesh(new THREE.BoxGeometry(sw, sh, depth), fm); b.position.set(x, y, 0); grp.add(b); }
    const mat = mesh(new THREE.PlaneGeometry(aw - 2 * fr, ah - 2 * fr), new THREE.MeshStandardMaterial({ color: 0xf2efe8, roughness: 0.95 }), false); mat.position.z = depth / 2 - 0.004; grp.add(mat);
    const iw = aw - 2 * fr - 2 * matB, ih = ah - 2 * fr - 2 * matB;
    const pic = mesh(new THREE.PlaneGeometry(iw, ih), new THREE.MeshStandardMaterial({ map: texture('/' + a.file), roughness: 0.82 }), false); pic.position.z = depth / 2 - 0.002; grp.add(pic);
    grp.userData.art = a.id; g.add(grp);
  }

  // ---------- curtains: two sheer panels per window, floor to just under the ceiling, on a slim rod ----------
  static _curtains(f, room) {
    const type = String((f.plan && f.plan.room_type) || f.meta.type || '').toLowerCase(); if (/bath|kitchen|hall|laundry|closet|wc|storage|entry|utility/.test(type)) return;
    const ceil = +f.meta.ceiling_m || 2.6; const pal = f._pal; const r = rngFor(f.room + ':curtains');
    const sheer = fabric(f, pal.light.clone().lerp(col('#f7f5f0'), 0.45), { side: THREE.DoubleSide, opacity: 0.8, rough: 0.97, bump: 0.25, sheen: 0.3 });
    const rodM = new THREE.MeshStandardMaterial({ color: r() < 0.5 ? col('#1e1d1b') : mute(pal.wood, 0.9), roughness: 0.4, metalness: 0.3 });
    for (const wn of f.meta.windows || []) {
      const e = f.edges[wn.edge]; if (!e) continue; const ww = wn.s1 - wn.s0; if (ww < 0.35) continue;
      const dir = e.b.clone().sub(e.a).normalize(); const inward = e.n.clone().negate();
      const top = Math.min(ceil - 0.07, (wn.sill_m ?? 0.9) + (wn.height_m ?? 1.3) + 0.25); const s0 = Math.max(0.04, wn.s0 - 0.22), s1 = Math.min(e.len - 0.04, wn.s1 + 0.22);
      const pw = Math.min((s1 - s0) / 2, Math.max(0.38, ww * 0.28 + 0.22)); const H = top - 0.03 - 0.012;
      const at = (s, off) => e.a.clone().add(dir.clone().multiplyScalar(s)).add(inward.clone().multiplyScalar(off));
      const xAxis = new THREE.Vector3(dir.x, 0, dir.y), zAxis = new THREE.Vector3(inward.x, 0, inward.y); if (new THREE.Vector3().crossVectors(xAxis, new THREE.Vector3(0, 1, 0)).dot(zAxis) < 0) xAxis.negate();
      const q = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(xAxis, new THREE.Vector3(0, 1, 0), zAxis));
      for (const [a, b] of [[s0, s0 + pw], [s1 - pw, s1]]) {
        const geo = new THREE.PlaneGeometry(pw, H, Math.max(8, Math.round(pw / 0.02)), 8); const p = geo.attributes.position; const pleat = 0.085 + r() * 0.02, ph = r() * 6.28;
        for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i); const v = (y + H / 2) / H; p.setZ(i, (0.028 + 0.012 * (1 - v)) * Math.sin(x / pleat * 6.28 + ph) + 0.004 * Math.sin(x * 61 + v * 3)); }
        geo.computeVertexNormals(); const m = mesh(geo, sheer, false); const c = at((a + b) / 2, 0.1); m.position.set(c.x, 0.012 + H / 2, c.y); m.quaternion.copy(q); room.add(m);
      }
      const rod = mesh(new THREE.CylinderGeometry(0.011, 0.011, s1 - s0 + 0.08, 12), rodM); const rc = at((s0 + s1) / 2, 0.1); rod.position.set(rc.x, top - 0.01, rc.y); rod.quaternion.copy(q); rod.rotateZ(Math.PI / 2); room.add(rod);
      for (const s of [s0 - 0.04, s1 + 0.04]) { const fin = mesh(new THREE.SphereGeometry(0.02, 12, 8), rodM); const fc = at(s, 0.1); fin.position.set(fc.x, top - 0.01, fc.y); room.add(fin); }
    }
    mark(room);
  }
}
Props.USED_ART = new Set();
Props.FACING = { standing_picture_frame_01: -Math.PI / 2, standing_picture_frame_02: -Math.PI / 2, alarm_clock_01: Math.PI };   // models whose face is not +z (checked by rendering each from +z)
