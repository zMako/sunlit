"""UDR's own site (udr.com; robots.txt disallows only /generatepdf/*, no terms-of-use page restricting automated access):
San Francisco and Bay Area communities with per-floor-plan 2D plan images and TRUE square footage.

    feasibility/.venv/bin/python feasibility/scrape_udr.py [--sf-only] [max_properties]

Each community's /apartments-pricing/ page embeds window.udr.jsonObjPropertyViewModel with floorPlans[] {Name, bedRooms,
bathRooms, sqFtMin, sqFtMax, units[] {media[] {src, type photo|diagram}}}. Diagrams come as a 3D render (.gif, skipped)
and a 2D plan, as .jpg or .gif with or without _2d/_3d in the name; pixels decide (colour + softness), plans saved as PNG. Writes feasibility/listings/udr-<slug>/meta.json (same shape as gs-*, plus per-plan sqft
so rescale.py gets true sizes) and plans/plan_NN.<ext>, one per distinct plan image URL. No photos (the library is about
plans). Paced 2-4 s per page, ~0.5 s per image. Re-runs skip done folders."""
import sys, re, json, time, random, pathlib, html, requests
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "listings"; BASE = "https://www.udr.com"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
S = requests.Session(); S.headers.update(UA)
SF_ONLY = "--sf-only" in sys.argv; ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]; MAXP = int(ARGS[0]) if ARGS else 99

def get(url):
    for i in range(3):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 429: time.sleep(20 * (i + 1)); continue
            return r
        except requests.RequestException: time.sleep(3)
    return None

def properties():
    r = get(BASE + "/san-francisco-bay-area-apartments/"); time.sleep(random.uniform(2, 4))
    paths = sorted(set(re.findall(r'href="(/san-francisco-bay-area-apartments/[^/"#]+/[^/"#]+/)"', r.text)))
    return [p for p in paths if not SF_ONLY or "/san-francisco/" in p or "/west-soma/" in p]

def ld_blocks(text):
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
        try: out.append(json.loads(m.group(1)))
        except Exception: pass
    return out

def find(obj, key):
    if isinstance(obj, dict):
        if key in obj: yield obj[key]
        for v in obj.values(): yield from find(v, key)
    elif isinstance(obj, list):
        for v in obj: yield from find(v, key)

def plan_candidates(fp):
    """Diagram URLs for one floor plan, most plan-like first: UDR publishes a 3D render and a 2D plan per type, as .jpg or
    .gif, named ..._3d... / ..._2d... or not at all, so names only order the candidates and pixels decide (colour3d)."""
    cands = []
    for m in list(find(fp, "galleryImages")) + list(find(fp, "media")):
        for it in (m or []):
            if isinstance(it, dict) and it.get("type") == "diagram" and it.get("src"): cands.append(it["src"])
    li = (fp.get("listingImage") or {}).get("src")
    if li: cands.append(li)
    out = []
    for u in cands:
        u = requests.compat.urljoin(BASE, u)
        if u not in out and u.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".gif")): out.append(u)
    def rank(u):
        n = u.lower().rsplit("/", 1)[-1]
        return (0 if "2d" in n else 2 if "3d" in n else 1, n.endswith(".gif"))
    return sorted(out, key=rank)

def colour3d(img):
    """Share of clearly coloured pixels: 3D renders (wood floors, furniture) score high, line plans near zero."""
    hsv = img.convert("RGB").resize((256, 256)).convert("HSV"); s = list(hsv.getchannel("S").getdata()); v = list(hsv.getchannel("V").getdata())
    return sum(1 for a, b in zip(s, v) if a > 60 and b > 40) / len(s)

def soft(im):
    """plan_engine.softness (soft gradients / hard edges): drawings ~0.4-1.5, 3D renders and photos > 3."""
    import tempfile, os
    sys.path.insert(0, str(HERE.parent / "app" / "plan3d")); import plan_engine as pe
    fd, tmp = tempfile.mkstemp(suffix=".png"); os.close(fd)
    try: im.save(tmp); return pe.softness(tmp)
    finally: os.unlink(tmp)

def fetch_plan(urls, cache):
    """First candidate whose pixels look like a 2D plan -> (url, PIL image, colour score) or None."""
    from PIL import Image
    import io
    best = None
    for u in urls[:4]:
        if u not in cache:
            rr = get(u); time.sleep(random.uniform(0.3, 0.7))
            try: cache[u] = Image.open(io.BytesIO(rr.content)).convert("RGB") if rr and rr.ok and len(rr.content) > 3000 else None
            except Exception: cache[u] = None
        im = cache[u]
        if im is None or min(im.size) < 250: continue
        c = colour3d(im)
        if soft(im) > 3.0: c = 1.0   # soft shading: a 3D render, never a plan
        if best is None or c < best[2]: best = (u, im, c)
        if c < 0.04: break
    return best if best and best[2] < 0.10 else None

def scrape(path):
    slug = path.rstrip("/").rsplit("/", 1)[-1]; d = OUT / f"udr-{slug}"
    if (d / "meta.json").exists(): print(f"[udr] {slug} done already"); return
    home = get(BASE + path); time.sleep(random.uniform(2, 4))
    pr = get(BASE + path + "apartments-pricing/")
    if not pr or pr.status_code != 200: print(f"[udr] {slug} pricing {pr.status_code if pr else 'ERR'}"); return
    i = pr.text.find('"floorPlans":[')
    if i < 0: print(f"[udr] {slug} no floorPlans"); return
    fps, _ = json.JSONDecoder().raw_decode(pr.text[i + len('"floorPlans":'):])
    addr, lat, lon, title, body = {}, None, None, None, ""
    for b in ld_blocks(home.text if home is not None and home.ok else "") + ld_blocks(pr.text):
        addr = addr or next(iter(a for a in find(b, "address") if isinstance(a, dict)), {})
        geo = next(iter(g for g in find(b, "geo") if isinstance(g, dict)), None)
        if geo and lat is None: lat, lon = geo.get("latitude"), geo.get("longitude")
    if home is not None and home.ok:
        mt = re.search(r'<meta name="description" content="([^"]*)"', home.text); body = html.unescape(mt.group(1)) if mt else ""
        if lat is None:
            mg = re.search(r'"latitude"\s*:\s*"?(-?\d+\.\d+)"?\s*,\s*"longitude"\s*:\s*"?(-?\d+\.\d+)', home.text)
            if mg: lat, lon = float(mg.group(1)), float(mg.group(2))
        mt = re.search(r"<title>([^<|]*)", home.text); title = html.unescape(mt.group(1)).strip() if mt else None
    title = re.sub(r"\s+Apartments\b.*$", "", title or slug.replace("-", " ").title()).strip() or slug
    d.mkdir(parents=True, exist_ok=True); (d / "plans").mkdir(exist_ok=True)
    seen, out, cache, rejected = {}, [], {}, 0
    for fp in fps:
        got = fetch_plan(plan_candidates(fp), cache)
        if not got: rejected += 1; continue
        u, im, col = got
        if u in seen:   # same drawing for two plan names: count the units on the first entry
            out[seen[u]]["units_available"] += len(fp.get("units") or []); continue
        f = f"plan_{len(out):02d}.png"; im.save(d / "plans" / f); seen[u] = len(out)   # PNG: the engine reads with OpenCV, which cannot open GIF
        smin, smax = fp.get("sqFtMin"), fp.get("sqFtMax")
        sqft = int(round((smin + smax) / 2)) if smin and smax else (smin or smax)
        out.append({"file": f"plans/{f}", "name": fp.get("Name"), "bedrooms": fp.get("bedRooms"), "bathrooms": fp.get("bathRooms"), "sqft": sqft,
                    "units_available": len(fp.get("units") or []), "rent_min": fp.get("rentMin"), "image_url": u, "colour": round(col, 3), "id": fp.get("id")})
    if not out:
        print(f"[udr] {slug} no 2D plans of {len(fps)}")
        for q in (d / "plans", d):
            try: q.rmdir()
            except OSError: pass
        return
    street = addr.get("streetAddress", ""); city = addr.get("addressLocality", ""); z = addr.get("postalCode", "")
    meta = {"url": BASE + path, "source": "udr", "title": title, "address": f"{street}, {city} {z}".strip(", "), "city": city, "lat": lat, "lon": lon,
            "n_photos": 0, "sqft_total": None, "bedrooms": None, "bathrooms": None, "body": body, "photo_codes": [], "floorplans": out,
            "note": "floor plans of the building's currently listed unit types; sqft per plan from UDR (true size); no photos"}
    json.dump(meta, open(d / "meta.json", "w"), indent=1)
    print(f"[udr] {slug:28s} {title[:30]:30s} {city:14s} plans {len(out):2d} of {len(fps)} (no 2D: {rejected}) geo {lat is not None}", flush=True)

if __name__ == "__main__":
    props = properties(); print(f"[udr] {len(props)} communities", flush=True)
    for p in props[:MAXP]:
        try: scrape(p)
        except Exception as e: print(f"[udr] {p} ERROR {type(e).__name__} {e}", flush=True)
        time.sleep(random.uniform(2, 4))
    print("[udr] done")
