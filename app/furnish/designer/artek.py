"""Artek: public product pages on www.artek.fi list per-product FBX/DAE/SKP zips under 'Downloads' (no login). Prices from Artek's Shopify shop (shop.artek.fi products.json)."""
import sys; sys.path.insert(0, "/Users/maciejkopiec/sunlit/app/furnish/designer")
from common import *
import zipfile, html as _html
from bs4 import BeautifulSoup
BR = "Artek"; B = "artek"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
SITE = "https://www.artek.fi"

def product_urls():
    r = get(f"{SITE}/en/sitemaps-1-section-products-1-sitemap.xml", cache=cpath(B, "sm", "xml"))
    return re.findall(r"<loc>([^<]+)</loc>", r.text)

def shop_products():
    out = []; pg = 1
    while True:
        c = cpath(B, f"shop{pg}", "json"); r = get(f"https://shop.artek.fi/products.json?limit=250&page={pg}", cache=c)
        if not r:
            time.sleep(60); r = get(f"https://shop.artek.fi/products.json?limit=250&page={pg}", cache=c)
        if not r: break
        ps = r.json()["products"]
        if not ps: break
        out += ps; pg += 1
    return out

def parse(url, txt):
    s = BeautifulSoup(txt, "html.parser"); d = {"url": url}
    h1 = s.find("h1"); d["name"] = h1.get_text(" ", strip=True) if h1 else None
    metas = [p.get_text(" ", strip=True) for p in s.select(".m-header-product-alternative__meta-text")]
    d["designer_year"] = metas[0] if metas else None
    a = s.select_one(".m-header-product-alternative__cta"); d["shop_url"] = a["href"] if a else None
    og = s.find("meta", property="og:image"); d["image"] = og["content"] if og else None
    desc = [p.get_text(" ", strip=True) for p in s.select("main p")]; d["desc"] = " ".join(x for x in desc if len(x) > 60)[:600]
    kv = {}
    for it in s.select(".m-key-value-table__list-item"):
        t = it.find("dt"); v = it.find("dd")
        if t and v and t.get_text(strip=True): kv[t.get_text(" ", strip=True).rstrip(":")] = v.get_text(" ", strip=True)
    d["kv"] = kv
    d["manu"] = [p.get_text(" ", strip=True) for p in s.select(".m-key-value-table__manufacturer-info")]
    nums = []
    for g in s.select(".m-key-value-table__svg-wrap [id^=number_]"):
        m = re.match(r"number_(.*?)__x7C__", g["id"])
        if m:
            n = re.match(r"(\d+(?:_\d+)?)", m.group(1))
            if n: nums.append(float(n.group(1).replace("_", ".")))
    d["dim_nums_cm"] = nums
    d["downloads"] = sorted(set(re.findall(r'href="(/downloads/[^"]+\.(?:zip|rfa|ifc))"', txt)))
    return d

def main(limit=None):
    urls = product_urls(); print(len(urls), "products", flush=True)
    pages = {}
    for i, u in enumerate(urls):
        r = get(u, cache=cpath(B, u))
        if r: pages[u] = parse(u, r.text)
        if i % 25 == 0: print("page", i, flush=True)
    json.dump(pages, open(R / "pages.json", "w"), indent=1)
    shop = {p["handle"]: p for p in shop_products()}; json.dump(list(shop.values()), open(R / "shop.json", "w"))
    print("shop products", len(shop), flush=True)
    items = []; rep = {"formats": {}, "listed": len(pages), "found3d": 0, "conv": 0, "mismatch": 0, "price": 0, "bo": 0, "bp": 0}; notes = []
    t0 = time.time()
    for u, d in pages.items():
        mesh = [x for x in d["downloads"] if re.search(r"_(fbx|dae)-\d+\.zip$", x)]
        if not mesh: continue
        mesh.sort(key=lambda x: (0 if "_fbx-" in x else 1))
        rep["found3d"] += 1
        name = d["name"]; sl = u.rstrip("/").split("/")[-1]
        pid = f"dsg-artek-{slug(sl)}"
        zp = R / "files" / mesh[0].split("/")[-1]
        if not zp.exists():
            r = get(SITE + mesh[0], binary=True)
            if not r: notes.append(f"download failed {sl}"); continue
            zp.write_bytes(r.content)
        xd = R / "files" / zp.stem
        if not xd.exists():
            xd.mkdir(); 
            try:
                with zipfile.ZipFile(zp) as z:
                    for n in z.namelist():
                        if ".." in n or n.startswith("/"): continue
                        z.extract(n, xd)
            except Exception as e: notes.append(f"bad zip {sl}"); continue
        cands = [p for p in xd.rglob("*") if p.suffix.lower() in (".fbx", ".dae") and "__MACOSX" not in str(p)]
        if not cands: notes.append(f"no mesh in zip {sl}"); continue
        cands.sort(key=lambda p: -p.stat().st_size); raw = cands[0]
        if raw.stat().st_size > 300e6: continue
        ext = raw.suffix.lower().lstrip("."); rep["formats"][ext] = rep["formats"].get(ext, 0) + 1
        info = process_model(pid, raw, None)
        if not info: notes.append(f"convert failed {sl}"); continue
        dm = info["dims"]  # (w,d,h) m
        nums = d["dim_nums_cm"]
        if nums:
            mx = max(nums) / 100; bx = max(dm)
            if abs(math.log(bx / mx)) > math.log(1.35):
                rep["mismatch"] += 1; notes.append(f"dim mismatch {sl}: listed max {mx} model {dm}")
                for q in (H / "models" / f"{pid}.glb", H / "models" / f"{pid}.json", H / "models_opt" / f"{pid}.glb"): q.unlink(missing_ok=True)
                continue
        rep["conv"] += 1; rep["bo"] += info["model_bytes_orig"]; rep["bp"] += info["model_bytes"]
        des, yr = None, None
        if d["designer_year"]:
            m = re.match(r"(.*?),\s*(\d{4})", d["designer_year"])
            if m: des, yr = m.group(1), int(m.group(2))
            else: des = d["designer_year"]
        kv = d["kv"]; mats = "; ".join(f"{k}: {v}" for k, v in kv.items())[:300] or None
        sh = shop.get(sl) or (shop.get(d["shop_url"].rstrip("/").split("/")[-1]) if d["shop_url"] else None)
        price = cur = None; buy = d["shop_url"] or u
        if sh:
            try: price = min(float(v["price"]) for v in sh["variants"] if v.get("available", True) or True)
            except Exception: pass
            if price: cur = "EUR"; buy = f"https://shop.artek.fi/products/{sh['handle']}"; rep["price"] += 1
        img = None
        if d["image"]: img = save_image(d["image"] if d["image"].startswith("http") else SITE + d["image"], pid + ".jpg", BR)
        cat = categorize(name, sl)
        it = make_item(BR, name, designer=des, category=cat, w=None, d=None, h=None, price=price, currency=cur, price_source="Artek shop EUR" if price else None,
                       product_url=u, buy_url=buy, image=img, model=info, description=d["desc"], materials=mats, colours=None, year=yr, source_formats=[ext], pid=pid,
                       extra={"listed_dims_m": {"numbers_cm": nums}, "model_formats": [ext]})
        items.append(it)
        if len(items) % 5 == 0: save_items(BR, items)
    save_items(BR, items)
    rep = {"brand": BR, "products_listed": rep["listed"], "with_3d_found": rep["found3d"], "models_converted": rep["conv"], "items": len(items), "formats_found": rep["formats"],
           "price_coverage": rep["price"], "how_3d_exposed": "Public per-product Downloads accordion on artek.fi product pages: <Product>_fbx-<id>.zip and _dae zips (also skp, 3D dxf, rfa, ifc), no login",
           "walled": False, "login_gated": False, "notes": "; ".join(notes)[:3000], "dim_mismatches": rep["mismatch"], "bytes_orig": rep["bo"], "bytes_opt": rep["bp"], "minutes": round((time.time() - t0) / 60, 1)}
    json.dump(rep, open(R.parent / "report_artek.json", "w"), indent=1); print(rep)
if __name__ == "__main__": main()
