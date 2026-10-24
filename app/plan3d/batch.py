"""Layouts for every plan image of the given listings (skips plans already done), then rooms_export; writes layouts/index.json."""
import sys, json, glob, pathlib, subprocess, time
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")
novlm = "--novlm" in sys.argv; listings = [a for a in sys.argv[1:] if not a.startswith("--")]; done = []
for lid in listings:
    meta = json.load(open(ROOT / "feasibility/listings" / lid / "meta.json")); plans = sorted(p for p in glob.glob(str(ROOT / "feasibility/listings" / lid / "plans/plan_*.[jp]*g")))
    for p in plans:
        unit = f"{lid}_{pathlib.Path(p).stem}"; out = HERE / "layouts" / f"{unit}.json"
        if not out.exists():
            r = subprocess.run([PY, str(HERE / "plan_engine.py"), "layout", p] + (["--novlm"] if novlm else []), capture_output=True, text=True, cwd=str(ROOT))
            if not out.exists(): print(f"[batch] {unit} FAILED: {r.stderr[-300:]}", flush=True); continue
            subprocess.run([PY, str(HERE / "rescale.py"), unit], capture_output=True, text=True, cwd=str(ROOT))   # area rule: listing/printed sqft or bedroom prior; never doors alone
            subprocess.run([PY, str(HERE / "rooms_export.py"), unit], capture_output=True, text=True, cwd=str(ROOT))
        L = json.load(open(out)); plan_name = next((f.get("name") for f in meta.get("floorplans", []) if f.get("file", "").endswith(pathlib.Path(p).name)), None)
        done.append({"unit": unit, "listing": lid, "building": meta.get("title"), "plan_image": f"/listings/{lid}/plans/{pathlib.Path(p).name}", "plan_name": plan_name, "rooms": [{"id": r["id"], "name": r["name"], "type": r["type"], "area_m2": r["area_m2"]} for r in L["rooms"]], "area_m2": round(sum(r["area_m2"] for r in L["rooms"]), 1), "scale_from": L["scale"]["from"] or ["none"], "n_fixtures": len(L["fixtures"]), "issues": L.get("review", {}).get("issues", [])})
        print(f"[batch] {unit}: {len(L['rooms'])} rooms {done[-1]['area_m2']} m2 fixtures {len(L['fixtures'])} scale {(L['scale']['from'] or ['none'])[0]}", flush=True)
idx = HERE / "layouts" / "index.json"; prev = json.load(open(idx)) if idx.exists() else []
merged = {d["unit"]: d for d in prev}; merged.update({d["unit"]: d for d in done}); json.dump(sorted(merged.values(), key=lambda d: d["unit"]), open(idx, "w"), indent=1)
print(f"[batch] index: {len(merged)} units")
