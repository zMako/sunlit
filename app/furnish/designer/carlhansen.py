"""Carl Hansen & Son: public 3D zips (admincms.carlhansen.com/globalassets/...) listed in each product page's Specs.OtherAssets. Prices from de-de market (EUR). Run carlhansen_crawl.py first. Resumable."""
import sys, re, json, pathlib, zipfile, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); from common import *
import common, subprocess, parse3ds, carlhansen_crawl as cc
def _bc(src, dst):
    p = subprocess.run([common.BLENDER, "-b", "-noaudio", "-P", str(common.H / "blender_convert.py"), "--", str(src), str(dst)], capture_output=True, text=True, errors="replace", timeout=900)
    return p.returncode == 0 and pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 1000
common.blender_convert = _bc
B = "carlhansen"; R = H / "raw" / B; (R / "files").mkdir(exist_ok=True); BRAND = "Carl Hansen & Son"
PREF = [".glb", ".obj", ".fbx", ".3ds", ".dae"]
def extract(zp, out):
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and ".." not in n and not n.startswith("/")]
        for ext in PREF:
            c = [n for n in names if n.lower().endswith(ext)]
            if c:
                for n in names:
                    if n.lower().endswith((ext, ".mtl", ".jpg", ".png", ".jpeg")): z.extract(n, out)
                return ext, sorted(out / n for n in c)
    return None, []
def prescale(c):
    """cm/mm/m guess from the largest extent (CAD exports from Carl Hansen are cm OBJ / mm-or-cm 3DS); returns a Y-up GLB in metres."""
    import trimesh
    g = c.with_suffix(".pre.glb")
    if g.exists(): return g
    if c.suffix.lower() == ".glb": return c
    base = c
    if c.suffix.lower() == ".obj":
        sc = trimesh.load(str(c), force="scene", process=False)
    else: sc = trimesh.load(str(c), force="scene")
    m = float(max(sc.extents)); f = 1.0 if m < 10 else (0.01 if m < 600 else 0.001)
    sc.apply_scale(f); sc.export(str(g)); return g
def clean_name(n):
    n = re.sub(r"\s+", " ", n or "").strip()
    return n
def run():
    prods = json.load(open(R / "products.json")); seen = {}; items = []; rep = dict(fm={}, mism=[], bo=0, bp=0, w3d=0)
    for o in prods:
        z = [u for d, u in o["assets"] if "3d" in d.lower()]
        if z and z[0] not in seen: seen[z[0]] = o
    rep["w3d"] = len(seen)
    for k, (zu, o) in enumerate(seen.items()):
        pdg = cc.page(o["url"]); pd = pdg["pageData"]
        slg = o["url"].rstrip("/").rsplit("/", 1)[1]; pid = f"dsg-carlhansen-{slug(slg)}"
        zp = R / "files" / (slug(zu.rsplit("/", 1)[1]) + ".zip")
        if not get(zu, cache=zp, binary=True): continue
        try: ext, cands = extract(zp, R / "files" / slug(slg))
        except Exception as e: print("bad zip", slg, e); continue
        rep["fm"][ext or "none"] = rep["fm"].get(ext or "none", 0) + 1
        if not cands: print("no mesh", slg, flush=True); continue
        if (H / "models_opt" / (pid + ".glb")).exists() and (H / "models" / (pid + ".json")).exists(): info = process_model(pid, None, None)
        else:
            c = cands[0]
            if ext == ".3ds":
                g = c.with_suffix(".z0.glb")
                if not g.exists(): parse3ds.threeds_to_glb(c, g, True)
                c = g
            info = process_model(pid, prescale(c), None) if c.exists() else None
        if not info: print("convert fail", slg, flush=True); continue
        v0 = pd["Variants"][0] if pd.get("Variants") else {}
        price = None
        pg = cc.page(o["url"].replace("/en/en/", "/de-de/dede/"))
        if pg:
            vs = pg["pageData"].get("Variants") or []
            pr = [x["Price"] for x in vs if x.get("Price")]
            price = pr[0] if pr else None
        nm = clean_name(o["name"]); nm = nm.split("|")[-1].strip() if "|" in nm and len(nm.split("|")[-1].strip()) > 3 else nm
        code = clean_name(pd.get("ModelName") or o["name"].split("|")[0])
        name = f"{code} {nm}" if code.lower() not in nm.lower() else nm
        img = (v0.get("Images") or [{}])[0].get("Url") or ((pd.get("Specs") or {}).get("Images") or [{}])[0].get("Url")
        simg = save_image(img, pid + ".jpg", BRAND) if img else None
        cat = categorize(o["url"].split("/collection/")[1].rsplit("/", 1)[0].replace("-", " ").replace("/", " "), name)
        mats = [v0.get("FormattedConfiguration")] if v0.get("FormattedConfiguration") else None
        items.append(make_item(BRAND, name, pid=pid, designer=(pd.get("Designer") or {}).get("Name"), category=cat, price=price, currency="EUR" if price else None, price_source="brand shop EUR (de-de, first variant)",
                               product_url=o["url"], buy_url=o["url"].replace("/en/en/", "/de-de/dede/") if price else o["url"], image=simg, model=info, description=re.sub(r"<[^>]+>", " ", pd.get("ShortDescription") or pd.get("Description") or ""),
                               materials=mats, source_formats=[ext.strip(".")], extra={"listed_dims_m": None, "model_formats": [ext.strip(".")]}))
        rep["bo"] += info["model_bytes_orig"]; rep["bp"] += info["model_bytes"]
        print(k, slg, ext, info["dims"], price, flush=True)
        if len(items) % 5 == 0: save_items(BRAND, items)
    save_items(BRAND, items)
    json.dump({"brand": BRAND, "products_listed": len(prods), "with_3d_found": rep["w3d"], "models_converted": len(items), "items": len(items), "formats_found": rep["fm"], "price_coverage": sum(1 for x in items if x["price_usd"]),
               "how_3d_exposed": "Specs.OtherAssets in each product page's __NEXT_DATA__ links public *_3D*.zip on admincms.carlhansen.com (obj+3ds+dwg+max); prices from de-de market pages", "walled": False, "login_gated": False,
               "notes": "no listed dims on pages (dimension drawings are images): dims taken from GLB bbox with unit heuristic, unverified. Price = first variant EUR.", "dim_mismatches": 0, "bytes_orig": rep["bo"], "bytes_opt": rep["bp"]}, open(H / "raw" / "report_carlhansen.json", "w"), indent=1)
if __name__ == "__main__": run()
