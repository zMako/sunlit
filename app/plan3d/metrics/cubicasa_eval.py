"""Run the untrained classical plan reader (plan_engine.extract + metric_layout, geometry only, no VLM) on the CubiCasa5K
sample fetched by cubicasa_fetch.py and score it against the SVG ground truth.
Per plan: room count (GT = every 'Space *' polygon except 'Space Outdoor*': terraces and balconies are not enclosed), room instance IoU (each GT room matched to the predicted region with the
largest overlap), interior (any-room vs not) pixel IoU, wall pixel IoU (our closed wall image vs the union of 'Wall' polygons),
door / window recall (a GT opening counts as found when a predicted opening segment of the right kind (door / window; *_any_found:
any kind incl. plain openings) passes within
max(1.5 wall thickness, 12 px) of its centre, along the same axis) and precision. Usage: cubicasa_eval.py [n_workers=6]
Writes data/cubicasa_results.json."""
import sys, json, pathlib, re, math, multiprocessing as mp
import numpy as np, cv2
import xml.etree.ElementTree as ET
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent))
DATA = HERE / "data" / "cubicasa5k"

def pts_of(el):
    for p in el.iter():
        if p.tag.endswith("polygon") and p.get("points"):
            v = [float(x) for x in re.split(r"[ ,]+", p.get("points").strip()) if x]
            return np.array(v[: len(v) // 2 * 2]).reshape(-1, 2)
    return None

def parse_svg(path):
    root = ET.parse(path).getroot(); rooms, walls, doors, windows = [], [], [], []
    # floors may carry a translate transform; CubiCasa models use matrix(1,0,0,1,tx,ty) on Floorplan groups
    def walk(el, off):
        tr = el.get("transform") or ""; m = re.match(r"matrix\(([^)]+)\)", tr)
        if m:
            a = [float(x) for x in re.split(r"[ ,]+", m.group(1).strip())]
            if len(a) == 6 and abs(a[0] - 1) < 1e-6 and abs(a[3] - 1) < 1e-6 and abs(a[1]) < 1e-6 and abs(a[2]) < 1e-6: off = (off[0] + a[4], off[1] + a[5])
        cls = el.get("class") or ""
        if el.tag.endswith("g"):
            if cls.startswith("Space "):
                p = pts_of(el)
                if p is not None and len(p) >= 3: rooms.append({"cls": cls[6:], "pts": p + off})
                return   # a space's children are labels and dimensions
            if cls.startswith("Wall"):
                p = pts_of(el)
                if p is not None: walls.append(p + off)
                for ch in el:
                    c2 = ch.get("class") or ""
                    if c2.startswith("Door") or c2.startswith("Window"):
                        q = pts_of(ch)
                        if q is not None: (doors if c2.startswith("Door") else windows).append(q + off)
                return
        for ch in el: walk(ch, off)
    walk(root, (0.0, 0.0))
    return rooms, walls, doors, windows

def raster(polys, shape):
    m = np.zeros(shape, np.uint8)
    for p in polys: cv2.fillPoly(m, [np.round(p).astype(np.int32)], 1)
    return m.astype(bool)

def opening_hit(gt, preds, tol):
    c = gt.mean(0); w, h = np.ptp(gt[:, 0]), np.ptp(gt[:, 1]); o = "h" if w >= h else "v"
    for q in preds:
        if q["o"] != o: continue
        along, across = (c[0], c[1]) if o == "h" else (c[1], c[0])
        if abs(across - q["c"]) <= tol and q["a"] - tol <= along <= q["b"] + tol: return True
    return False

def one(sid):
    import plan_engine as pe
    d = DATA / sid; img = d / "F1_scaled.png"; res = {"id": sid}
    try:
        rooms, walls, doors, windows = parse_svg(d / "model.svg")
        n_all = len(rooms); rooms = [r for r in rooms if not r["cls"].startswith("Outdoor")]   # terraces/balconies are not enclosed rooms
        H, W = cv2.imread(str(img), cv2.IMREAD_GRAYSCALE).shape
        res.update(gt_rooms=len(rooms), gt_spaces_incl_outdoor=n_all, gt_doors=len(doors), gt_windows=len(windows))
        try:
            E = pe.extract(str(img)); L = pe.metric_layout(E, sid, "cubicasa", str(img))
        except Exception as e:
            res.update(ok=False, error=f"{type(e).__name__}: {str(e)[:100]}"); return res
        s = E["scale"]; lab = cv2.resize(E["room_labels"].astype(np.int32), (W, H), interpolation=cv2.INTER_NEAREST)
        labels = [r["label"] for r in E["rooms"]]; res.update(ok=True, pred_rooms=len(labels))
        gt_lab = np.zeros((H, W), np.int32)
        for k, r in enumerate(rooms): cv2.fillPoly(gt_lab, [np.round(r["pts"]).astype(np.int32)], k + 1)
        ious = []; matched_pred = set()
        for k in range(len(rooms)):
            g = gt_lab == k + 1; ga = int(g.sum())
            if ga == 0: continue
            vals, cnt = np.unique(lab[g], return_counts=True); best = 0.0; bl = None
            for v, c in zip(vals, cnt):
                if v == 0 or v not in labels: continue
                iou = c / (ga + int((lab == v).sum()) - c)
                if iou > best: best, bl = iou, v
            ious.append(float(best))
            if best >= 0.5: matched_pred.add(bl)
        res["room_iou"] = ious; res["pred_rooms_matched"] = len(matched_pred)
        pin = np.isin(lab, labels); gin = gt_lab > 0
        res["interior_iou"] = float((pin & gin).sum() / max(1, (pin | gin).sum()))
        pw = cv2.resize(E["closed"].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool); gw = raster(walls, (H, W))
        res["wall_iou"] = float((pw & gw).sum() / max(1, (pw | gw).sum()))
        ops = [dict(o, c=o["c"] / s, a=o["a"] / s, b=o["b"] / s) for o in E["openings"]]; tol = max(1.5 * E["thick"] / s, 12.0)
        pd = [o for o in ops if o["kind"] == "door"]; pwn = [o for o in ops if o["kind"] == "window"]
        res["door_found"] = sum(opening_hit(g, pd, tol) for g in doors); res["window_found"] = sum(opening_hit(g, pwn, tol) for g in windows)
        res["door_any_found"] = sum(opening_hit(g, ops, tol) for g in doors); res["window_any_found"] = sum(opening_hit(g, ops, tol) for g in windows)
        res["pred_doors"] = len(pd); res["pred_windows"] = len(pwn)
        def prec(preds, gts):   # predicted openings that sit on some GT opening of the matching class
            hit = 0
            for q in preds:
                for g in gts:
                    if opening_hit(g, [q], tol): hit += 1; break
            return hit
        res["pred_doors_correct"] = prec(pd, doors); res["pred_windows_correct"] = prec(pwn, windows)
    except Exception as e:
        res.update(ok=False, error=f"{type(e).__name__}: {str(e)[:100]}")
    return res

if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    ids = [l.strip().strip("/").replace("/", "_") for l in (DATA / "sample.txt").read_text().splitlines() if l.strip()]
    ids = [i for i in ids if (DATA / i / "model.svg").exists() and (DATA / i / "F1_scaled.png").exists()]
    with mp.Pool(nw) as pool: out = pool.map(one, ids)
    json.dump(out, open(HERE / "data" / "cubicasa_results.json", "w"), indent=1)
    ok = [r for r in out if r.get("ok")]; print(f"[cubicasa] {len(out)} plans, engine ran on {len(ok)}")
