"""Tom Dixon: per-product 'Downloads - CAD' links (public, Shopify CDN) -> STL meshes (or STL inside zip); STEP/DWG-only skipped. Prices GBP from product page JSON-LD."""
import sys, re, json, html, pathlib, time, zipfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
B = "Tom Dixon"; R = H / "raw/tomdixon"; F = R / "files"; EX = R / "ex"; t0 = time.time()
inv = json.load(open("/tmp/w_E/td_inv.json")) if pathlib.Path("/tmp/w_E/td_inv.json").exists() else json.load(open(R / "inventory.json"))
json.dump(inv, open(R / "inventory.json", "w"), indent=1)
def cat_of(name, url):
    n = name.lower()
    if re.search(r"vessel|grinder|candelabra", n): return "other"
    if re.search(r"wall|surface", n): return "other"
    if re.search(r"floor", n) and re.search(r"light|lamp|chandelier", n): return "floor_lamp"
    if re.search(r"table light|table lamp|portable", n): return "table_lamp"
    if re.search(r"pendant|chandelier", n): return "pendant_lamp"
    if "/lighting/" in url: return "other"
    if "/coffee" in url: return "coffee_table"
    if "/side-tables/" in url: return "side_table"
    return categorize(name)
items = []; rej = []; fm = {}
for fu, pages in inv.items():
    fn = pathlib.Path(fu.split("/")[-1]); mesh = F / fn
    if not mesh.exists(): continue
    if mesh.suffix.lower() == ".zip":
        d = EX / mesh.stem
        if not d.exists():
            d.mkdir(parents=True)
            with zipfile.ZipFile(mesh) as z:
                for i in z.infolist():
                    if i.filename.lower().endswith(".stl") and "/" not in i.filename.strip("/"): z.extract(i, d)
        c = [p for p in d.iterdir() if p.suffix.lower() == ".stl"]
        if not c: rej.append((fn.name, "zip has no stl")); continue
        mesh = c[0]
    url = pages[0]; r = get(url, cache=cpath("tomdixon", url))
    if not r: continue
    t = r.text; ld = None
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
        try: j = json.loads(m)
        except Exception: continue
        if j.get("@type") == "Product": ld = j; break
    sp = dict(re.findall(r'title:"([^"]{1,40})",content:"([^"]{0,200})"', t))
    name = html.unescape((ld or {}).get("name", fn.stem)).split("|")[0].strip()
    def cm(*ks):
        for k in ks:
            try: return float(sp[k]) / 100
            except Exception: pass
    dia = cm("Diameter (cm)", "Max Diameter (cm)"); w = cm("Width (cm)") or dia; dd = cm("Length (cm)", "Depth (cm)") or dia; h = cm("Height (cm)", "Overall Height (cm)", "Max Height (cm)")
    cat = cat_of(name, url); pend = cat == "pendant_lamp"
    pid = f"dsg-tom-dixon-{slug(name)}"
    info = process_model(pid, mesh, listed=(w, dd, None) if pend else (w, dd, h))
    if not info: rej.append((name, "parse")); continue
    bb = info["dims"]; L = sorted(x for x in (w, dd) if x); M = sorted(bb[:2])
    chk = ([(bb[2], h)] if (h and not pend) else []) + ([(M[1], L[-1])] if L else [])
    if (pend and h and bb[2] < 0.65 * h) or any(abs(a / b - 1) > 0.35 for a, b in chk):
        rej.append((name, f"bbox {bb} vs listed {[w, dd, h]}"))
        for p_ in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb", H / "models" / f"{pid}.json"): p_.unlink(missing_ok=True)
        print("MISMATCH", name, bb, w, dd, h); continue
    img = None
    if ld and ld.get("image"):
        im = ld["image"] if isinstance(ld["image"], str) else ld["image"][0]; img = save_image(im, pid + ".jpg", B)
    price = None; cur = None
    try: price = float(ld["offers"]["price"]); cur = ld["offers"]["priceCurrency"]
    except Exception: pass
    clean = "https://" + url.split("//")[1]
    ext = mesh.suffix.lower().strip(".")
    items.append(make_item(B, name, designer="Tom Dixon", category=cat, w=w, d=dd, h=h, price=price, currency=cur, price_source=f"Tom Dixon shop {cur}" if price else None,
        product_url=clean, buy_url=clean, image=img, model=info, description=(ld or {}).get("description", ""), materials=sp.get("Material"), colours=None,
        year=int(sp["Year of Design"]) if sp.get("Year of Design", "").isdigit() else None, source_formats=[ext], pid=pid,
        extra={"listed_dims_m": {"w": w, "d": dd, "h": h}, "model_formats": [ext], "variants_sharing_model": len(pages)}))
    fm[ext] = fm.get(ext, 0) + 1; save_items(B, items); print("ok", cat, name, bb, [w, dd, h], price, flush=True)
json.dump({"brand": B, "products_listed": 1511, "with_3d_found": len(inv), "models_converted": len(items), "items": len(items), "formats_found": {"stl": 26, "step/stp": "~170 pages", "dwg": "~190 pages"},
  "price_coverage": sum(1 for i in items if i["price_orig"]), "how_3d_exposed": "sitemap.xml lists 1511 product urls; each product page embeds 'Downloads - CAD' (STEP/STP mostly, STL for ~26 distinct families, a few zips containing STL/STEP) as Shopify CDN links; no login. One mesh shared by many colour variants; one item per mesh.",
  "walled": False, "login_gated": False, "notes": json.dumps(rej), "dim_mismatches": sum(1 for r_ in rej if "bbox" in r_[1]),
  "bytes_orig": sum(i.get("model_bytes_orig") or 0 for i in items), "bytes_opt": sum(i.get("model_bytes") or 0 for i in items), "minutes": round((time.time() - t0) / 60, 1)}, open(R / "report_tomdixon.json", "w"), indent=1)
