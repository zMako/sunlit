// Liquid glass for .glass elements: edge refraction through an SVG displacement map (Chromium only; Safari and Firefox keep
// the frosted base from movein.css). enhanceGlass(el) for elements added later; enhanceAll() for what is on the page now.
const chromium = !!navigator.userAgentData?.brands?.some(b => /Chromium/.test(b.brand));
let svg = null, k = 0;

function mapFor(w, h, r, bezel) {   // R,G = sampling offset toward the inside, strongest at the rim of a rounded box
  const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d'), img = g.createImageData(w, h), d = img.data;
  const hw = w / 2, hh = h / 2;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const px = x + .5 - hw, py = y + .5 - hh, qx = Math.abs(px) - (hw - r), qy = Math.abs(py) - (hh - r);
    const out = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)), depth = -(out + Math.min(Math.max(qx, qy), 0) - r);
    let nx = 0, ny = 0; if (qx > 0 && qy > 0) { nx = qx / out * Math.sign(px); ny = qy / out * Math.sign(py); } else if (qx > qy) nx = Math.sign(px); else ny = Math.sign(py);
    const t = depth < bezel && depth > 0 ? 1 - depth / bezel : 0, m = 1 - Math.sqrt(1 - t * t);   // circular lens profile: flat inside, bending at the rim
    const i = (y * w + x) * 4; d[i] = 128 - nx * m * 127; d[i + 1] = 128 - ny * m * 127; d[i + 2] = 128; d[i + 3] = 255;
  }
  g.putImageData(img, 0, 0); return c.toDataURL();
}

export function enhanceGlass(el, { scale = 46, bezel = 18, blur = 6 } = {}) {
  if (!chromium || el.dataset.glass) return; el.dataset.glass = '1';
  if (!svg) { svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('width', 0); svg.setAttribute('height', 0); svg.style.position = 'absolute'; document.body.appendChild(svg); }
  const id = 'lg' + (k++); const f = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
  f.setAttribute('id', id); f.setAttribute('color-interpolation-filters', 'sRGB'); f.setAttribute('x', 0); f.setAttribute('y', 0); f.setAttribute('width', '100%'); f.setAttribute('height', '100%');
  f.innerHTML = `<feImage result="map" preserveAspectRatio="none"/><feDisplacementMap in="SourceGraphic" in2="map" scale="${scale}" xChannelSelector="R" yChannelSelector="G"/>`; svg.appendChild(f);
  const im = f.querySelector('feImage'); let last = '';
  const redo = () => { const w = Math.round(el.offsetWidth), h = Math.round(el.offsetHeight); if (!w || !h || w * h > 900000) return;   // large panels keep the plain frost
    const r = Math.min(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0, h / 2, w / 2), key = `${w}x${h}x${r}`; if (key === last) return; last = key;
    im.setAttribute('href', mapFor(w, h, r, Math.min(bezel, r || bezel))); im.setAttribute('width', w); im.setAttribute('height', h);
    el.style.backdropFilter = `url(#${id}) blur(${blur}px) saturate(180%)`; };
  new ResizeObserver(redo).observe(el); redo();
}
export function enhanceAll(root = document) { for (const el of root.querySelectorAll('.glass')) enhanceGlass(el); }
