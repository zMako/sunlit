"""Rebuild layouts/index.json from the layout files and export every unit's room JSONs."""
import json, glob, pathlib, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python"); idx = []
for f in sorted(glob.glob(str(HERE / "layouts" / "*.json"))):
    if f.endswith("index.json") or f.endswith("test_unit.json"): continue
    L = json.load(open(f)); lid = L["listing"]; meta = json.load(open(ROOT / "feasibility/listings" / lid / "meta.json")); pimg = pathlib.Path(L["plan_image"]).name
    fp = next((p for p in meta.get("floorplans", []) if p.get("file", "").endswith(pimg)), {}); plan_name = fp.get("name")
    subprocess.run([PY, str(HERE / "rooms_export.py"), L["unit"]], capture_output=True, text=True, cwd=str(ROOT))
    idx.append({"unit": L["unit"], "listing": lid, "building": meta.get("title"), "plan_image": f"/listings/{lid}/plans/{pimg}", "plan_name": plan_name,
                "rooms": [{"id": r["id"], "name": r["name"], "type": r["type"], "area_m2": r["area_m2"]} for r in L["rooms"]], "area_m2": round(sum(r["area_m2"] for r in L["rooms"]), 1),
                "scale_from": L["scale"]["from"] or ["none"], "n_fixtures": len(L["fixtures"]), "bedrooms": fp.get("bedrooms"), "sqft": fp.get("sqft"), "annotated": bool(L.get("review", {}).get("usd")), "issues": L.get("review", {}).get("issues", []), "materials": bool(L.get("materials"))})
json.dump(idx, open(HERE / "layouts" / "index.json", "w"), indent=1); print(len(idx), "units"); import collections; print(dict(collections.Counter(d["listing"] for d in idx)))
