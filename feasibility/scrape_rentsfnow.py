"""RentSFNow (Veritas's own SF leasing site; robots.txt allows everything, sitemap lists every unit page): one page per
vacant unit with 10-20 photos OF THAT UNIT (image names carry the address and unit number), square footage, beds/baths.
Virtually staged photos are watermarked ('staged' / '-wm' in the name) and skipped.

    feasibility/.venv/bin/python feasibility/scrape_rentsfnow.py [since=2026-08-01] [max]

Writes feasibility/listings/rsn-<slug>/NN.jpg + meta.json (source rentsfnow, sqft_total). Paced 2-4 s per page; resumable."""
import sys, re, json, time, random, pathlib, html, requests
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "listings"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"; MAXN = int(sys.argv[2]) if len(sys.argv) > 2 else 999
S = requests.Session(); S.headers.update(UA)

def get(url):
    for i in range(3):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 429: time.sleep(20 * (i + 1)); continue
            return r
        except requests.RequestException: time.sleep(3)
    return None

def unit_urls():
    idx = get("https://www.rentsfnow.com/sitemap.xml").text; out = []
    for sm in re.findall(r"<loc>(https://www\.rentsfnow\.com/property-sitemap\d*\.xml)</loc>", idx):
        x = get(sm).text
        for loc, lm in re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", x):
            if lm >= SINCE and "/apartments/rental/" in loc: out.append((lm[:10], loc.rstrip("/")))
        time.sleep(1)
    return [u for _, u in sorted(out, reverse=True)]

def text(h): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S | re.I)).replace("<", " <")).strip()

def scrape(url):
    slug = url.rsplit("/", 1)[-1]; d = OUT / f"rsn-{slug}"
    if (d / "meta.json").exists(): return "done"
    r = get(url)
    if not r or r.status_code != 200: return f"http {r.status_code if r else 'ERR'}"
    h = r.text; addr_slug, unit = slug.rsplit("-", 1)
    imgs = list(dict.fromkeys(re.findall(r'https?://cdn\.rentcafe\.com/[^"\' ]+\.(?:jpg|jpeg|png)', h)))
    own = [i for i in imgs if re.search(rf"unit[-_]?{re.escape(unit)}[-_.(]", i, re.I)]
    own = [i for i in own if "staged" not in i.lower() and "-wm" not in i.lower() and "floorplan" not in i.lower()]
    if len(own) < 6: return f"only {len(own)} unstaged photos"
    tt = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S | re.I); tt = html.unescape(re.sub(r"<[^>]+>", "\n", tt))
    lines = [l.strip() for l in tt.split("\n") if l.strip()]
    title = html.unescape((re.search(r"<title>(.*?)</title>", h, re.S) or [None, slug])[1]).split("–")[0].split("&#8211;")[0].strip()
    beds = baths = sqft = price = None; headline = None
    for i, l in enumerate(lines):
        m = re.match(r"^(\d(?:\.\d)?) +Baths?$", l)
        if m and baths is None and i > 0:
            baths = float(m.group(1)); b = lines[i - 1]
            beds = 0 if b.lower().startswith("studio") else (int(b[0]) if re.match(r"^\d Bed", b) else None)
        m = re.match(r"^([\d,]{3,5}) sq\.? ?ft$", l, re.I)
        if m and sqft is None: sqft = int(m.group(1).replace(",", ""))
        m = re.match(r"^\$([\d,]+)$", l)
        if m and price is None: price = int(m.group(1).replace(",", ""))
        if sqft is not None and headline is None and i > 2 and 15 < len(l) < 140 and not l.startswith("$") and "sqft" not in l.lower() and "Bath" not in l: headline = l
    desc = next((l for l in lines if len(l) > 200 and "cookie" not in l.lower() and "{" not in l), "")
    neighborhood = lines[47] if len(lines) > 47 and len(lines[47]) < 40 else None
    address = f"{addr_slug.replace('-', ' ').title()} #{unit}, San Francisco, CA"
    d.mkdir(parents=True, exist_ok=True); n = 0
    for u in own[:30]:
        rr = get(u)
        if rr and rr.ok and len(rr.content) > 20000: (d / f"{n:02d}.jpg").write_bytes(rr.content); n += 1
        time.sleep(random.uniform(0.3, 0.7))
    plans = [i for i in imgs if "floorplan" in i.lower() or "floor-plan" in i.lower()]
    if plans:
        (d / "plans").mkdir(exist_ok=True)
        for k, u in enumerate(plans[:4]):
            rr = get(u)
            if rr and rr.ok: (d / "plans" / f"plan_{k:02d}.jpg").write_bytes(rr.content)
    meta = {"url": url, "source": "rentsfnow", "title": f"{title}: {headline}" if headline else title, "address": address, "lat": None, "lon": None, "n_photos": n,
            "sqft_total": sqft, "bedrooms": beds, "bathrooms": baths, "price_usd": price, "neighborhood": neighborhood, "body": desc[:2500], "unit": unit, "n_staged_skipped": len([i for i in imgs if "staged" in i.lower()]),
            "floorplans": [{"file": f"plans/plan_{k:02d}.jpg"} for k in range(min(len(plans), 4))]}
    json.dump(meta, open(d / "meta.json", "w"), indent=1)
    return f"photos {n} sqft {meta['sqft_total']} beds {meta['bedrooms']} | {title[:40]}"

if __name__ == "__main__":
    urls = unit_urls(); print(f"[rsn] {len(urls)} unit pages since {SINCE}")
    for u in urls[:MAXN]:
        res = scrape(u); print(f"[rsn] {u.rsplit('/', 1)[-1]:28s} {res}", flush=True)
        if res != "done": time.sleep(random.uniform(2, 4))
    print("[rsn] done")
