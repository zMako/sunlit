"""Flos: 3D zips linked on the public professional.flos.com planning-aids page (no login), shop data from flos.com/en/us (USD)."""
import sys, re, json, html, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
B = "Flos"; R = H / "raw/flos"; EX = R / "ex"; t0 = time.time()
S = "https://flos.com/en/us/"
# (name, extracted dir, mesh stem filter, shop url, category, price?)
P = [
 ("Arco", "Arco-3D", "Arco.obj", "arco/M-arco.html", "floor_lamp", False),
 ("Arco Led", "Arco-Led-3D", "Arco LED.obj", "arco/M-arco.html", "floor_lamp", True),
 ("Aim Small", "Aim-Small-3D", "Aim_Small.obj", "aim/M-aim-us.html", "pendant_lamp", True),
 ("Aim Small Plug-in", "Aim-Small-Cable-Plug-3D", "Aim_Small_Switch.obj", "aim-plug-in/M-aim-cable-plug.html", "pendant_lamp", True),
 ("Ariette 1", "Ariette-3D", "Ariette 1.obj", "ariette/M-ariette.html", "pendant_lamp", True),
 ("Almendra Linear Suspension 4", "ALMENDRA_LINEAR_FAMILY_3D_DRAWING/Almendra-Linear-S4-3D", "Almendra-Linear-S4-3D.obj", "almendra-linear-suspension-4-nude-white-canopy-s4/FU042226.html", "pendant_lamp", True),
 ("Almendra Linear Suspension 3", "ALMENDRA_LINEAR_FAMILY_3D_DRAWING/Almendra-Linear-S3-3D", "Almendra-Linear-S3-3D.obj", "almendra-linear-suspension-3-primer-nude-primer-canopy-s3/FU039126.html", "pendant_lamp", True),
 ("Almendra Organic Suspension Short 3", "ALMENDRA_ORGANIC_FAMILY_3D_DRAWING/Almendra-Organic-Y-S3-Short-3D", "Almendra-Organic-Y-S3-Short-3D.obj", "almendra-organic-suspension-short-3-primer-nude-primer-canopy-s3/FU039826.html", "pendant_lamp", True),
]
def txt(t):
    x = re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S); x = re.sub(r'<[^>]+>', '|', x); return html.unescape(re.sub(r'[\s|]+', ' ', x))
items = []; rep = {"dim_mismatches": 0, "rejected": []}; fmts = {}
for name, d, mesh, url, cat, wantprice in P:
    full = S + url; r = get(full, cache=cpath("flos", full))
    f = next(iter((EX / d).rglob(mesh)), None) if (EX / d).exists() else None
    if not r or not f: print("skip", name, bool(r), f); continue
    t = r.text; ld = None
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
        try: j = json.loads(m)
        except Exception: continue
        if j.get("@type") == "Product": ld = j; break
    x = txt(t); dm = re.search(r'Designed by (.*?) , (\d{4})', x); dim = re.search(r'Dimensions (?:Dimensions )*(.*?) (?:Main features|Cord)', x)
    dims = {k: float(v) * 0.0254 for k, v in re.findall(r'(Width|Length|Height|Diameter) \(in\) ([\d.]+)', dim.group(1))} if dim else {}
    w = dims.get("Width") or dims.get("Diameter"); dd = dims.get("Length") or dims.get("Diameter"); h = dims.get("Height")
    pid = f"dsg-flos-{slug(name)}"
    pend = cat == 'pendant_lamp'
    info = process_model(pid, f, listed=(w, dd, None) if pend else (w, dd, h))
    if not info: print("model fail", name); rep["rejected"].append((name, "parse")); continue
    bb = info["dims"]; bad = False
    for a, b in ((sorted(bb[:2]), sorted([w or 0, dd or 0])),):
        pass
    L = sorted([x_ for x_ in (w, dd) if x_]); M = sorted(bb[:2])
    chk = ([(bb[2], h)] if not pend else []) + ([(M[1], L[-1])] if L else [])
    if (pend and h and bb[2] < 0.65 * h) or any(b and abs(a / b - 1) > 0.35 for a, b in chk):
        rep["dim_mismatches"] += 1; rep["rejected"].append((name, f"bbox {bb} vs listed {[w, dd, h]}")); print("MISMATCH", name, bb, w, dd, h)
        for p_ in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb", H / "models" / f"{pid}.json"): p_.unlink(missing_ok=True)
        continue
    img = None
    if ld and ld.get("image"):
        im = ld["image"] if isinstance(ld["image"], str) else ld["image"][0]; img = save_image(im, pid + ".jpg", B)
    price = float(ld["offers"]["price"]) if (wantprice and ld and ld.get("offers", {}).get("price")) else None
    desc = (ld or {}).get("description", ""); mat = (ld or {}).get("material"); col = (ld or {}).get("color")
    items.append(make_item(B, name, designer=html.unescape(dm.group(1)).strip() if dm else None, category=cat, w=w, d=dd, h=h, price=price, currency="USD" if price else None,
        price_source="Flos shop USD" if price else None, product_url=full, buy_url=full, image=img, model=info, description=desc, materials=mat, colours=col,
        year=int(dm.group(2)) if dm else None, source_formats=["obj", "3ds", "fbx", "3dm"], pid=pid, extra={"listed_dims_m": {"w": w, "d": dd, "h": h}, "model_formats": ["obj"]}))
    fmts["obj"] = fmts.get("obj", 0) + 1; save_items(B, items); print("ok", name, bb, w, dd, h, price, flush=True)
json.dump({"brand": B, "products_listed": 355, "with_3d_found": len(P), "models_converted": len(items), "items": len(items), "formats_found": {"3ds": 15, "obj": 15, "fbx": 15, "3dm": 10},
  "price_coverage": sum(1 for i in items if i["price_orig"]), "how_3d_exposed": "professional.flos.com/en/global/product-downloads/planning-aids/ lists 355 '2D/3D files' zips (public, no login; contentful downloads.ctfassets.net). Only the 24 server-rendered cards (15 with 3D zips) were fetched; the remaining pages load via the site's Algolia search from the browser and were not queried.",
  "walled": False, "login_gated": False, "notes": json.dumps(rep["rejected"]), "dim_mismatches": rep["dim_mismatches"],
  "bytes_orig": sum(i.get("model_bytes_orig") or 0 for i in items), "bytes_opt": sum(i.get("model_bytes") or 0 for i in items), "minutes": round((time.time() - t0) / 60, 1)}, open(R / "report_flos.json", "w"), indent=1)
