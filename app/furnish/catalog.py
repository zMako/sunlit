"""Furniture catalogue of FACTS from IKEA US product pages: name, type, article, price, outer dimensions (metres), product
URL, and the URLs of the product image and of IKEA's own GLB model. Nothing is downloaded or re-hosted: the viewer shows our
own dimensioned boxes and links to the product page; loading IKEA's image/model URLs client-side is a switch left to the user
(IKEA's terms restrict copying and embedding their materials). Category pages are allowed by robots.txt (search/filter URLs
are not and are never used). Paced 3-5 s per page, ~8 products per category.

    feasibility/.venv/bin/python app/furnish/catalog.py [per_category=8]   -> app/furnish/catalog.json"""
import sys, re, json, time, random, pathlib, html, requests
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "catalog.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36", "Accept-Language": "en-US"}
S = requests.Session(); S.headers.update(UA)
PER = int(sys.argv[1]) if len(sys.argv) > 1 else 8
# category slug fragment -> our category
CATS = {"bed-frames-16284": "bed", "sofas-fu003": "sofa", "armchairs-chaises-fu006": "armchair", "coffee-tables-10705": "coffee_table", "dining-tables-21825": "dining_table",
        "dining-chairs-25219": "dining_chair", "desks-computer-desks-20649": "desk", "desk-chairs-20652": "desk_chair", "armoires-wardrobes-19053": "wardrobe",
        "bookcases-shelving-units-st002": "bookcase", "dressers-storage-drawers-st004": "dresser", "nightstands-20656": "nightstand", "rugs-10653": "rug",
        "floor-lamps-10731": "floor_lamp", "tv-media-furniture-10475": "tv_bench"}
FRAC = {"½": .5, "¼": .25, "¾": .75, "⅛": .125, "⅜": .375, "⅝": .625, "⅞": .875}

def get(url):
    for i in range(3):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 429: time.sleep(30 * (i + 1)); continue
            return r
        except requests.RequestException: time.sleep(4)
    return None

def inches_to_m(txt):
    """'66 1/8 "' or '82 ⅝"' or '30 ½ "' -> metres"""
    if not txt: return None
    t = html.unescape(txt).replace("″", '"').replace("′", "'").strip()
    ft = re.match(r"\s*(\d+)\s*'\s*(\d+)?\s*(?:(\d)/(\d))?\s*\"?\s*$", t)   # rugs: 5 ' 3 "  (feet and inches)
    if ft:
        v = int(ft.group(1)) * 12 + (int(ft.group(2)) if ft.group(2) else 0) + (int(ft.group(3)) / int(ft.group(4)) if ft.group(3) else 0)
        return round(v * 0.0254, 3)
    t = t.replace('"', "")
    m = re.match(r"(\d+)(?:\s+(\d)/(\d))?\s*([½¼¾⅛⅜⅝⅞])?", t)
    if not m: return None
    v = int(m.group(1)) + (int(m.group(2)) / int(m.group(3)) if m.group(2) else 0) + (FRAC.get(m.group(4), 0) if m.group(4) else 0)
    return round(v * 0.0254, 3)

def ld_blocks(h): return re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S)

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
                P = {"name": html.unescape(str(j.get("name") or "")), "sku": j.get("sku"), "image": img if isinstance(img, str) else None,
                     "width_m": inches_to_m(j.get("width")), "depth_m": inches_to_m(j.get("depth")) or inches_to_m(j.get("length")), "height_m": inches_to_m(j.get("height")), "length_m": inches_to_m(j.get("length")),
                     "price_usd": float(off.get("price")) if isinstance(off, dict) and off.get("price") not in (None, "") else None, "description": html.unescape(str(j.get("description") or ""))[:300], "color": j.get("color")}
        if "3DModel" in l:
            m = re.search(r'"contentUrl"\s*:\s*"([^"]+\.glb[^"]*)"', l); glb = m.group(1) if m else glb
    if not P: return None
    tn = re.search(r'"typeName"\s*:\s*"([^"]+)"', h); P["type_name"] = tn.group(1) if tn else None
    ms = re.search(r'"itemMeasureReferenceText"\s*:\s*"([^"]*)"', h); P["size_label"] = ms.group(1) if ms else None
    P.update({"id": "ikea-" + (P["sku"] or url.rstrip("/").rsplit("-", 1)[-1]).replace(".", ""), "category": cat, "product_url": url, "model_glb_url": glb, "source": "ikea.com/us product page", "fetched": time.strftime("%Y-%m-%d")})
    return P

def main():
    cat_items = {}
    for slug, cat in CATS.items():
        r = get(f"https://www.ikea.com/us/en/cat/{slug}/")
        if not r or r.status_code != 200: print(f"[cat] {slug}: {r.status_code if r else 'ERR'}"); continue
        urls = [u for u in dict.fromkeys(re.findall(r'https://www\.ikea\.com/us/en/p/[a-z0-9-]+/', r.text)) if not re.search(r"mattress|slatted|pillow|duvet|sheet|cover|protector|topper|leg-|legs-|cushion", u)]
        cat_items[cat] = urls; print(f"[cat] {slug}: {len(urls)} product links", flush=True); time.sleep(random.uniform(3, 5))
    out = json.load(open(OUT)) if OUT.exists() else {"items": []}; have = {i["product_url"] for i in out["items"]}
    for cat, urls in cat_items.items():
        n = 0
        for u in urls:
            if n >= PER: break
            if u in have: n += 1; continue
            p = product(u, cat)
            if p and p.get("width_m") and cat == "rug" and not p.get("height_m"): p["height_m"] = 0.015; p["depth_m"] = p.get("depth_m") or p.get("length_m")
            if p and p.get("width_m") and p.get("height_m") and p.get("depth_m"):
                out["items"].append(p); n += 1; print(f"[item] {cat:13s} {p['name']:12s} {p.get('type_name') or '':28s} {p['width_m']}x{p['depth_m']}x{p['height_m']} m ${p['price_usd']} glb={'y' if p['model_glb_url'] else 'n'}", flush=True)
                json.dump(out, open(OUT, "w"), indent=1)
            time.sleep(random.uniform(3, 5))
    print(f"[catalog] {len(out['items'])} items -> {OUT}")

if __name__ == "__main__": main()
