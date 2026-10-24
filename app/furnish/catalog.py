"""IKEA US furniture catalogue builder for the room planner. Reads category pages (allowed by robots.txt; no search/filter/sort
URLs), then each product page (ld+json facts: name, type, price, dimensions in metres, image, GLB url), and downloads IKEA's
GLB model to app/furnish/models/<id>.glb and the main image to app/furnish/imgcache/<id>.jpg for LOCAL hackathon-demo use.
All requests are paced 3-5 s. Resumable: catalog.json is written after every item; discovered URLs are cached in
catalog_urls.json; existing items/files are never refetched.

    feasibility/.venv/bin/python app/furnish/catalog.py [per_category=40] [max_minutes=150]"""
import sys, re, json, time, random, pathlib, html, requests
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "catalog.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36", "Accept-Language": "en-US"}
S = requests.Session(); S.headers.update(UA)
PER = int(sys.argv[1]) if len(sys.argv) > 1 else 40
MAXMIN = float(sys.argv[2]) if len(sys.argv) > 2 else 150
T0 = time.time()
MODELS = HERE / 'models'; IMGS = HERE / 'imgcache'; URLS = HERE / 'catalog_urls.json'
MODELS.mkdir(exist_ok=True); IMGS.mkdir(exist_ok=True)
# our category -> IKEA category slugs (several sub-pages per category; the ?page=N param is client-side only, so sub-categories give breadth)
CATS = {
 "bed": ["bed-frames-16284", "upholstered-beds-49096", "beds-with-storage-25205", "twin-beds-16285", "guest-beds-daybeds-19037", "beds-bm003"],
 "sofa": ["two-seat-sofas-10668", "three-seat-sofas-10670", "fabric-sectionals-10671", "sofas-with-chaise-47388", "sofas-sectionals-fu003", "sleeper-sofas-10663"],
 "armchair": ["fabric-armchairs-10687", "armchairs-chaises-fu006", "leather-armchairs-10696", "rattan-armchairs-20907", "lounge-chairs-53257", "reclining-chairs-47359"],
 "coffee_table": ["coffee-tables-10716", "multifunctional-tables-57537", "nesting-tables-57298"],
 "side_table": ["side-end-tables-10717", "accent-tables-10705", "sofa-console-tables-16246"],
 "tv_bench": ["tv-benches-10810", "tv-media-furniture-10475", "tv-media-storage-14885", "besta-tv-benches-12153"],
 "bookcase": ["bookcases-10382", "bookcases-shelving-units-st002", "storage-shelves-units-10397", "cube-wall-shelves-55015"],
 "dresser": ["chests-of-drawers-10451", "dressers-storage-drawers-st004"],
 "nightstand": ["nightstands-20656"],
 "wardrobe": ["armoires-wardrobes-19053", "pax-wardrobes-without-doors-19110", "hinged-wardrobes-48005", "open-wardrobes-43634", "sliding-wardrobes-43635"],
 "dining_table": ["dining-tables-21825", "dining-tables-2-seats-57297", "dining-tables-4-seats-21826", "dining-tables-6-seats-21827", "extendable-tables-21829", "round-tables-59244"],
 "dining_chair": ["dining-chairs-25219", "upholstered-chairs-25221", "folding-chairs-25222"],
 "bar_stool": ["bar-stools-chairs-20864", "stools-22659"],
 "desk": ["desks-computer-desks-20649", "desks-for-home-20651", "standing-desks-55008", "gaming-desks-47070"],
 "desk_chair": ["desk-chairs-20652", "desk-chairs-for-home-20653", "office-chairs-20654", "gaming-chairs-47067"],
 "rug": ["rugs-10653", "large-medium-rugs-10692", "runners-small-rugs-10689", "handmade-rugs-39267"],
 "floor_lamp": ["floor-lamps-10731"],
 "table_lamp": ["table-lamps-10732", "desk-lamps-20502"],
 "mirror": ["mirrors-20489", "standing-mirrors-49139", "wall-mirrors-24858", "round-mirrors-24860", "large-mirrors-24859", "decorative-mirrors-24861"],
 "plant": ["artificial-floor-plants-700520", "artificial-plants-flowers-20492", "floor-plants-700524", "plants-10779", "desk-plants-700523"],
 "plant_pot": ["indoor-plant-pots-10778", "flower-pots-stands-pp004", "plant-stands-movers-20494", "hanging-planters-59240"],
}
FRAC = {"½": .5, "¼": .25, "¾": .75, "⅛": .125, "⅜": .375, "⅝": .625, "⅞": .875}


def pause(): time.sleep(random.uniform(3, 5))

def get(url, binary=False):
    for i in range(3):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 429: time.sleep(30 * (i + 1)); continue
            return r
        except requests.RequestException: time.sleep(5)
    return None

def inches_to_m(txt):
    """'66 1/8 "' or '82 ⅝"' or '30 ½ "' or feet-inches \"5 ' 3 \\\"\" -> metres"""
    if not txt: return None
    t = html.unescape(txt).replace("″", '"').replace("′", "'").strip()
    ft = re.match(r"\s*(\d+)\s*'\s*(\d+)?\s*(?:(\d)/(\d))?\s*\"?\s*$", t)
    if ft:
        v = int(ft.group(1)) * 12 + (int(ft.group(2)) if ft.group(2) else 0) + (int(ft.group(3)) / int(ft.group(4)) if ft.group(3) else 0)
        return round(v * 0.0254, 3)
    t = t.replace('"', "")
    m = re.match(r"(\d+)(?:\s+(\d)/(\d))?\s*([½¼¾⅛⅜⅝⅞])?", t)
    if not m: return None
    v = int(m.group(1)) + (int(m.group(2)) / int(m.group(3)) if m.group(2) else 0) + (FRAC.get(m.group(4), 0) if m.group(4) else 0)
    return round(v * 0.0254, 3)

def ld_blocks(h): return re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S)
BAD = r"mattress|slatted|pillow|duvet|sheet|cover|protector|topper|leg-|legs-|cushion|-frame-\d|slats|-set-of|bag-|insert|wheel|caster|drawer-unit-on|door-|-doors-|-shelf-\d|hinge|-kit|-parts|pull-out|connector|handle|-top-\d|tabletop|table-top|underframe|base-cabinet|lamp-shade|lampshade|cord-set|light-bulb|bulb|led-|-led-|trim-|wardrobe-interior|-fronts|clothes-rail|-rail-"
STYLE = {  # style -> keywords in name/description/colour/type
 "scandinavian": ["scandinav", "birch", "oak", "pine", "ash ", "light wood", "white", "beige", "linen", "hemnes", "malm", "kallax", "billy", "lack ", "uppland", "friheten", "ektorp", "poaeng", "poang", "stoense", "hoeganaes"],
 "modern": ["modern", "contemporary", "sleek", "clean lines", "glass", "chrome", "gloss", "high-gloss", "black", "tempered", "minimalist look"],
 "minimal": ["minimal", "simple", "clean", "slim", "uncluttered", "compact", "streamlined", "thin"],
 "rustic": ["rustic", "rattan", "wicker", "bamboo", "seagrass", "jute", "solid wood", "solid pine", "natural", "cabin", "woven", "handmade", "hand-woven", "weathered", "raw"],
 "mid-century": ["mid-century", "retro", "tapered", "walnut", "vintage", "1950", "1960", "angled legs", "splayed"],
 "industrial": ["industrial", "steel", "metal frame", "black metal", "iron", "raw metal", "mesh", "wire", "concrete", "dark gray steel"],
 "classic": ["classic", "traditional", "timeless", "tufted", "velvet", "leather", "brass", "ornate", "turned", "panel", "button"],
}
def style_tags(name, desc, color, tn):
    t = f" {name} {desc} {color or ''} {tn or ''} ".lower(); sc = {}
    for st, kws in STYLE.items():
        n = sum(1 for k in kws if k in t)
        if n: sc[st] = n
    tags = [k for k, v in sorted(sc.items(), key=lambda kv: -kv[1])][:3]
    return tags or ["scandinavian"]   # IKEA's house style when nothing else is evident

def product(url, cat):
    r = get(url)
    if not r or r.status_code != 200: return None
    h = r.text; P = None; glb = None
    for l in ld_blocks(h):
        if '"Product"' in l and P is None:
            try: j = json.loads(l)
            except Exception: j = None
            if isinstance(j, dict) and j.get("@type") == "Product":
                off = j.get("offers") or {}; off = off[0] if isinstance(off, list) and off else off
                img = j.get("image"); img = img[0] if isinstance(img, list) and img else img
                if isinstance(img, dict): img = img.get("contentUrl") or img.get("url")
                P = {"name": html.unescape(str(j.get("name") or "")), "sku": j.get("sku"), "image": img if isinstance(img, str) else None,
                     "width_m": inches_to_m(j.get("width")), "depth_m": inches_to_m(j.get("depth")) or inches_to_m(j.get("length")), "height_m": inches_to_m(j.get("height")), "length_m": inches_to_m(j.get("length")),
                     "price_usd": float(off.get("price")) if isinstance(off, dict) and off.get("price") not in (None, "") else None, "description": html.unescape(str(j.get("description") or ""))[:300], "color": j.get("color")}
        if "3DModel" in l:
            m = re.search(r'"contentUrl"\s*:\s*"([^"]+\.glb[^"]*)"', l); glb = m.group(1) if m else glb
    if not P: return None
    if not P["image"]:
        m = re.search(r'property="og:image"\s+content="([^"]+)"', h) or re.search(r'content="([^"]+)"\s+property="og:image"', h)
        P["image"] = m.group(1) if m else None
    # fallback: measurement list on the page (sofas, chairs, plants often lack height/width in ld+json)
    ms_ = {}
    for nm, val in re.findall(r'measurement-name">([^<]+)</span><span class="pipf-measurements-tab__measurement-value">([^<]+)<', h):
        v = inches_to_m(html.unescape(val))
        if v: ms_.setdefault(nm.strip().lower(), v)
    if not P["height_m"]:
        hs = [v for k, v in ms_.items() if "height" in k and not re.search(r"under|seat|arm|min|max|adjust|step|pot", k)]
        P["height_m"] = max(hs) if hs else None
    if not P["width_m"]:
        P["width_m"] = ms_.get("width") or ms_.get("length") or ms_.get("diameter") or ms_.get("pot diameter") or ms_.get("outside diameter")
    if not P["depth_m"]:
        P["depth_m"] = ms_.get("depth") or ms_.get("diameter") or ms_.get("pot diameter") or ms_.get("outside diameter") or (P["width_m"] if cat in ("plant", "plant_pot") else None)
    tn = re.search(r'"typeName"\s*:\s*"([^"]+)"', h); P["type_name"] = tn.group(1) if tn else None
    ms = re.search(r'"itemMeasureReferenceText"\s*:\s*"([^"]*)"', h); P["size_label"] = ms.group(1) if ms else None
    series = (P["name"].split() or [""])[0].lower()
    vs = []
    for u in dict.fromkeys(re.findall(r'https://www\.ikea\.com/us/en/p/([a-z0-9-]+)/', h)):
        if u.startswith(series + "-") and not re.search(BAD, u) and "https://www.ikea.com/us/en/p/" + u + "/" != url: vs.append("https://www.ikea.com/us/en/p/" + u + "/")
    P["variants"] = vs[:12]
    P["style_tags"] = style_tags(P["name"], P["description"], P["color"], P["type_name"])
    P.update({"id": "ikea-" + (P["sku"] or url.rstrip("/").rsplit("-", 1)[-1]).replace(".", ""), "category": cat, "product_url": url, "model_glb_url": glb, "source": "ikea.com/us product page", "fetched": time.strftime("%Y-%m-%d")})
    return P

def download(url, dest, minbytes=500):
    r = get(url)
    if r is not None and r.status_code == 200 and len(r.content) >= minbytes:
        dest.write_bytes(r.content); return len(r.content)
    return None

def assets(p, fails):
    """download glb + image for item p (paced), recording model_glb / model_bytes / image_local"""
    if p.get("model_glb_url") and not (MODELS / (p["id"] + ".glb")).exists():
        n = download(p["model_glb_url"], MODELS / (p["id"] + ".glb"), 2000); pause()
        if n is None: fails.append(("glb", p["id"], p["model_glb_url"]))
    f = MODELS / (p["id"] + ".glb")
    if f.exists(): p["model_glb"] = "furnish/models/" + p["id"] + ".glb"; p["model_bytes"] = f.stat().st_size
    im = IMGS / (p["id"] + ".jpg")
    if p.get("image") and not im.exists():
        n = download(p["image"] + ("&" if "?" in p["image"] else "?") + "f=l", im); pause()
        if n is None: fails.append(("img", p["id"], p["image"]))
    if im.exists(): p["image_local"] = "furnish/imgcache/" + p["id"] + ".jpg"

def save(out): 
    tmp = OUT.with_suffix(".tmp"); json.dump(out, open(tmp, "w"), indent=1); tmp.replace(OUT)

def out_of_time(): return time.time() - T0 > MAXMIN * 60

def main():
    urls = json.load(open(URLS)) if URLS.exists() else {}
    seen = {u for v in urls.values() for u in v}
    for cat, slugs in CATS.items():
        for slug in slugs:
            if slug in urls.get("_done", []): continue
            r = get(f"https://www.ikea.com/us/en/cat/{slug}/")
            if not r or r.status_code != 200: print(f"[cat] {slug}: {r.status_code if r else 'ERR'}", flush=True); pause(); continue
            ls = [u for u in dict.fromkeys(re.findall(r'https://www\.ikea\.com/us/en/p/[a-z0-9-]+/', r.text)) if not re.search(BAD, u) and u not in seen]
            urls.setdefault(cat, []).extend(ls); seen.update(ls); urls.setdefault("_done", []).append(slug)
            json.dump(urls, open(URLS, "w")); print(f"[cat] {cat:13s} {slug}: +{len(ls)} new links", flush=True); pause()
    out = json.load(open(OUT)) if OUT.exists() else {"items": []}; fails = []
    # backfill pass for items from the earlier run (no image/style_tags/local assets)
    for p in out["items"]:
        if out_of_time(): break
        if "style_tags" not in p or not p.get("image") or "image_local" not in p or ("model_glb" not in p and p.get("model_glb_url")):
            q = product(p["product_url"], p["category"]); pause()
            if q: 
                for k in ("image", "variants", "style_tags"): p[k] = q[k]
            assets(p, fails); save(out); print(f"[backfill] {p['id']} {p['name'][:30]}", flush=True)
    have = {i["product_url"] for i in out["items"]}
    cnt = lambda c: sum(1 for i in out["items"] if i["category"] == c)
    series_n = {}
    for i in out["items"]: series_n[(i["category"], i["name"].split()[0])] = series_n.get((i["category"], i["name"].split()[0]), 0) + 1
    ptr = {c: 0 for c in CATS}; tried = {c: 0 for c in CATS}
    # round-robin across categories so a time-box still leaves every category populated
    active = [c for c in CATS if cnt(c) < PER]
    while active and not out_of_time():
        for cat in list(active):
            if cnt(cat) >= PER or ptr[cat] >= len(urls.get(cat, [])): active.remove(cat); continue
            u = urls[cat][ptr[cat]]; ptr[cat] += 1
            if u in have: continue
            sk = u.split("/p/")[1].split("-")[0]
            if series_n.get((cat, sk.upper()), 0) >= 4: continue          # at most 4 colourways of one series, keeps variety
            p = product(u, cat); pause()
            if p and p.get("width_m") and cat in ("rug",) and not p.get("height_m"): p["height_m"] = 0.015; p["depth_m"] = p.get("depth_m") or p.get("length_m")
            if p and cat == "rug" and p.get("width_m") and not p.get("depth_m"): p["depth_m"] = p.get("length_m")
            if p and p.get("width_m") and p.get("height_m") and p.get("depth_m") and p.get("price_usd") is not None:
                if p["id"] in {i["id"] for i in out["items"]}: continue
                assets(p, fails); out["items"].append(p); have.add(u)
                k = (cat, p["name"].split()[0]); series_n[k] = series_n.get(k, 0) + 1
                save(out); print(f"[item {len(out['items'])}] {cat:13s} {p['name'][:34]:34s} {p['width_m']}x{p['depth_m']}x{p['height_m']} ${p['price_usd']} glb={'y' if p.get('model_glb') else 'n'} {p['style_tags']}", flush=True)
    json.dump(fails, open(HERE / "catalog_fails.json", "w"), indent=1)
    print(f"[catalog] {len(out['items'])} items, {len(fails)} asset failures -> {OUT}")

if __name__ == "__main__": main()
