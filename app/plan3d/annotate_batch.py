"""Re-run the engine WITH the VLM steps (reader + repair + annotation) for the given units, then rescale and re-export rooms.
Usage: annotate_batch.py <units file>"""
import sys, json, pathlib, subprocess, os
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")
units = [u.strip() for u in open(sys.argv[1]) if u.strip()]; env = dict(os.environ, REPAIR="1")
for u in units:
    L = json.load(open(HERE / "layouts" / f"{u}.json")); plan = L["plan_image"]
    r = subprocess.run([PY, str(HERE / "plan_engine.py"), "layout", plan], capture_output=True, text=True, cwd=str(ROOT), env=env)
    ok = (HERE / "layouts" / f"{u}.json").exists() and '"review"' in open(HERE / "layouts" / f"{u}.json").read()
    subprocess.run([PY, str(HERE / "rescale.py"), u], capture_output=True, text=True, cwd=str(ROOT))
    subprocess.run([PY, str(HERE / "rooms_export.py"), u], capture_output=True, text=True, cwd=str(ROOT))
    L2 = json.load(open(HERE / "layouts" / f"{u}.json")); print(f"[annot] {u}: rooms {[r['name'] for r in L2['rooms']][:6]} fixtures {len(L2['fixtures'])} usd {L2.get('review',{}).get('usd')} {'' if ok else r.stderr[-200:]}", flush=True)
subprocess.run([PY, str(HERE / "reindex.py")], capture_output=True, text=True, cwd=str(ROOT)); print("[annot] done")
