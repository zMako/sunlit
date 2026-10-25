"""Step 4: write catalog_abo.json from downloaded items. Dimensions come from the GLB bounding box (glTF is Y-up:
width=x, depth=z, height=y; read from the GLB itself via trimesh, falling back to 3dmodels.csv extents), cross-checked against listed item_dimensions."""
import json, ast, pathlib, re, datetime, sys
import trimesh
H = pathlib.Path(__file__).resolve().parent
src = (H.parent / "catalog.py").read_text(); tree = ast.parse(src); ns = {}
for n in tree.body:   # reuse catalog.py's STYLE table + style_tags() verbatim without importing (import has side effects)
    if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "STYLE") or (isinstance(n, ast.FunctionDef) and n.name == "style_tags"):
        exec(compile(ast.Module([n], []), "catalog.py", "exec"), ns)
SEL = {o["item_id"]: o for o in json.load(open(H / "raw/selected.json"))}; chosen = json.load(open(H / "raw/chosen.json"))
items = []; agree = 0; nlisted = 0
for iid in chosen:
    o = SEL[iid]; g = H / f"models/{iid}.glb"
    try:
        sc = trimesh.load(g, force="scene"); ext = [float(v) for v in sc.bounds[1] - sc.bounds[0]]; src_d = "glb_bbox"
    except Exception as e:
        ext = o["extent"]; src_d = "3dmodels.csv_extent"
    w, h, d = ext   # x, y(up), z
    L = o["listed_m"]
    if L and all(v == v and v > 0 for v in L.values()):
        nlisted += 1
        if max(abs(a / b - 1) for a, b in zip(sorted(ext), sorted(L.values()))) < .25: agree += 1
    desc = " ".join(o["bullets"]).strip()[:300]
    name = re.sub(r"\s+", " ", o["name"]).strip()[:120]
    items.append({"id": f"abo-{iid}", "name": name, "category": o["category"], "width_m": round(w, 3), "depth_m": round(d, 3), "height_m": round(h, 3),
        "dims_source": src_d + ("+listing_agrees" if L and max(abs(a / b - 1) for a, b in zip(sorted(ext), sorted(L.values()))) < .25 else "+listing_missing_or_differs" if L else "+no_listing_dims"),
        "listed_dims_m": {k: round(v, 3) for k, v in L.items()} if L else None,
        "price_usd": None, "product_url": f"https://www.amazon.com/dp/{iid}", "image": f"furnish/abo/images/{iid}.jpg", "model_glb": f"furnish/abo/models/{iid}.glb",
        "description": desc, "color": (o["color"] or "").lower() or None, "style_tags": ns["style_tags"](name, desc, o["color"], o["pt"].lower().replace("_", " ")),
        "type_name": o["pt"].lower().replace("_", " "), "brand": o["brand"], "source": "amazon-abo", "license": "CC BY-NC 4.0",
        "attribution": "Amazon.com (Amazon Berkeley Objects)", "fetched": str(datetime.date.today())})
json.dump({"items": items}, open(H / "catalog_abo.json", "w"), indent=1)
print(len(items), "items; listed dims present", nlisted, "agree with bbox (<25%)", agree)
