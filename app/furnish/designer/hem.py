import sys, pathlib, zipfile, re, json, html
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common_dl import *
B = "hem"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
ST = R / "state.json"
def sj(p, d=None):
    return json.load(open(p)) if pathlib.Path(p).exists() else d
# 1. product list
sm = get("https://hem.com/en-us/sitemap-0.xml", cache=R / "sitemap.xml").text
urls = [u for u in re.findall(r"<loc>([^<]+)", sm) if re.search(r"/(furniture|lighting|accessories|rugs)/.+/\d+$", u)]
print(len(urls), "sku pages", flush=True)
# designers
dmap = {}
dsm = [u for u in re.findall(r"<loc>([^<]+)", sm) if "/designers/" in u]
for u in dsm:
    r = get(u, cache=cpath(B, u))
    if not r: continue
    t = r.text; nm = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S)
    nm = html.unescape(re.sub(r"<[^>]+>", "", nm.group(1))).strip() if nm else u.rsplit("/", 1)[-1].replace("-", " ").title()
    for fam in set(re.findall(r'href="/en-us/(?:en-us/)?(?:furniture|lighting|accessories|rugs)/[^/"]+/([^/"]+)"', t)): dmap.setdefault(fam, []).append(nm)
def txt(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S); s = html.unescape(re.sub(r"<[^>]+>", "|", t)); return re.sub(r"\|+", "|", s)
def parse(u):
    r = get(u, cache=cpath(B, u))
    if not r: return None
    t = r.text; d = {"url": u}
    m = re.search(r'3d-files/([^"\\\s]+)', t); d["z3d"] = m.group(1) if m else None
    for m in re.finditer(r'application/ld\+json[^>]*>(.*?)</script>', t, re.S):
        try: j = json.loads(m.group(1))
        except Exception: continue
        if j.get("@type") == "Product":
            d["name"] = re.sub(r"\s*[—-]\s*Hem$", "", j["name"]); d["desc"] = j.get("description", ""); d["img"] = (j.get("image") or [None])[0]
            o = j.get("offers", {}); d["price"] = o.get("price"); d["cur"] = o.get("priceCurrency"); d["sku"] = j.get("sku")
    s = txt(t)
    dm = {}
    i = s.find("|Dimensions|")
    if i >= 0:
        seg = s[i + 12:i + 400]
        for k, v, un in re.findall(r"([A-Za-z ]+)\|([\d.]+) (in|cm|mm)\|", seg):
            f = 2.54 if un == "in" else 1 if un == "cm" else 0.1
            dm.setdefault(k.strip(), float(v) * f)
    d["dims_cm"] = dm
    mm = re.search(r"\|Inside material\|(.*?)\|Dimensions", s, re.S); d["inside"] = mm.group(1).strip()[:150] if mm else None
    ml = re.search(r"\|Legs material\|.*?\|Name\|([^|]+)", s); d["legs"] = ml.group(1) if ml else None
    mu = re.search(r"\|Upholstery material\|.*?\|Name\|([^|]+)\|Composition\|([^|]+)", s); d["uph"] = (mu.group(1) + ", " + mu.group(2)) if mu else None
    bc = re.findall(r'"name":"([^"]+)"\}\}', t); d["crumb"] = re.findall(r'"@id":"https://hem\.com/en-us/[^"]*?(?:furniture|lighting|accessories|rugs)/([^/"]+)(?:/([^/"]+))?', t)[:1]
    return d
pages = {}
for k, u in enumerate(urls):
    p = parse(u)
    if p: pages[u] = p
    if k % 100 == 0: print("parsed", k, flush=True)
json.dump(pages, open(R / "pages.json", "w"))
# 2. group by 3d file
groups = {}
for u, p in pages.items():
    if p.get("z3d"): groups.setdefault(p["z3d"], []).append(p)
print(len(groups), "distinct 3d zips,", sum(1 for p in pages.values() if p.get("z3d")), "pages with 3d", flush=True)
json.dump({k: [x["url"] for x in v] for k, v in groups.items()}, open(R / "groups.json", "w"), indent=1)
