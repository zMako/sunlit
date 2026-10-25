"""Artemide: public per-product modal (/en/product/modalProdotto?id=) lists 3D Model files (3DS + STP) with no login; one item per distinct 3DS/zip."""
import sys, re, json, html, pathlib, time, zipfile, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
B = "Artemide"; A = "https://www.artemide.com"; R = H / "raw/artemide"; F = R / "files"; EX = R / "ex"; F.mkdir(parents=True, exist_ok=True); t0 = time.time()
prods = json.load(open("/tmp/w_E/ar_prods.json")) if pathlib.Path("/tmp/w_E/ar_prods.json").exists() else json.load(open(R / "prods.json")); json.dump(prods, open(R / "prods.json", "w"))
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
def txt(t):
    x = re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S); x = re.sub(r'<!--.*?-->', ' ', x, flags=re.S); x = re.sub(r'<[^>]+>', '|', x); return html.unescape(re.sub(r'[\s|]+', ' ', x))
files = collections.OrderedDict()  # href -> first product record
for pid_, (sid, sname) in prods.items():
    u = f"{A}/en/product/modalProdotto?id={pid_}"; p = cpath("artemide", u)
    if not p.exists(): continue
    t = p.read_text(errors="replace")
    hs = re.findall(r'<a href="([^"]*)"[^>]*data-type="model3d"', t, re.S)
    hs = [h for h in hs if h.lower().rsplit(".", 1)[-1] in ("3ds", "zip", "obj", "fbx", "dae")]
    if not hs: continue
    h0 = sorted(hs, key=lambda h: (h.lower().endswith("zip"), h))[0]
    if h0 not in files: files[h0] = (pid_, sid, sname, t)
print("distinct 3D files", len(files), flush=True)
def cat_of(inst, name):
    i = (inst or "").lower()
    if i.startswith("table"): return "table_lamp"
    if i.startswith("floor"): return "floor_lamp"
    if i.startswith("suspension"): return "pendant_lamp"
    if re.search(r"wall|ceiling|recessed|surface|outdoor|ground|bollard|track|spot", i): return "other"
    c = categorize(name); return c if c in ("floor_lamp", "table_lamp", "pendant_lamp") else "other"
items = []; rej = []; used = set(); fm = {}
for n_, (h, (pid_, sid, sname, t)) in enumerate(files.items()):
    if n_ >= LIMIT: break
    local = F / pathlib.Path(h).name
    r = get(A + h, cache=local, binary=True) if not local.exists() else True
    if not r or not local.exists():
        if r and r is not True: local.write_bytes(r.content)
        else: rej.append((h, "download")); continue
    if r is not True and not local.exists(): local.write_bytes(r.content)
    mesh = local
    if local.suffix.lower() == ".zip":
        d = EX / local.stem
        if not d.exists():
            d.mkdir(parents=True)
            try:
                with zipfile.ZipFile(local) as z:
                    for i in z.infolist():
                        if i.filename.startswith("__MACOSX") or i.filename.endswith("/") or ".." in i.filename: continue
                        if i.filename.lower().rsplit(".", 1)[-1] in ("3ds", "obj", "fbx", "dae", "mtl", "png", "jpg"): z.extract(i, d)
            except Exception: pass
        c = sorted([q for q in d.rglob("*") if q.suffix.lower() in (".obj", ".fbx", ".3ds", ".dae")], key=lambda q: [".obj", ".fbx", ".3ds", ".dae"].index(q.suffix.lower()))
        if not c: rej.append((h, "zip no mesh")); continue
        mesh = c[0]
    x = txt(t); title = html.unescape(re.search(r'subfamily-modal__title"><span>(.*?)</span>', t, re.S).group(1)).strip()
    name = title.split(" - ")[0].strip(); name = re.sub(r"\s+", " ", name)
    pid = f"dsg-artemide-{slug(name)}"
    if pid in used: pid += "-" + slug(pathlib.Path(h).stem)[-12:]
    used.add(pid)
    inst = (re.search(r"Installation: (\w+)", x) or [None, None])[1]; des = re.search(r"design by: (.*?)(?: LUMINAIRE| DIMENSIONS|$)", x); mat = re.search(r"Material: (.*?) Series:", x)
    col = re.search(r"Colour: (.*?) (?:Installation|Material|Series)", x); ser = re.search(r"Series: (.*?) (?:design by|Environment)", x)
    dm = x[x.find("DIMENSIONS"):] if "DIMENSIONS" in x else ""
    dm = re.split(r"SOURCES|AWARDS|Accessories|Download all", dm)[0]
    dd_ = {k: float(v) / 1000 for k, v in re.findall(r"([A-Za-z][A-Za-z ]*?): (\d+(?:\.\d+)?) mm", dm)}
    main = [dd_[k] for k in ("Diameter", "Length", "Width", "Depth") if k in dd_]; allh = [v for k, v in dd_.items() if "Height" not in k]
    H_ = dd_.get("Height"); maxH = max([v for k, v in dd_.items() if "Height" in k] or [0])
    w = dd_.get("Width") or dd_.get("Diameter") or dd_.get("Length"); dep = dd_.get("Length") if dd_.get("Width") else (dd_.get("Depth") or dd_.get("Diameter"))
    if "Diameter" in dd_ and "Width" not in dd_: w = dep = dd_["Diameter"]
    cat = cat_of(inst, name); pend = cat == "pendant_lamp"
    info = process_model(pid, mesh, listed=(w, dep, None) if pend else (w, dep, H_))
    if not info: rej.append((name, "parse")); continue
    bb = info["dims"]; hm = max(bb[:2]); bad = False
    if main and not (0.65 * max(main) <= hm <= 1.35 * max(allh or main)): bad = True
    if H_ and not pend and not (0.65 * H_ <= bb[2] <= 1.35 * max(H_, maxH)): bad = True
    if H_ and pend and bb[2] < 0.65 * H_: bad = True
    if bad:
        rej.append((name, f"bbox {bb} vs listed {dd_}"))
        for p_ in (H / "models" / f"{pid}.glb", H / "models_opt" / f"{pid}.glb", H / "models" / f"{pid}.json"): p_.unlink(missing_ok=True)
        print("MISMATCH", name, bb, dd_, flush=True); continue
    im = re.search(r"subfamily-modal__image[^>]*background-image: url\(([^)]+)\)", t); img = save_image(A + im.group(1), pid + ".jpg", B) if im else None
    desc = f"{inst or ''} luminaire from the Artemide {ser.group(1) if ser else ''} series" + (f", design by {des.group(1).strip()}." if des else ".")
    purl = f"{A}/en/subfamily/{sid}/{sname}"
    items.append(make_item(B, name, designer=des.group(1).strip() if des else None, category=cat, w=w, d=dep, h=H_, price=None, product_url=purl, buy_url=f"{A}/en/storelocator", image=img, model=info,
        description=desc, materials=mat.group(1) if mat else None, colours=col.group(1) if col else None, source_formats=[mesh.suffix.lower().strip(".")], pid=pid,
        extra={"listed_dims_m": {"w": w, "d": dep, "h": H_}, "model_formats": [mesh.suffix.lower().strip(".")], "product_code_sample": None}))
    e = mesh.suffix.lower().strip("."); fm[e] = fm.get(e, 0) + 1
    if len(items) % 5 == 0: save_items(B, items)
    print("ok", cat, name, bb, flush=True)
save_items(B, items)
json.dump({"brand": B, "products_listed": len(prods), "with_3d_found": len(files), "models_converted": len(items), "items": len(items), "formats_found": fm,
  "price_coverage": 0, "how_3d_exposed": "Family pages list products; each product modal /en/product/modalProdotto?id=N has a 'Downloadable files' accordion with 3D Model (.3ds + .stp, some zip) at /contents/documenti/prodotto/...; public, no login. No online shop price; buy_url = store locator.",
  "walled": False, "login_gated": False, "notes": json.dumps(rej), "dim_mismatches": sum(1 for r_ in rej if "bbox" in r_[1]),
  "bytes_orig": sum(i.get("model_bytes_orig") or 0 for i in items), "bytes_opt": sum(i.get("model_bytes") or 0 for i in items), "minutes": round((time.time() - t0) / 60, 1)}, open(R / "report_artemide.json", "w"), indent=1)
