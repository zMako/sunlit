"""GUBI: product pages (sitemap) embed public '3D Drawings' zip paths served from media.gubi.com (dwg + 3ds/obj/fbx). Resumable; python gubi.py [limit]"""
import sys, re, json, pathlib, zipfile, html
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); from common import *
import common, subprocess, math, parse3ds
def _bc(src, dst):   # common.blender_convert crashes on binary stdout; same call with errors=replace
    p = subprocess.run([common.BLENDER, "-b", "-noaudio", "-P", str(common.H / "blender_convert.py"), "--", str(src), str(dst)], capture_output=True, text=True, errors="replace", timeout=900)
    return p.returncode == 0 and pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 1000
common.blender_convert = _bc
B = "gubi"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
BRAND = "GUBI"; PREF = [".glb", ".gltf", ".obj", ".fbx", ".3ds", ".dae"]
def product_urls():
    t = get("https://gubi.com/sitemap.xml", cache=cpath(B, "sitemap", "xml")).text
    return sorted(u for u in set(re.findall(r"<loc>(https://gubi\.com/en/us/products/[^<]*)", t)) if not u.rsplit("/", 1)[1].isdigit())
def dec(h): return h.replace('\\\\\\"', '\x01').replace('\\"', '"').replace('\x01', '\\"')
def nums(s): return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s or "")]
def parse(u):
    r = get(u, cache=cpath(B, u))
    if not r: return None
    h = r.text; d = dec(h)
    spec = {}
    for k, v in re.findall(r'"label":"([^"]+)","value":"([^"]*)"', d): spec.setdefault(k, v)
    zips = re.findall(r'product-documents/shared/3D Drawings/[^"\\]+?\.zip', d)
    desc = re.findall(r'productDescription[^>]*><p[^>]*>(.*?)</p>', h, re.S)
    img = re.findall(r'og:image" content="([^"]*)', h) or re.findall(r'"src":"(https://cdn\.thorcommerce\.io/gubi/[^"]+)"', d)
    price = re.findall(r"(?<=>)\$([\d,]+(?:\.\d+)?)(?=<)", h)
    mats = [f"{k}: {v}" for k, v in spec.items() if re.search(r"Material|Colo|Finish", k) and "Table Top Dimensions" not in k][:8]
    return {"url": u, "name": spec.get("Product Name") or re.sub(r"^GUBI ", "", (re.findall(r"<title>(.*?)</title>", h) or [""])[0]), "designer": html.unescape(spec.get("Designer", "")) or None,
            "year": spec.get("Design Year"), "type": spec.get("Type"), "dims": nums(spec.get("Overall Dimensions (cm) (W x H x D)")), "zip": zips[0] if zips else None,
            "desc": html.unescape(re.sub(r"<[^>]+>", "", desc[0])) if desc else "", "image": img[0] if img else None, "price": float(price[0].replace(",", "")) if price else None, "materials": mats, "spec": spec}
def pick_meshes(zpath, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and ".." not in n and not n.startswith("/")]
        for ext in PREF:
            c = [n for n in names if n.lower().endswith(ext)]
            if c:
                for n in names:   # extract all (textures stay next to OBJ)
                    if n.lower().endswith((ext, ".mtl", ".jpg", ".png", ".jpeg")): z.extract(n, outdir)
                return ext, [outdir / n for n in c], names
    return None, [], names
def run(limit=None):
    items = []; rep = {"formats": {}, "listed": 0, "with3d": 0, "mismatch": 0, "bo": 0, "bp": 0, "mism_list": []}
    urls = product_urls()[:limit]
    for i, u in enumerate(urls):
        p = parse(u); rep["listed"] += 1
        if not p or not p["zip"]: continue
        rep["with3d"] += 1; slg = u.rsplit("/", 1)[1]
        pid = f"dsg-gubi-{slug(slg)}"
        zr = get("https://media.gubi.com/" + p["zip"].replace(" ", "%20"), cache=R / "files" / (slg + ".zip"), binary=True)
        if not zr: continue
        ext, cands, names = pick_meshes(R / "files" / (slg + ".zip"), R / "files" / slg)
        rep["formats"][ext or "none"] = rep["formats"].get(ext or "none", 0) + 1
        if not cands: print("no mesh", slg, names[:5], flush=True); continue
        dm = p["dims"]; listed = (dm[0] / 100, dm[2] / 100, dm[1] / 100) if len(dm) == 3 else None
        best = None; tried = []
        if (H / 'models_opt' / (pid + '.glb')).exists() and (H / 'models' / (pid + '.json')).exists():
            best = (process_model(pid, None, listed), pid, 0)
        for ci, c in enumerate([] if best else sorted(cands)[:6]):
            vars_ = [(c, "")]
            if ext == ".3ds":
                vars_ = []
                for zi, zup in enumerate((True, False)):
                    g = c.with_suffix(f".z{zi}.glb")
                    if not g.exists(): parse3ds.threeds_to_glb(c, g, zup)
                    if g.exists(): vars_.append((g, f"z{zi}"))
            for path, tag in vars_:
                q = f"{pid}~{ci}{tag}"
                info = process_model(q, path, listed)
                if not info: continue
                e = sum(abs(math.log(max(a, 1e-6) / b)) for a, b in zip(info["dims"], listed)) if listed else 0
                tried.append((q, e))
                if best is None or e < best[2]: best = (info, q, e)
        if not best: print("convert fail", slg, flush=True); continue
        # keep only the winning candidate under the canonical id; drop the rest
        for q, e in tried:
            if q != best[1]:
                for sub, e2 in (("models", ".glb"), ("models", ".json"), ("models_opt", ".glb")): (H / sub / (q + e2)).unlink(missing_ok=True)
        info, q = best[0], best[1]
        if q != pid:
            for sub, ext2 in (("models", ".glb"), ("models", ".json"), ("models_opt", ".glb")):
                (H / sub / (q + ext2)).replace(H / sub / (pid + ext2))
        ok = True
        if listed:
            for a, b in zip(info["dims"], listed):
                if abs(a / b - 1) > 0.35: ok = False
        if not ok:
            rep["mismatch"] += 1; rep["mism_list"].append([slg, info["dims"], listed]); print("dim mismatch", slg, info["dims"], listed, flush=True)
            for sub, e2 in (("models", ".glb"), ("models", ".json"), ("models_opt", ".glb")): (H / sub / (pid + e2)).unlink(missing_ok=True)
            continue
        img = save_image(p["image"], pid + ".jpg", BRAND) if p["image"] else None
        cat = categorize(p["type"], p["name"])
        items.append(make_item(BRAND, p["name"], pid=pid, designer=p["designer"], category=cat, w=listed and listed[0], d=listed and listed[1], h=listed and listed[2], price=p["price"], currency="USD" if p["price"] else None,
                               price_source="brand shop USD (excl. VAT)", product_url=u, image=img, model=info, description=p["desc"], materials=p["materials"], year=p["year"], source_formats=[ext.strip(".")],
                               extra={"listed_dims_m": listed and dict(w=listed[0], d=listed[1], h=listed[2]), "model_formats": [ext.strip(".")]}))
        rep["bo"] += info["model_bytes_orig"]; rep["bp"] += info["model_bytes"]
        if len(items) % 5 == 0: save_items(BRAND, items)
        print(i, slg, ext, info["dims"], flush=True)
    save_items(BRAND, items)
    json.dump({"brand": BRAND, "products_listed": rep["listed"], "with_3d_found": rep["with3d"], "models_converted": len(items), "items": len(items), "formats_found": rep["formats"],
               "price_coverage": sum(1 for x in items if x["price_usd"]), "how_3d_exposed": "product page data lists product-documents/shared/3D Drawings/*.zip, served publicly from media.gubi.com (dwg + 3ds/obj)",
               "walled": False, "login_gated": False, "notes": "prices: US webshop USD excl. VAT", "dim_mismatches": rep["mismatch"], "mismatches": rep["mism_list"], "bytes_orig": rep["bo"], "bytes_opt": rep["bp"]},
              open(H / "raw" / "report_gubi.json", "w"), indent=1)
if __name__ == "__main__": run(int(sys.argv[1]) if len(sys.argv) > 1 else None)
