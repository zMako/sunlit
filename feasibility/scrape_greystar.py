"""Greystar's own site (robots.txt allows everything but /api/*): SF properties with photos of actual empty units
(scene7 ids carry the room code: LIV/KIT/BED/BTH/DNG) and floor plan images (many with printed room dimensions).

    feasibility/.venv/bin/python feasibility/scrape_greystar.py [max_properties]

Writes feasibility/listings/gs-<id>/NN.jpg (interior photos only), plans/plan_NN.*, meta.json (same fields as the
Craigslist listings plus photo_codes / floorplans). Paced: 2-4 s per page, ~0.5 s per image. Re-runs skip done folders."""
import sys, re, json, time, random, pathlib, requests
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "listings"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
INTERIOR = {"LIV": "living", "KIT": "kitchen", "BED": "bedroom", "BTH": "bathroom", "DNG": "dining", "INT": "interior"}
MAXP = int(sys.argv[1]) if len(sys.argv) > 1 else 99
S = requests.Session(); S.headers.update(UA)

def get(url, **kw):
    for i in range(3):
        try:
            r = S.get(url, timeout=40, **kw)
            if r.status_code == 429: time.sleep(20 * (i + 1)); continue
            return r
        except requests.RequestException: time.sleep(3)
    return None

def sf_properties():
    pdp = get("https://www.greystar.com/sitemap-pdp.xml").text
    urls = {}
    for u in re.findall(r"<loc>(https://www\.greystar\.com/[^<]*san-francisco-ca/p_(\d+))</loc>", pdp): urls.setdefault(u[1], u[0])
    img = get("https://www.greystar.com/sitemap-pdp-images.xml").text
    images = {}
    for block in re.findall(r"<url>(.*?)</url>", img, re.S):
        m = re.search(r"/p_(\d+)</loc>", block)
        if m and m.group(1) in urls: images[m.group(1)] = re.findall(r"<image:loc>([^<]+)</image:loc>", block)
    return urls, images

def scrape(pid, url, imgs):
    d = OUT / f"gs-{pid}"
    if (d / "meta.json").exists(): print(f"[gs] {pid} done already"); return
    r = get(url)
    if not r or r.status_code != 200: print(f"[gs] {pid} page {r.status_code if r else 'ERR'}"); return
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S)
    ld = json.loads(m.group(1)) if m else {}
    addr = ld.get("address", {}); plans = ld.get("containsPlace", [])
    body = ""
    md = re.search(r'"description\\":{\\"value\\":\\"(.*?)\\"}', r.text)
    if md: body = md.group(1).encode().decode("unicode_escape", "ignore"); body = re.sub(r"<[^>]+>", " ", body)[:3000]
    interior = [(u, re.search(r"greystarprod/\d+-?([A-Z]+)(\d*)$", u)) for u in imgs]
    interior = [(u, mm.group(1), mm.group(2)) for u, mm in interior if mm and mm.group(1) in INTERIOR]
    d.mkdir(parents=True, exist_ok=True); (d / "plans").mkdir(exist_ok=True)
    codes = []; n = 0
    for u, code, idx in interior[:40]:
        rr = get(u + "?wid=1600&fmt=jpeg&qlt=90")
        if rr and rr.ok and len(rr.content) > 20000:
            (d / f"{n:02d}.jpg").write_bytes(rr.content); codes.append({"i": n, "code": code + idx, "room_hint": INTERIOR[code]}); n += 1
        time.sleep(random.uniform(0.3, 0.7))
    for u in imgs:
        if re.search(r"greystarprod/\d+-?PL\d*$", u) or "floorplan" in u.lower(): plans.append({"image": u + ("?wid=2000&fmt=png-alpha" if "scene7" in u else ""), "name": u.rsplit("/", 1)[-1], "source": "scene7"})
    fps = []
    for k, p in enumerate(plans):
        u = p.get("image")
        if not u: continue
        rr = get(u)
        if rr and rr.ok and len(rr.content) > 5000:
            ext = ".png" if "png" in rr.headers.get("Content-Type", "") else ".jpg"; f = f"plan_{k:02d}{ext}"
            (d / "plans" / f).write_bytes(rr.content)
            fps.append({"file": f"plans/{f}", "name": p.get("name"), "bedrooms": p.get("numberOfBedrooms"), "bathrooms": p.get("numberOfBathroomsTotal"), "id": p.get("identifier")})
        time.sleep(random.uniform(0.3, 0.7))
    meta = {"url": url, "source": "greystar", "title": ld.get("name", f"Greystar {pid}"), "address": f"{addr.get('streetAddress', '')}, {addr.get('addressLocality', '')} {addr.get('postalCode', '')}".strip(", "),
            "lat": ld.get("latitude"), "lon": ld.get("longitude"), "n_photos": n, "sqft_total": None, "bedrooms": None, "bathrooms": None, "body": body,
            "photo_codes": codes, "floorplans": fps, "note": "photos are of several units in the building; floorplans are the building's unit types"}
    json.dump(meta, open(d / "meta.json", "w"), indent=1)
    print(f"[gs] {pid} {meta['title'][:34]:34s} photos {n:2d} ({', '.join(sorted(set(c['code'][:3] for c in codes)))}) plans {len(fps)}")

if __name__ == "__main__":
    urls, images = sf_properties(); print(f"[gs] {len(urls)} SF properties, {sum(len(v) for v in images.values())} images in sitemap")
    for pid, url in list(urls.items())[:MAXP]:
        scrape(pid, url, images.get(pid, [])); time.sleep(random.uniform(2, 4))
    print("[gs] done")
