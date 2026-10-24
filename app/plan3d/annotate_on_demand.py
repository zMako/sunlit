"""Name rooms and place fixtures with Claude for ONE unit, on demand (the judge picked a unit nobody annotated yet).

    feasibility/.venv/bin/python app/plan3d/annotate_on_demand.py <unit> [--json]

Runs `REPAIR=1 plan_engine.py layout <plan>` (plan reader + repair + annotation, ~5 cents, every call goes through
app/spend.py), then rescale.py and rooms_export.py, and updates that unit's entry in layouts/index.json in place (no full
reindex). The engine swallows VLM errors and would write an un-annotated layout over the old one, so the old layout is kept
aside and restored unless the new one carries an annotation (review.usd). A refused spend (SpendCapExceeded) prints
{"error": "budget cap reached"} and exits 3; other failures exit 1. With --json the last stdout line is the result JSON."""
import sys, os, json, glob, shutil, pathlib, subprocess, re, fcntl
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")
LAYOUTS = HERE / "layouts"; INDEX = LAYOUTS / "index.json"
sys.path.insert(0, str(ROOT / "app")); import spend

def is_annotated(L): return bool((L.get("review") or {}).get("usd"))

def index_entry(L, old=None):
    lid = L["listing"]; meta = json.load(open(ROOT / "feasibility/listings" / lid / "meta.json")); pimg = pathlib.Path(L["plan_image"]).name
    plan_name = next((p.get("name") for p in meta.get("floorplans", []) if p.get("file", "").endswith(pimg)), None)
    e = dict(old or {})   # keep fields other workers may have added (materials flag, metrics...)
    e.update({"unit": L["unit"], "listing": lid, "building": meta.get("title"), "plan_image": f"/listings/{lid}/plans/{pimg}", "plan_name": plan_name,
              "rooms": [{"id": r["id"], "name": r["name"], "type": r["type"], "area_m2": r["area_m2"]} for r in L["rooms"]],
              "area_m2": round(sum(r["area_m2"] for r in L["rooms"]), 1), "scale_from": L["scale"]["from"] or ["none"], "n_fixtures": len(L["fixtures"]),
              "issues": L.get("review", {}).get("issues", []), "materials": bool(L.get("materials")), "annotated": is_annotated(L)})
    return e

def update_index(L):
    with open(str(INDEX) + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        idx = json.load(open(INDEX)) if INDEX.exists() else []
        for i, d in enumerate(idx):
            if d["unit"] == L["unit"]: idx[i] = index_entry(L, d); break
        else: idx.append(index_entry(L)); idx.sort(key=lambda d: d["unit"])
        tmp = INDEX.with_suffix(".json.tmp"); json.dump(idx, open(tmp, "w"), indent=1); tmp.replace(INDEX)

def plan_path(unit):
    f = LAYOUTS / f"{unit}.json"
    if f.exists(): return json.load(open(f))["plan_image"]
    m = re.match(r"(.+)_(plan_\d+)$", unit)
    if not m: return None
    hits = glob.glob(str(ROOT / "feasibility/listings" / m.group(1) / "plans" / f"{m.group(2)}.*"))
    hits = [h for h in hits if re.search(r"\.(jpe?g|png)$", h, re.I)]
    return hits[0] if hits else None

def run(unit):
    f = LAYOUTS / f"{unit}.json"
    if f.exists():
        L = json.load(open(f))
        if is_annotated(L): update_index(L); return {"ok": True, "already": True, "rooms": [r["name"] for r in L["rooms"]], "fixtures": len(L["fixtures"]), "usd": 0.0}
    plan = plan_path(unit)
    if not plan: return {"error": f"unknown unit {unit}"}
    led0 = spend.status()["usd"]["anthropic"]
    try: spend.check("anthropic", 0.08)   # refuse up front when even one annotation would cross the cap
    except spend.SpendCapExceeded as e: return {"error": "budget cap reached", "detail": str(e)}
    bak = f.with_suffix(".json.bak")
    if f.exists(): shutil.copy2(f, bak)
    r = subprocess.run([PY, str(HERE / "plan_engine.py"), "layout", plan], capture_output=True, text=True, cwd=str(ROOT), env=dict(os.environ, REPAIR="1"), timeout=600)
    log = (r.stdout or "") + (r.stderr or ""); usd = round(spend.status()["usd"]["anthropic"] - led0, 4)
    L = json.load(open(f)) if f.exists() else None
    if not L or not is_annotated(L):
        if bak.exists(): shutil.move(bak, f)
        elif f.exists(): f.unlink()
        if "SpendCapExceeded" in log: return {"error": "budget cap reached", "usd": usd}
        return {"error": "annotation failed", "usd": usd, "log": log[-600:]}
    if bak.exists(): bak.unlink()
    subprocess.run([PY, str(HERE / "rescale.py"), unit], capture_output=True, text=True, cwd=str(ROOT))
    subprocess.run([PY, str(HERE / "rooms_export.py"), unit], capture_output=True, text=True, cwd=str(ROOT))
    L = json.load(open(f)); update_index(L)
    return {"ok": True, "rooms": [r["name"] for r in L["rooms"]], "fixtures": len(L["fixtures"]), "usd": usd, "area_m2": round(sum(r["area_m2"] for r in L["rooms"]), 1)}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args: print(__doc__); sys.exit(2)
    try: res = run(args[0])
    except Exception as e: res = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res))
    sys.exit(0 if res.get("ok") else (3 if res.get("error") == "budget cap reached" else 1))
