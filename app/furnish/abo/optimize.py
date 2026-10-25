"""Optimisation pass: models/<id>.glb -> models_opt/<id>.glb via gltf-transform (Draco geometry + WebP textures <=1024 px; no KTX2). Resumable.
   Writes raw/opt.json {id: [orig_bytes, opt_bytes, ok]}. Run: feasibility/.venv/bin/python -I optimize.py"""
import subprocess, pathlib, json, concurrent.futures as cf
H = pathlib.Path(__file__).resolve().parent; BIN = str(H / "raw/node/node_modules/.bin/gltf-transform"); (H / "models_opt").mkdir(exist_ok=True)
R = H / "raw/opt.json"; res = json.load(open(R)) if R.exists() else {}
def one(g):
    i = g.stem; o = H / f"models_opt/{i}.glb"
    if i in res and o.exists(): return i, res[i]
    p = subprocess.run([BIN, "optimize", str(g), str(o), "--compress", "draco", "--texture-compress", "webp", "--texture-size", "1024"], capture_output=True, text=True)
    ok = p.returncode == 0 and o.exists() and subprocess.run([BIN, "inspect", str(o)], capture_output=True).returncode == 0
    if not ok: o.unlink(missing_ok=True)
    return i, [g.stat().st_size, o.stat().st_size if ok else None, ok]
files = sorted(H.glob("models/*.glb"))
with cf.ThreadPoolExecutor(4) as ex:
    for n, (i, r) in enumerate(ex.map(one, files)):
        res[i] = r
        if n % 25 == 0: json.dump(res, open(R, "w")); print(n, len(files), flush=True)
json.dump(res, open(R, "w")); print("done", len(res))
