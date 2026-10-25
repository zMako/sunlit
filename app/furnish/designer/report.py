"""Builds REPORT.md and LOGIN_NEEDED.md from raw/report_*.json, raw/login_*.md, raw/walls.json and raw/items_*.json."""
import json, glob, pathlib, collections
H = pathlib.Path(__file__).resolve().parent
items = []
for f in sorted(glob.glob(str(H / "raw/items_*.json"))): items += json.load(open(f))
by = collections.defaultdict(list)
for i in items: by[i["brand"]].append(i)
reps = {}
for f in glob.glob(str(H / "raw/report_*.json")):
    r = json.load(open(f)); reps[r["brand"]] = r
mb = lambda b: f"{b/1e6:.0f} MB" if b else "-"
L = ["# Designer tier (catalog_designer): report", "", f"Items with models: **{len(items)}** across {len(by)} brands. Models: `models/` (rescaled to metres, Y-up, floor at 0), `models_opt/` (gltf-transform Draco + WebP 1024).",
     "Conversion: OBJ/PLY/STL via trimesh; FBX/3DS/DAE via headless Blender 5.2 (/Applications/Blender.app, `blender -b -P blender_convert.py`; bpy pip not needed). Scale/orientation auto-fit to listed dims (common.fit_transform).", "",
     "| brand | items | formats | price coverage | models before | models after | how 3D is exposed |", "|---|---|---|---|---|---|---|"]
tb = ta = 0
for b in sorted(by, key=lambda b: -len(by[b])):
    its = by[b]; r = reps.get(b, {}); o = sum(i.get("model_bytes_orig") or 0 for i in its); n = sum(i.get("model_bytes") or 0 for i in its); tb += o; ta += n
    fm = collections.Counter(f for i in its for f in (i.get("model_formats") or []))
    pr = sum(1 for i in its if i.get("price_usd") is not None)
    L.append(f"| {b} | {len(its)} | {', '.join(f'{k} {v}' for k, v in fm.items()) or '-'} | {pr}/{len(its)} | {mb(o)} | {mb(n)} | {r.get('how_3d_exposed', '')} |")
L += ["", f"Total models: {mb(tb)} original -> {mb(ta)} optimised.", "", "## Per-brand notes", ""]
for b in sorted(reps): r = reps[b]; L += [f"### {b}", f"- listed {r.get('products_listed')}, with 3D {r.get('with_3d_found')}, converted {r.get('models_converted')}, items {r.get('items')}; dim mismatches rejected: {r.get('dim_mismatches')}; walled: {r.get('walled')}; login-gated: {r.get('login_gated')}", f"- {r.get('notes', '')}", ""]
cats = collections.Counter(i["category"] for i in items); L += ["## Categories", ", ".join(f"{k} {v}" for k, v in sorted(cats.items())), ""]
dm = [i for i in items if i.get("dims_source") == "listed" and i.get("model_dims_m")]
bad = [i for i in dm if i.get("width_m") and i.get("height_m") and (abs(i["model_dims_m"][2] / i["height_m"] - 1) > .35)]
L += [f"## Dimensions check", f"Items with listed dims: {len(dm)}; height differs >35% from model bbox: {len(bad)}; items using bbox dims only: {sum(1 for i in items if i.get('dims_source') == 'glb_bbox')}.", ""]
walls = json.load(open(H / "raw/walls.json")) if (H / "raw/walls.json").exists() else {}
L += ["## Bot walls hit (not bypassed)", ""] + [f"- {h}: HTTP {w['status']} at {w['url']}" for h, w in walls.items()] + [""]
(H / "REPORT.md").write_text("\n".join(L))
LG = ["# Login-gated 3D files (owner to fetch)", "", "Brands whose 3D/CAD sit behind a professional login or a bot wall. Nothing here was accessed.", ""]
for f in sorted(glob.glob(str(H / "raw/login_*.md"))): LG += [pathlib.Path(f).read_text().strip(), ""]
(H / "LOGIN_NEEDED.md").write_text("\n".join(LG)); print("wrote REPORT.md, LOGIN_NEEDED.md")
