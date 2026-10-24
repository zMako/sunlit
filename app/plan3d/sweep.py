"""Geometry-only sweep over every plan image: per plan stats + a contact sheet per building of overlays. No VLM calls."""
import sys, json, glob, pathlib, traceback
import numpy as np, cv2
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; sys.path.insert(0, str(HERE)); import plan_engine as pe
OUT = HERE / "sweep"; OUT.mkdir(exist_ok=True); rows = []
for lid_dir in sorted(glob.glob(str(ROOT / "feasibility/listings/gs-*"))):
    lid = pathlib.Path(lid_dir).name; plans = sorted(p for p in glob.glob(lid_dir + "/plans/plan_*.[jp]*g")); tiles = []
    for p in plans:
        name = f"{lid}_{pathlib.Path(p).stem}"
        try:
            g, _, _ = pe.load_ink(p)
            if not pe.is_plan(g): rows.append({"unit": name, "status": "not_plan"}); continue
            E = pe.extract(p); L = pe.metric_layout(E, name, lid, p)
            total = sum(r["area_m2"] for r in L["rooms"]); kinds = {k: sum(1 for o in E["openings"] if o["kind"] == k) for k in ("window", "door", "opening")}
            rows.append({"unit": name, "status": "ok", "thick": E["thick"], "pieces": len(E["pieces"]), "rooms": len(E["rooms"]), "area_m2_doorscale": round(total, 1), **kinds, "blocks": len(E["blocks"]), "shape": list(g.shape)})
            rgb = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR); rng = np.random.RandomState(3)
            for r in E["rooms"]:
                col = rng.randint(80, 255, 3); m = E["room_labels"] == r["label"]; rgb[m] = (0.55 * rgb[m] + 0.45 * col).astype(np.uint8)
            for pc in E["pieces"]:
                x0, y0, x1, y1 = [int(v) for v in pe.ext_of(pc)]; cv2.rectangle(rgb, (x0, y0), (x1, y1), (30, 30, 30), -1)
            for o in E["openings"]:
                col = {"window": (255, 160, 0), "door": (0, 0, 255), "opening": (0, 200, 200)}[o["kind"]]
                if o["o"] == "h": cv2.line(rgb, (int(o["a"]), int(o["c"])), (int(o["b"]), int(o["c"])), col, 3)
                else: cv2.line(rgb, (int(o["c"]), int(o["a"])), (int(o["c"]), int(o["b"])), col, 3)
            cv2.putText(rgb, f"{pathlib.Path(p).stem} r{len(E['rooms'])} w{kinds['window']} d{kinds['door']}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2); tiles.append(rgb)
        except Exception as e:
            rows.append({"unit": name, "status": "error", "error": f"{type(e).__name__}: {str(e)[:120]}"})
    if tiles:   # contact sheet, up to 12 per building, 360 px tall
        tiles = tiles[:12]; H = 360; tiles = [cv2.resize(t, (int(t.shape[1] * H / t.shape[0]), H)) for t in tiles]
        cols = 4; rowsn = (len(tiles) + cols - 1) // cols; W = max(t.shape[1] for t in tiles)
        sheet = np.full((rowsn * H, cols * W, 3), 255, np.uint8)
        for i, t in enumerate(tiles): y, x = (i // cols) * H, (i % cols) * W; sheet[y:y + H, x:x + t.shape[1]] = t
        cv2.imwrite(str(OUT / f"{lid}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
    print(f"[sweep] {lid}: {len(plans)} plans, ok {sum(1 for r in rows if r['unit'].startswith(lid) and r['status']=='ok')}", flush=True)
json.dump(rows, open(OUT / "sweep.json", "w"), indent=1)
ok = [r for r in rows if r["status"] == "ok"]
print(f"[sweep] total {len(rows)} plans: ok {len(ok)}, not_plan {sum(1 for r in rows if r['status']=='not_plan')}, error {sum(1 for r in rows if r['status']=='error')}")
print(f"[sweep] rooms<2: {sum(1 for r in ok if r['rooms']<2)}, doors==0: {sum(1 for r in ok if r['door']==0)}, windows==0: {sum(1 for r in ok if r['window']==0)}")
