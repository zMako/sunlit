"""Remove degenerate layouts (fewer than 2 rooms or under 8 m2, or made from a non-plan image) and their room JSONs; rebuild index.json."""
import json, glob, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); import plan_engine as pe
removed = []
for f in sorted(glob.glob(str(HERE / "layouts" / "*.json"))):
    if f.endswith("index.json") or f.endswith("test_unit.json"): continue
    L = json.load(open(f)); total = sum(r["area_m2"] for r in L["rooms"]); bad = len(L["rooms"]) < 2 or total < 8 or total > 260 or max((r["area_m2"] for r in L["rooms"]), default=0) > 90
    try:
        g, _, _ = pe.load_ink(L["plan_image"]); bad = bad or not pe.is_plan(g)
    except Exception: pass
    if bad:
        pathlib.Path(f).unlink(); removed.append(L["unit"])
        for r in glob.glob(str(HERE.parent / "rooms" / f"{L['unit']}__*.json")): pathlib.Path(r).unlink()
idx = HERE / "layouts" / "index.json"
if idx.exists():
    I = [d for d in json.load(open(idx)) if d["unit"] not in removed]; json.dump(I, open(idx, "w"), indent=1)
print("removed", removed)
