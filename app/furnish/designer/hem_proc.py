import sys, pathlib, zipfile, re, json, html
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common_dl import *
B = "hem"; R = H / "raw" / B
pages = json.load(open(R / "pages.json"))
dmap = json.load(open(R / "designers.json")) if (R / "designers.json").exists() else {}
groups = {}
for u, p in pages.items():
    if p.get("z3d"): groups.setdefault(p["z3d"], []).append(p)
MAXN = int(sys.argv[1]) if len(sys.argv) > 1 else 10**6
def dims(p):
    d = p.get("dims_cm") or {}
    L, W, Hh, D, Dia = d.get("Length"), d.get("Width"), d.get("Height"), d.get("Depth"), d.get("Diameter")
    if L and W: w, dp = L, W
    elif Dia: w, dp = Dia, Dia
    elif W and D: w, dp = W, D
    elif L: w, dp = L, D or L
    else: w, dp = W, D
    f = lambda x: round(x / 100, 3) if x else None
    return f(w), f(dp), f(Hh)
def meshes(root):
    c = [p for p in root.rglob("*") if p.is_file() and "__MACOSX" not in str(p) and p.suffix.lower() in (".glb", ".obj", ".fbx", ".3ds", ".dae") and not p.name.startswith("._")]
    rank = {".glb": 0, ".obj": 1, ".fbx": 2, ".3ds": 3, ".dae": 4}
    c.sort(key=lambda p: (rank[p.suffix.lower()], p.stat().st_size)); return c
def fits(dm, lst):
    ok = lambda a: all(not b or abs(math.log(max(x, 1e-6) / b)) <= math.log(1.35) for x, b in zip(a, lst))
    return ok(dm) or ok((dm[1], dm[0], dm[2]))
items = []; rep = {"formats": {}, "mism": 0, "notes": [], "with3d": 0, "big": 0, "nomesh": 0}
n = 0
for z, pl in groups.items():
    if n >= MAXN: break
    p = pl[0]; w, d, h = dims(p); listed = (w, d, h) if (w and d and h) else None
    name = re.sub(r",\s*[^,]*$", "", p["name"]) if "," in p["name"] else p["name"]
    pid = f"dsg-hem-{slug(z)}"
    n += 1
    if (H / "models_opt" / f"{pid}.glb").exists() and (H / "raw/hem/items_cache" / f"{pid}.json").exists():
        items.append(json.load(open(R / "items_cache" / f"{pid}.json"))); continue
    dest = R / "files" / (slug(z) + ".zip")
    dl = download("https://go.hem.com/3d-files/" + z, dest, maxmb=300)
    if dl == "BIG": rep["big"] += 1; rep["notes"].append(f"{z}: zip >300MB skipped"); continue
    if not dl: rep["notes"].append(f"{z}: download failed"); continue
    rep["with3d"] += 1
    ex = R / "files" / ("x_" + slug(z))
    if not ex.exists():
        ex.mkdir()
        try: zipfile.ZipFile(dest).extractall(ex)
        except Exception as e: print("unzip", z, e); continue
    ms = meshes(ex)
    if not ms: rep["nomesh"] += 1; rep["notes"].append(f"{z}: no glb/obj/fbx/3ds (rfa/dwg only)"); continue
    info = None; used = None
    for m in ms[:4]:
        i = process_model(pid, m, listed=listed)
        if not i: continue
        if listed and not fits(i["dims"], listed):
            rep["notes"].append(f"{pid}: {m.name} dims {i['dims']} vs listed {listed} rejected")
            for q in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb", H / "models" / f"{pid}.json"): q.unlink(missing_ok=True)
            continue
        info = i; used = m; break
    if not info: rep["mism"] += 1; continue
    fmt = used.suffix.lower(); rep["formats"][fmt] = rep["formats"].get(fmt, 0) + 1
    img = save_image(p["img"], f"{pid}.jpg", B) if p.get("img") else None
    fam = p["url"].split("/")[-2]; cat_txt = p["url"].split("/")[-3] + " " + fam
    cat = categorize(name) if categorize(name) != "other" else categorize(cat_txt)
    mats = "; ".join(x for x in (p.get("inside"), p.get("legs"), p.get("uph")) if x)
    ds = dmap.get(fam)
    it = make_item("Hem", name, designer=", ".join(sorted(set(ds))) if ds else None, category=cat, w=w, d=d, h=h, price=float(p["price"]) if p.get("price") else None, currency=p.get("cur"),
                   price_source="brand shop USD" if p.get("price") else None, product_url=p["url"], buy_url=p["url"], image=img, model=info, description=p.get("desc") or "", materials=mats or None,
                   source_formats=[fmt.strip(".")], pid=pid, extra={"listed_dims_m": {"w": w, "d": d, "h": h}, "model_formats": [fmt.strip(".")], "model_source_file": used.name})
    (R / "items_cache").mkdir(exist_ok=True); json.dump(it, open(R / "items_cache" / f"{pid}.json", "w"))
    items.append(it); save_items("Hem", items); print(pid, info["dims"], listed, p.get("price"), flush=True)
json.dump({"brand": "Hem", "products_listed": len(pages), "with_3d_found": rep["with3d"], "models_converted": len(items), "items": len(items), "formats_found": rep["formats"],
           "price_coverage": sum(1 for i in items if i["price_usd"]), "how_3d_exposed": "Each product page lists 'Downloads > 3D files' -> go.hem.com/3d-files/<slug> (301 to storage.googleapis.com/hem-digital-assets, public zips with FBX+RFA+DWG)",
           "walled": False, "login_gated": False, "notes": "; ".join(rep["notes"])[:3000], "dim_mismatches": rep["mism"], "oversize_skipped": rep["big"],
           "bytes_orig": sum(i.get("model_bytes_orig") or 0 for i in items), "bytes_opt": sum(i.get("model_bytes") or 0 for i in items), "minutes": 90}, open(R.parent / "report_hem.json", "w"), indent=1)
