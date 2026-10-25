"""Shared helpers for the designer-catalogue scrapers. Import with: sys.path.insert(0, <this dir>); from common import *
Polite (1.5 s per host, thread-safe), resumable (disk cache), never solves captchas / bypasses walls (walls are logged to raw/walls.json).
Python: feasibility/.venv/bin/python"""
import os, re, json, time, hashlib, pathlib, subprocess, threading, shutil, math, itertools, sys
import requests
H = pathlib.Path(__file__).resolve().parent
(H / "raw").mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
GLTF = str(H.parent / "abo/raw/node/node_modules/.bin/gltf-transform")
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
FX = {"EUR": 1.08, "GBP": 1.27, "USD": 1.0, "DKK": 0.145, "SEK": 0.095, "CHF": 1.13}
DELAY = 1.5
_S = requests.Session(); _S.headers.update({"User-Agent": UA, "Accept-Language": "en"})
_lock = threading.Lock(); _last = {}
WALLS = H / "raw/walls.json"

def log_wall(host, url, status, note=""):
    with _lock:
        w = json.load(open(WALLS)) if WALLS.exists() else {}
        w.setdefault(host, {"url": url, "status": status, "note": note})
        json.dump(w, open(WALLS, "w"), indent=1)

def _wait(host):
    with _lock:
        t = _last.get(host, 0); now = time.time(); d = max(0, t + DELAY - now); _last[host] = now + d
    if d: time.sleep(d)

def get(url, cache=None, binary=False, retries=2, session=None, **kw):
    """GET with rate limit + optional disk cache path (pathlib). Returns requests.Response-like (text/content/status_code) or None.
    On 403/429/captcha pages returns None and logs a wall (we never try to get around it)."""
    host = url.split("/")[2]
    if cache and pathlib.Path(cache).exists():
        class C: pass
        c = C(); b = pathlib.Path(cache).read_bytes(); c.content = b; c.text = b.decode("utf8", "replace"); c.status_code = 200; c.cached = True; c.url = url
        c.json = lambda: json.loads(c.text); return c
    S = session or _S
    for k in range(retries + 1):
        _wait(host)
        try: r = S.get(url, timeout=60, **kw)
        except Exception as e:
            if k == retries: return None
            time.sleep(3); continue
        if r.status_code in (403, 429) or (r.status_code == 503 and "cloudflare" in r.text[:3000].lower()) or re.search(r"Just a moment|captcha|px-captcha|datadome", r.text[:6000] if not binary and "text" in r.headers.get("content-type", "") else "", re.I):
            if r.status_code == 429 and k < retries: time.sleep(20 * (k + 1)); continue
            log_wall(host, url, r.status_code); return None
        if r.status_code >= 500 and k < retries: time.sleep(5); continue
        if r.status_code != 200: return None
        if cache:
            p = pathlib.Path(cache); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(r.content)
        return r
    return None

def cpath(brand, key, ext="html"):
    return H / "raw" / brand / "cache" / (hashlib.md5(key.encode()).hexdigest() + "." + ext)

def usd(price, cur):
    return None if price is None else round(float(price) * FX.get(cur, 1.0), 2)

# ---------------- categories & styles (same keyword table as ../catalog.py) ----------------
CATS = [  # (category, regex) first match wins; lamps first so "table lamp" is never a table
 ("pendant_lamp", r"pendant|suspension|chandelier|ceiling (?:lamp|light)|hanging lamp|ceiling"), ("floor_lamp", r"floor lamp|floor light|standing lamp|uplight|floor-lamp|floor lights?"),
 ("table_lamp", r"table lamp|desk lamp|table light|portable|task lamp|desk light|bedside lamp|table-lamp|\blamp\b|\blight\b|luminaire|lantern|\bled\b"),
 ("bar_stool", r"bar stool|counter stool|bar chair|barstool"), ("desk_chair", r"office chair|task chair|desk chair|swivel chair|work chair|aeron|mirra|embody|setu|cosm|conference"),
 ("sofa", r"sofa|couch|settee|loveseat|love seat|daybed|modular seating|sectional|banquette|\bseater\b|seating system"), ("ottoman", r"ottoman|pouf|pouffe|footstool|footrest"),
 ("bench", r"bench"), ("stool", r"stool"), ("armchair", r"armchair|lounge chair|easy chair|club chair|wing chair|recliner|arm chair|\begg\b|\bswan\b|\bant\b|lounge"),
 ("dining_chair", r"chair|\bseat\b|stacking|shell"), ("coffee_table", r"coffee table|lounge table|cocktail table|center table|centre table"),
 ("nightstand", r"nightstand|night stand|bedside"), ("side_table", r"side table|end table|accent table|occasional table|nesting|console|tray table|\bside\b"),
 ("desk", r"desk|writing table|\bwork ?station"), ("dining_table", r"dining table|table"), ("bed", r"\bbed\b|headboard"),
 ("wardrobe", r"wardrobe|armoire|closet|coat rack|hall"), ("bookcase", r"bookcase|bookshelf|shelf|shelving|shelves|\brack\b|etagere|storage system|\bcase\b"),
 ("dresser", r"dresser|chest of drawers|sideboard|cabinet|credenza|buffet|highboard|drawer|chest|\bunit\b"), ("tv_bench", r"tv bench|tv unit|media unit|tv stand"),
 ("rug", r"\brug\b|carpet"), ("mirror", r"mirror"), ("plant_pot", r"plant pot|planter|flower ?pot|\bpot\b"),
]
def categorize(*texts):
    t = " ".join(x or "" for x in texts).lower().replace("_", " ")
    for c, rx in CATS:
        if re.search(rx, t): return c
    return "other"
STYLE = {
 "scandinavian": ["scandinav", "danish", "nordic", "birch", "oak", "ash ", "light wood", "beige", "linen", "finnish", "swedish"],
 "modern": ["modern", "contemporary", "sleek", "clean lines", "glass", "chrome", "gloss", "black", "aluminium", "aluminum", "polypropylene"],
 "minimal": ["minimal", "simple", "clean", "slim", "uncluttered", "compact", "streamlined", "thin", "pure"],
 "mid-century": ["mid-century", "retro", "tapered", "walnut", "vintage", "1950", "1960", "195", "196", "splayed", "eames", "jacobsen", "wegner", "saarinen", "aalto"],
 "industrial": ["industrial", "steel", "metal frame", "black metal", "iron", "mesh", "wire", "concrete"],
 "classic": ["classic", "traditional", "timeless", "tufted", "velvet", "leather", "brass", "ornate", "turned", "icon"],
}
def style_tags(name, desc, mat=""):
    t = f" {name} {desc} {mat} ".lower(); sc = {}
    for st, kws in STYLE.items():
        n = sum(1 for k in kws if k in t)
        if n: sc[st] = n
    return [k for k, v in sorted(sc.items(), key=lambda kv: -kv[1])][:3] or ["modern"]

def slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower().replace("&", "and")).strip("-")[:60]

# ---------------- model conversion ----------------
def blender_convert(src, dst):
    """FBX/3DS/DAE/OBJ/STL/etc -> GLB through headless Blender (Blender 5.x at /Applications/Blender.app). Returns True/False."""
    script = H / "blender_convert.py"
    p = subprocess.run([BLENDER, "-b", "-noaudio", "-P", str(script), "--", str(src), str(dst)], capture_output=True, timeout=900)
    return p.returncode == 0 and pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 1000

def to_glb(src, dst, force_blender=False):
    """Convert any mesh file to a GLB at dst (unscaled, raw units). glb/gltf are copied/re-packed; obj/ply/stl/off via trimesh; fbx/3ds/dae/blend via Blender."""
    src = pathlib.Path(src); dst = pathlib.Path(dst); dst.parent.mkdir(parents=True, exist_ok=True); ext = src.suffix.lower()
    try:
        if ext == ".glb": shutil.copy(src, dst); return dst.exists()
        if ext in (".obj", ".ply", ".stl", ".gltf", ".off") and not force_blender:
            import trimesh
            sc = trimesh.load(str(src), force="scene", process=False)
            if len(sc.geometry) == 0: raise ValueError("empty")
            sc.export(str(dst)); return dst.exists() and dst.stat().st_size > 500
    except Exception as e:
        print("trimesh failed", src.name, e, "-> blender", flush=True)
    return blender_convert(src, dst)

def extents(glb):
    import trimesh
    sc = trimesh.load(str(glb), force="scene"); return sc.bounds, sc.extents

# typical (height / sqrt(width*depth)) by category, used to pick Y-up vs Z-up when listed dims are unknown
ASPECT = {"floor_lamp": 4, "table_lamp": 1.6, "pendant_lamp": 1.0, "dining_chair": 1.6, "armchair": 1.0, "desk_chair": 1.8, "bar_stool": 2.4, "stool": 1.3, "sofa": 0.55,
          "coffee_table": 0.45, "side_table": 0.9, "dining_table": 0.4, "desk": 0.5, "bed": 0.5, "bench": 0.6, "ottoman": 0.6, "wardrobe": 2.5, "bookcase": 2.2, "dresser": 0.9,
          "nightstand": 1.0, "tv_bench": 0.45, "mirror": 2.0}
def fit_transform(glb_in, glb_out, listed=None, allow_zup=True, category=None):
    """Rescale/reorient a raw-unit GLB so its bounding box matches the listed dims.
    listed = (width_m, depth_m, height_m) (any may be None). Tries unit scales (mm,cm,m,inch) and Z-up->Y-up rotation, picks best log-error.
    Without listed dims: if the model's largest extent looks like cm/mm (>10 m) rescale by 0.01/0.001; keep orientation (Y-up unless Z extent is clearly the height).
    Returns dict(scale, zup, dims=(w,d,h) metres, err). dims is (width_x, depth_z, height_y)"""
    import trimesh, numpy as np
    sc = trimesh.load(str(glb_in), force="scene"); ext = sc.extents.copy()
    cands = []  # (label, matrix-rotate Zup->Yup?)
    def dims_for(e, zup): return (e[0], e[1], e[2]) if zup else (e[0], e[2], e[1])   # returns (w,d,h) given extents ordering
    best = None
    for zup in ((False, True) if allow_zup else (False,)):
        for s in (1, 0.1, 0.01, 0.001, 0.0254, 0.3048):
            w, d, h = (v * s for v in dims_for(ext, zup))
            if listed and any(listed):
                err = 0; n = 0
                for a, b in zip((w, d, h), listed):
                    if b: err += abs(math.log(max(a, 1e-6) / b)); n += 1
                err /= max(n, 1)
                # allow width/depth swap
                if listed[0] and listed[1]:
                    e2 = 0; n2 = 0
                    for a, b in zip((d, w, h), listed):
                        if b: e2 += abs(math.log(max(a, 1e-6) / b)); n2 += 1
                    err = min(err, e2 / max(n2, 1))
            else:
                err = 0 if (0.15 < max(w, d, h) < 4) else 9
                if category in ASPECT and err == 0:
                    err += 0.6 * abs(math.log(max(h, 1e-6) / math.sqrt(max(w * d, 1e-9)) / ASPECT[category]))   # category prior on shape
                if not zup: err += 0.01 if not (category in ASPECT) else -0.15   # prefer Y-up (3ds Max/Blender/most CAD exports), then natural scale order
            if best is None or err < best[0] - 1e-9: best = (err, zup, s)
    err, zup, s = best
    M = np.eye(4)
    if zup: M[:3, :3] = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])   # Z-up -> Y-up
    sc.apply_transform(M); sc.apply_scale(s)
    b = sc.bounds; T = np.eye(4); T[:3, 3] = [-(b[0][0] + b[1][0]) / 2, -b[0][1], -(b[0][2] + b[1][2]) / 2]; sc.apply_transform(T)  # centre xz, floor y=0
    sc.export(str(glb_out)); e = sc.extents
    return {"scale": s, "zup": zup, "dims": [round(float(e[0]), 3), round(float(e[2]), 3), round(float(e[1]), 3)], "err": round(float(err), 3)}

def optimise(src, dst):
    """gltf-transform: Draco + WebP 1024 (as abo/optimize.py). Returns (orig_bytes, opt_bytes) or None."""
    src = pathlib.Path(src); dst = pathlib.Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([GLTF, "optimize", str(src), str(dst), "--compress", "draco", "--texture-compress", "webp", "--texture-size", "1024"], capture_output=True, text=True)
    ok = p.returncode == 0 and dst.exists() and subprocess.run([GLTF, "inspect", str(dst)], capture_output=True).returncode == 0
    if not ok: dst.unlink(missing_ok=True); return None
    return src.stat().st_size, dst.stat().st_size

def process_model(pid, raw_file, listed=None, category=None):
    """raw mesh file -> models/<pid>.glb (scaled+oriented, uncompressed) -> models_opt/<pid>.glb. Returns info dict or None."""
    tmp = H / "raw" / "tmp" / f"{pid}.glb"; out = H / "models" / f"{pid}.glb"; opt = H / "models_opt" / f"{pid}.glb"
    if opt.exists() and out.exists():
        try: return {"model_bytes_orig": out.stat().st_size, "model_bytes": opt.stat().st_size, "cached": True, "dims": json.load(open(out.with_suffix(".json")))["dims"]}
        except Exception: pass
    ext = pathlib.Path(raw_file).suffix.lower()
    if not to_glb(raw_file, tmp): return None
    try: info = fit_transform(tmp, out, listed, allow_zup=ext in (".obj", ".ply", ".stl", ".off"), category=category)   # Blender output is already Y-up metres
    except Exception as e:
        print("fit failed", pid, e); return None
    finally: tmp.unlink(missing_ok=True)
    json.dump(info, open(out.with_suffix(".json"), "w"))
    r = optimise(out, opt)
    if not r: return None
    info.update(model_bytes_orig=r[0], model_bytes=r[1]); return info

def make_item(brand, name, *, designer=None, category=None, w=None, d=None, h=None, price=None, currency=None, price_source=None, product_url=None, buy_url=None,
              image=None, model=None, description="", materials=None, colours=None, year=None, source_formats=None, variant=None, pid=None, extra=None):
    """Build a catalogue item. `model` = process_model info dict (with 'dims') or None. image = local path under images/ (already saved)."""
    brand_slug = slug(brand); pid = pid or f"dsg-{brand_slug}-{slug(name)}" + (f"-{slug(variant)}" if variant else "")
    desc = re.sub(r"\s+", " ", description or "").strip()[:300]
    category = category or categorize(name)
    it = {"id": pid, "brand": brand, "designer": designer, "name": name, "category": category,
          "width_m": w, "depth_m": d, "height_m": h, "price_usd": usd(price, currency) if price is not None else None,
          "price_source": price_source or (f"brand shop {currency}" if price is not None else None), "price_currency": currency if price is not None else None, "price_orig": price,
          "product_url": product_url, "buy_url": buy_url or product_url, "image": f"furnish/designer/images/{image}" if image else None,
          "model_glb": f"furnish/designer/models_opt/{pid}.glb" if model else None, "model_glb_orig": f"furnish/designer/models/{pid}.glb" if model else None,
          "description": desc, "materials": materials, "colours": colours, "year": year, "style_tags": style_tags(name, desc, str(materials)), "tier": "design", "source": f"{brand} website",
          "source_formats": source_formats, "fetched": time.strftime("%Y-%m-%d")}
    if model:
        it["model_bytes"] = model.get("model_bytes"); it["model_bytes_orig"] = model.get("model_bytes_orig"); it["model_dims_m"] = model.get("dims")
        # if listed dims missing, fill from the (rescaled) model bbox and flag it
        dm = model.get("dims")
        if dm and not (w and d and h): it["width_m"], it["depth_m"], it["height_m"] = (w or dm[0]), (d or dm[1]), (h or dm[2]); it["dims_source"] = "glb_bbox"
        else: it["dims_source"] = "listed"
    if extra: it.update(extra)
    return it

def save_items(brand, items):
    """Write raw/items_<brand>.json (merge.py gathers all of these)."""
    p = H / "raw" / f"items_{slug(brand)}.json"; tmp = p.with_suffix(".tmp"); json.dump(items, open(tmp, "w"), indent=1); tmp.replace(p)

def save_image(url, fname, brand):
    """Download a product image to images/<fname> (jpg/png/webp kept as is; resized to <=1024 px jpg). Returns fname or None."""
    from PIL import Image
    import io
    out = H / "images" / fname
    if out.exists(): return fname
    r = get(url, binary=True)
    if not r: return None
    try:
        im = Image.open(io.BytesIO(r.content)); im.thumbnail((1024, 1024)); im.convert("RGB").save(out, "JPEG", quality=85); return fname
    except Exception: return None
