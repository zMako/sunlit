import sys, pathlib, zipfile, re, json, html
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common_dl import *
B = "string"; R = H / "raw" / B
SERIES = {"system": "String System", "works": "Works", "museum": "Museum Collection", "pira-g2": "Pira", "relief": "Relief", "pocket": "String Pocket"}
DESIGNER = {"system": ("Nils Strinning", 1949), "pocket": ("Nils Strinning", 1949)}
ps = json.load(open(R / "products.json"))
sm = get("https://www.stringfurniture.com/sitemap_en.xml", cache=R / "sm_en.xml").text
urls = [u for u in re.findall(r"<loc>([^<]+)", sm) if "/en/series/" in u and u.count("/") >= 7]
def ldjson(u):
    r = get(u, cache=cpath(B, u))
    if not r: return None
    for m in re.finditer(r'application/ld\+json[^>]*>(.*?)</script>', r.text, re.S):
        try: j = json.loads(m.group(1))
        except Exception: continue
        if j.get("@type") == "Product": return j
def cm(v):
    m = re.match(r"([\d.]+)\s*(cm|mm|m)?", v or "")
    return None if not m else float(m.group(1)) * {"cm": 0.01, "mm": 0.001, "m": 1}.get(m.group(2) or "cm")
def norm(s): return re.sub(r"[^A-Z0-9]", "", (s or "").upper())
def find_page(pname, code):
    toks = slug(pname).split("-")[:2]
    cands = [u for u in urls if all(t.rstrip("s") in u.rsplit("/", 1)[-1] for t in toks)] + [u for u in urls]
    for u in cands:
        j = ldjson(u)
        if j and norm(j.get("sku")).startswith(norm(code)): return u, j
    return None, None
def pick_mesh(root):
    c = [p for p in root.rglob("*") if p.is_file() and "__MACOSX" not in str(p) and p.suffix.lower() in (".obj", ".fbx", ".3ds")]
    if not c: return None
    rank = {".obj": 0, ".fbx": 1, ".3ds": 2}
    c.sort(key=lambda p: (rank[p.suffix.lower()], "open" not in p.name.lower(), p.name))
    return c[0]
seen_zip = set()
items = []; rep = {"formats": {}, "dim_mismatch": 0, "notes": [], "with3d": 0}
for p in ps:
    if not p.get("files"): continue
    tag = (p.get("tags") or ["system"])[0]
    for f in p["files"]:
        zp = R / "files" / p["code"] / f["filename"]
        if (f["filename"], f["size"]) in seen_zip: continue
        seen_zip.add((f["filename"], f["size"]))
        if not zp.exists() or zp.suffix != ".zip": continue
        ex = R / "files" / p["code"] / ("x_" + re.sub(r"\W", "_", zp.stem))
        if not ex.exists():
            ex.mkdir()
            try: zipfile.ZipFile(zp).extractall(ex)
            except Exception as e: print("unzip fail", zp, e); continue
        mesh = pick_mesh(ex)
        if not mesh: rep["notes"].append(f"{p['name']} {zp.stem}: no obj/fbx/3ds (only max/dwg)"); continue
        rep["with3d"] += 1
        fmt = mesh.suffix.lower(); rep["formats"][fmt] = rep["formats"].get(fmt, 0) + 1
        code = re.sub(r"[_ ]?(Composite|2025.*)$", "", zp.stem); code = code.split("_")[-1] if re.match(r"^[a-z_]+_[A-Z0-9-]+$", code) else code
        code = re.sub(r"^.*_(?=[A-Z0-9-]+$)", "", code)
        url, j = find_page(p["name"], code)
        name = f"{p['name']} {code}".strip(); pid = f"dsg-string-{slug(name)}"
        listed = None; extra_l = {}
        if j:
            w, d, h = cm(j.get("width")), cm(j.get("depth")), cm(j.get("height"))
            if w and d and h: listed = (w, d, h); extra_l = {"width": w, "depth": d, "height": h}
        src = mesh
        if fmt == ".3ds":
            src = convert_3ds_to_obj(mesh, R / "obj" / (pid + ".obj"), zup_to_yup=False)   # Max files are Z-up; fit_transform handles Z-up
            if not src: rep["notes"].append(f"{pid}: 3ds parse failed"); continue
        if fmt == ".obj":   # native OBJ from Works: Y-up, avoid Z-up guess
            g = R / "obj" / (pid + ".glb")
            if not to_glb(src, g): rep["notes"].append(f"{pid}: obj convert failed"); continue
            src = g
        for q in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb"): q.unlink(missing_ok=True)   # regenerate (orientation logic changed)
        info = process_model(pid, src, listed=listed)
        if info and (max(info["dims"]) > 3.3 or "parts" in pid):
            rep["notes"].append(f"{pid}: dropped (part/oversize {info['dims']})")
            for q in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb", H / "models" / f"{pid}.json"): q.unlink(missing_ok=True)
            continue
        if not info: rep["notes"].append(f"{pid}: process_model failed"); continue
        if listed:
            dm = info["dims"]
            if any(abs(math.log(max(a, 1e-6) / b)) > math.log(1.35) for a, b in zip(dm, listed) if b) and any(abs(math.log(max(a, 1e-6) / b)) > math.log(1.35) for a, b in zip((dm[1], dm[0], dm[2]), listed) if b):
                rep["dim_mismatch"] += 1; rep["notes"].append(f"{pid}: rejected dims {dm} vs listed {listed}")
                for q in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb"): q.unlink(missing_ok=True)
                continue
        img = None
        imgurl = p.get("image")
        if imgurl: img = save_image(imgurl, f"{pid}.jpg", B)
        pr = j and (j.get("offers") or {}); price = pr.get("price") if pr else None; cur = pr.get("priceCurrency") if pr else None
        des = DESIGNER.get(tag, (None, None))
        it = make_item("String", name, designer=des[0], year=des[1], category=categorize(p["name"]), w=listed and listed[0], d=listed and listed[1], h=listed and listed[2],
                       price=price, currency=cur, price_source=(f"brand shop {cur}" if price else None), product_url=url or "https://www.stringfurniture.com/en/professionals/3d-images",
                       buy_url=url or "https://www.stringfurniture.com/en/find-a-store", image=img, model=info,
                       description=(j or {}).get("description") or f"String Furniture {SERIES.get(tag, '')} {p['name']}", materials=(j or {}).get("material"), colours=(j or {}).get("color"),
                       source_formats=[fmt.strip(".")], pid=pid, extra={"listed_dims_m": extra_l or None, "model_formats": [fmt.strip(".")], "series": SERIES.get(tag)})
        items.append(it); save_items("String", items); print(pid, info["dims"], listed, price, flush=True)
rep_out = {"brand": "String", "products_listed": len(ps), "with_3d_found": rep["with3d"], "models_converted": len(items), "items": len(items), "formats_found": rep["formats"],
           "price_coverage": sum(1 for i in items if i["price_usd"]), "how_3d_exposed": "Public product-group pages /professionals/3d-images link to anonymous Mediaflow share links (shareapi.mediaflow.com token = share id) and iCatServer transfer links; each zip holds 3DS(+3ds Max, DWG, textures) or OBJ/FBX",
           "walled": False, "login_gated": False, "notes": "; ".join(rep["notes"])[:2000], "dim_mismatches": rep["dim_mismatch"],
           "bytes_orig": sum(i.get("model_bytes_orig") or 0 for i in items), "bytes_opt": sum(i.get("model_bytes") or 0 for i in items), "minutes": 60}
json.dump(rep_out, open(R.parent / "report_string.json", "w"), indent=1)
