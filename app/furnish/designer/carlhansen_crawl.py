"""Carl Hansen & Son: crawl en-market product pages (cached), list products with downloadable 3D zips. Resumable."""
import sys, re, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); from common import *
B = "carlhansen"; R = H / "raw" / B
def urls():
    t = get("https://admincms.carlhansen.com/sitemap.xml", cache=cpath(B, "sitemap", "xml")).text
    u = re.findall(r"<loc>([^<]*)", t)
    return sorted({x for x in u if "/en/en/collection/" in x and "/variant/" not in x and x.count("/") >= 7 and "/shop-accessories" not in x})
def page(u, mk="en/en"):
    r = get(u, cache=cpath(B, u))
    if not r: return None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.S)
    return json.loads(m.group(1))["props"]["pageProps"] if m else None
if __name__ == "__main__":
    us = urls(); print(len(us)); out = []
    for i, u in enumerate(us):
        p = page(u)
        if not p: continue
        pd = p["pageData"]
        if pd.get("Kind") != "ProductPageModel": continue
        assets = [(a["Description"], a["Link"]["Url"]) for a in (pd.get("Specs") or {}).get("OtherAssets") or []]
        out.append({"url": u, "name": pd["ProductName"], "assets": assets})
        if i % 50 == 0: print(i, len(out), flush=True)
    json.dump(out, open(R / "products.json", "w"), indent=1)
    print(len(out), sum(1 for o in out if any("3d" in a[0].lower() for a in o["assets"])))
