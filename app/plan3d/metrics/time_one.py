"""One timed run, in a fresh process (so imports count): plan image -> layout JSON (plan_engine.run with use_reader=False, i.e.
`plan_engine.py layout <plan> --novlm`, the geometry-only path, no Claude calls) -> per-room JSON (rooms_export.export).
Writes only under <out_dir>. Prints one JSON line with stage timings in seconds. Usage: time_one.py <plan image> <out_dir>"""
import time; T0 = time.perf_counter()
import sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent; P3 = HERE.parent; sys.path.insert(0, str(P3))
plan, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); (out / "layouts").mkdir(parents=True, exist_ok=True); (out / "rooms").mkdir(exist_ok=True)
import plan_engine as pe, rooms_export as rx
T1 = time.perf_counter()
listing = plan.parts[-3]; unit = f"{listing}_{plan.stem}"; res = {"unit": unit}
try:
    L, path = pe.run(plan, listing, unit, out / "layouts", use_reader=False); T2 = time.perf_counter()
    rx.HERE, rx.ROOMS = out, out / "rooms"          # read the layout we just wrote, write rooms into out/rooms (never app/rooms)
    rooms = rx.export(unit); T3 = time.perf_counter()
    res.update(ok=True, rooms=len(L["rooms"]), exported=len(rooms), import_s=T1 - T0, layout_s=T2 - T1, rooms_export_s=T3 - T2)
except Exception as e:
    T2 = time.perf_counter(); res.update(ok=False, error=f"{type(e).__name__}: {str(e)[:100]}", import_s=T1 - T0, layout_s=T2 - T1)
res["process_s"] = time.perf_counter() - T0
print(json.dumps(res))
