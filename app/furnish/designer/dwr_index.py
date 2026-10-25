"""Design Within Reach product index (price source for brands without own shop). Crawls the public product sitemap pages (US), one request/1.5 s, resumable.
Writes raw/dwr_index.json: [{url,name,brand,price_usd(min),image,dims_text,breadcrumb}]. Other scripts: from dwr_index import lookup."""
import sys, re, json, html, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
OUT = H / "raw/dwr_index.json"
def build():
    urls = []
    for n in (0, 1):
        r = get(f"https://www.dwr.com/sitemap_{n}-product.xml", cache=H / f"raw/dwr/sitemap_{n}.xml")
        urls += [u for u in re.findall(r"<loc>([^<]+)</loc>", r.text) if "lang=en_US" in u]
    res = {x["url"]: x for x in json.load(open(OUT))} if OUT.exists() else {}
    print(len(urls), "products,", len(res), "done", flush=True)
    for k, u in enumerate(urls):
        if u in res: continue
        r = get(u)
        if not r: res[u] = None; continue
        t = r.text
        m = re.search(r'<div class="product-brand">\s*<a[^>]*>([^<]+)</a>', t); brand = html.unescape(m.group(1)).strip() if m else None
        m = re.search(r'<h1[^>]*>(.*?)</h1>', t, re.S); name = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None
        prices = [float(p) for p in re.findall(r'"priceCurrency":"USD","price":([\d.]+)', t)]
        im = re.search(r'<meta property=.og:image. content=.([^\'"]+)', t)
        dm = re.search(r'summary-pdp-dimensions-list">(.*?)</ul>', t, re.S)
        bc = re.findall(r'"name":"([^"]+)","item":"https://www.dwr.com/[a-z-]+\?lang', t)
        res[u] = {"url": u, "name": name, "brand": brand, "price_usd": min(prices) if prices else None, "image": im.group(1) if im else None,
                  "dims_text": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", dm.group(1)))).strip() if dm else None, "breadcrumb": bc}
        if k % 25 == 0:
            json.dump([v for v in res.values() if v], open(OUT, "w")); print(k, len(urls), flush=True)
    json.dump([v for v in res.values() if v], open(OUT, "w")); print("done")
def norm(s): return re.sub(r"[^a-z0-9 ]", "", (s or "").lower().replace("&", "and"))
def lookup(brand, name):
    """Best DWR match for (brand, product name): returns dict or None. Matches on brand + all name tokens contained."""
    idx = json.load(open(OUT)) if OUT.exists() else []
    nt = set(norm(name).split()); best = None
    for x in idx:
        if norm(brand) not in norm(x["brand"]) and norm(x["brand"]) not in norm(brand): continue
        xt = set(norm(x["name"]).split()); sc = len(nt & xt) / max(len(nt | xt), 1)
        if min(len(nt), len(xt)) >= 2 and (nt <= xt or xt <= nt): sc += 0.25
        if sc > 0.6 and len(nt & xt) >= max(1, min(len(nt), len(xt)) - 0) and (not best or sc > best[0]): best = (sc, x)
    return best[1] if best else None
if __name__ == "__main__": build()
