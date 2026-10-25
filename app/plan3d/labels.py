"""Training labels for fine-tuning the wall model (cubi.py) on our plans, without hand painting: a reviewer (a Claude subagent)
looks at the model's prediction over the plan and flags what is wrong in coarse plan-percent coordinates; this file snaps
each flag to the drawn ink at pixel precision and writes the corrected masks. Claude decides WHAT is wrong; the image decides
exactly WHERE.

  labels.py split                      -> labels/split.json (20 held-out test plans from 20 buildings, 300 training plans)
  labels.py images [plans...]          -> labels/review/<id>.jpg (prediction overlay + percent grid) for the reviewer
  [CUBI_TAG=ft1] labels.py score     -> held-out IoU / F1 of walls, windows, doors against the corrected labels
  labels.py apply [plans...]           -> next to each plan: cubi_<stem>_label.npz (wall, window, door, ignore) from
                                          labels/review/<id>.json; labels/check/<id>.jpg shows before | after
Review JSON (percent of the review image, x right, y down):
  {"usable": bool, "missing_walls": [[x0,y0,x1,y1]], "extra_walls": [[x0,y0,x1,y1]], "missing_windows": [[x0,y0,x1,y1]],
   "extra_windows": [[...]], "missing_doors": [[x0,y0,x1,y1]], "extra_doors": [[...]], "exclude": [[...]], "notes": str}
  missing_* are segments along the wall (end points); extra_* and exclude are boxes."""
import sys, json, glob, pathlib, random
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; LAB = HERE / "labels"
sys.path.insert(0, str(HERE)); import cubi

def plan_id(path): p = pathlib.Path(path); return f"{p.parts[-3]}_{p.stem}"
def label_path(path): p = pathlib.Path(path); return p.parent / f"cubi_{p.stem}_label.npz"

def split(n_test=20, n_train=300, per_building=8, seed=7):
    idx = json.load(open(HERE / "layouts" / "index.json")); rng = random.Random(seed)
    plans = []
    for d in idx:
        p = ROOT / "feasibility" / "listings" / d["listing"] / "plans" / pathlib.Path(d["plan_image"]).name
        if cubi.load(str(p)) is not None: plans.append((d["listing"], str(p)))
    by = {}
    for lid, p in plans: by.setdefault(lid, []).append(p)
    blds = sorted(by); rng.shuffle(blds)
    test = [rng.choice(by[b]) for b in blds[:n_test]]
    pool = []
    for b in sorted(by):
        cand = [p for p in by[b] if p not in test]; rng.shuffle(cand); pool += cand[:per_building]
    rng.shuffle(pool); train = pool[:n_train]
    LAB.mkdir(exist_ok=True); json.dump({"test": test, "train": train, "seed": seed}, open(LAB / "split.json", "w"), indent=1)
    print(f"[labels] split: {len(test)} test plans from {len(set(pathlib.Path(p).parts[-3] for p in test))} buildings, {len(train)} train plans from {len(set(pathlib.Path(p).parts[-3] for p in train))} buildings")

def view_box(P, pad=0.03):
    """The reviewed region (inference px): the union of the drawing levels, padded."""
    H, W = P["rooms"].shape
    if not P["levels"]: return 0, 0, W, H
    x0 = min(L["bbox"][0] for L in P["levels"]); y0 = min(L["bbox"][1] for L in P["levels"]); x1 = max(L["bbox"][2] for L in P["levels"]); y1 = max(L["bbox"][3] for L in P["levels"])
    px, py = int(pad * W), int(pad * H); return max(0, x0 - px), max(0, y0 - py), min(W, x1 + px), min(H, y1 + py)

def overlay(path, wall, window, door, box, max_side=1400, grid=True):
    P = cubi.load(path); x0, y0, x1, y1 = box
    src = np.asarray(Image.open(path).convert("RGB").resize(tuple(P["size"]), Image.LANCZOS)).astype(np.float32)[y0:y1, x0:x1]
    o = 0.6 * src + 0.4 * 255   # plan lightened: an unpainted wall stays clearly grey/black, a painted one turns clearly coloured
    for m, col in ((wall, (235, 20, 20)), (window, (0, 150, 255)), (door, (0, 190, 60))):
        m = m[y0:y1, x0:x1].astype(bool); o[m] = 0.25 * src[m] + 0.75 * np.array(col)
    im = Image.fromarray(o.astype(np.uint8)); z = max_side / max(im.size); im = im.resize((int(im.width * z), int(im.height * z)), Image.LANCZOS)
    if not grid: return im
    W, H = im.size; m = 34; out = Image.new("RGB", (W + 2 * m, H + 2 * m), "white"); out.paste(im, (m, m)); d = ImageDraw.Draw(out)
    try: font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    except Exception: font = None
    for k in range(0, 101, 5):
        x = m + W * k / 100; y = m + H * k / 100; strong = k % 10 == 0
        d.line([(x, m), (x, m + H)], fill=(120, 120, 255) if strong else (200, 200, 255), width=1)
        d.line([(m, y), (m + W, y)], fill=(120, 120, 255) if strong else (200, 200, 255), width=1)
        if strong:
            for (tx, ty) in ((x - 8, 4), (x - 8, m + H + 6)): d.text((tx, ty), str(k), fill=(0, 0, 160), font=font)
            for (tx, ty) in ((2, y - 8), (m + W + 4, y - 8)): d.text((tx, ty), str(k), fill=(0, 0, 160), font=font)
    return out

def review_image(path, out):
    P = cubi.load(path); crop = P["crop"].astype(bool); box = view_box(P)
    overlay(path, (P["rooms"] == cubi.WALL) & crop, (P["icons"] == cubi.WINDOW) & crop, (P["icons"] == cubi.DOOR) & crop, box).save(out, quality=90)
    return box

# ------------------------------------------------------------------ snapping ------------------------------------------------
def _seg_mask(shape, p0, p1, width):
    m = np.zeros(shape, np.uint8); cv2.line(m, tuple(int(v) for v in p0), tuple(int(v) for v in p1), 1, max(1, int(width))); return m

def _box_mask(shape, b):
    m = np.zeros(shape, np.uint8); x0, y0, x1, y1 = [int(v) for v in b]; m[min(y0, y1):max(y0, y1), min(x0, x1):max(x0, x1)] = 1; return m

def snap_wall(gray, p0, p1, T):
    """A wall along p0-p1: the drawn strokes in a corridor around the segment that run along it (text and hairline arcs
    dropped), double outlines closed into one band. Falls back to a T-thick band on the segment when there is no ink."""
    corr = _seg_mask(gray.shape, p0, p1, 5 * T)
    ink = ((gray < 215) & (corr > 0)).astype(np.uint8)
    d = np.array(p1, float) - np.array(p0, float); L = np.hypot(*d)
    if L < 2: return np.zeros_like(ink)
    horiz = abs(d[0]) >= abs(d[1]); k = max(3, int(min(L * 0.5, 4 * T)))
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1) if horiz else (1, k))
    along = cv2.morphologyEx(ink, cv2.MORPH_OPEN, ker)   # strokes running along the wall direction
    if along.sum() < 0.3 * L:   # nothing drawn there: trust the reviewer's line
        return _seg_mask(gray.shape, p0, p1, T) & corr
    kc = max(3, int(T)) | 1; band = cv2.morphologyEx(along, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kc, kc)))
    # keep the band nearest to the reviewer's line (a parallel counter edge in the corridor is not the wall)
    n, lab, st, cen = cv2.connectedComponentsWithStats(band, 8)
    if n <= 2: return band
    u = d / L; nrm = np.array([-u[1], u[0]]); best = min(range(1, n), key=lambda i: abs(np.dot(cen[i] - np.array(p0, float), nrm)) - 0.001 * st[i, cv2.CC_STAT_AREA])
    return (lab == best).astype(np.uint8)

def apply(path, R, box):
    """Corrected (wall, window, door, ignore) masks at inference size from the model prediction and the review R."""
    P = cubi.load(path); H, W = P["rooms"].shape; crop = P["crop"].astype(bool); T = cubi.TARGET_T
    gray = np.asarray(Image.open(path).convert("L").resize(tuple(P["size"]), Image.LANCZOS))
    wall = ((P["rooms"] == cubi.WALL) & crop).astype(np.uint8); win = ((P["icons"] == cubi.WINDOW) & crop).astype(np.uint8); door = ((P["icons"] == cubi.DOOR) & crop).astype(np.uint8)
    x0, y0, x1, y1 = box; bw, bh = x1 - x0, y1 - y0
    pt = lambda x, y: (x0 + x / 100 * bw, y0 + y / 100 * bh)
    bx = lambda b: (*pt(b[0], b[1]), *pt(b[2], b[3]))
    ignore = np.ones((H, W), np.uint8); ignore[y0:y1, x0:x1] = 0   # only the reviewed region is labelled
    thick_ink = cv2.morphologyEx((gray < 200).astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(2, int(T * 0.45)),) * 2))
    for b in R.get("exclude", []): m = _box_mask((H, W), bx(b)) > 0; wall[m] = win[m] = door[m] = 0
    for b in R.get("extra_walls", []):   # remove predicted wall without a heavy stroke under it (real walls are drawn heavy)
        m = (_box_mask((H, W), bx(b)) > 0) & (thick_ink == 0); wall[m] = 0; win[m] = 0; door[m] = 0
    for b in R.get("extra_windows", []): win[_box_mask((H, W), bx(b)) > 0] = 0
    for b in R.get("extra_doors", []): door[_box_mask((H, W), bx(b)) > 0] = 0
    for s in R.get("missing_walls", []): wall |= snap_wall(gray, pt(s[0], s[1]), pt(s[2], s[3]), T)
    for key, dst in (("missing_windows", win), ("missing_doors", door)):
        for s in R.get(key, []):   # an opening sits in the wall line: the wall band along the segment, marked as opening too
            band = snap_wall(gray, pt(s[0], s[1]), pt(s[2], s[3]), T)
            if band.sum() < 0.5 * T * T: band = _seg_mask((H, W), pt(s[0], s[1]), pt(s[2], s[3]), T)
            band = cv2.dilate(band, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))); dst |= band; wall |= band
    if not R.get("usable", True): ignore[:] = 1
    return wall, win, door, ignore

def apply_all(plans):
    (LAB / "check").mkdir(parents=True, exist_ok=True); n = 0
    for path in plans:
        rj = LAB / "review" / f"{plan_id(path)}.json"
        if not rj.exists(): continue
        R = json.load(open(rj)); meta = json.load(open(LAB / "review" / f"{plan_id(path)}.box.json"))
        wall, win, door, ign = apply(path, R, meta["box"])
        np.savez_compressed(label_path(path), wall=wall, window=win, door=door, ignore=ign, box=np.array(meta["box"]))
        P = cubi.load(path); crop = P["crop"].astype(bool); box = meta["box"]
        a = overlay(path, (P["rooms"] == cubi.WALL) & crop, (P["icons"] == cubi.WINDOW) & crop, (P["icons"] == cubi.DOOR) & crop, box, max_side=900, grid=False)
        b = overlay(path, wall.astype(bool), win.astype(bool), door.astype(bool), box, max_side=900, grid=False)
        c = Image.new("RGB", (a.width + b.width + 10, max(a.height, b.height)), "white"); c.paste(a, (0, 0)); c.paste(b, (a.width + 10, 0)); c.save(LAB / "check" / f"{plan_id(path)}.jpg", quality=85); n += 1
    print(f"[labels] applied {n} reviews")

def score(plans, tag=None):
    """Held-out agreement of a prediction (zero-shot cache, or CUBI_TAG fine-tuned cache) with the corrected labels, on the
    reviewed region: IoU per class, and boundary-tolerant F1 (a pixel within 2 px of the other mask counts)."""
    acc = {k: {"i": 0, "u": 0, "pt": 0, "pn": 0, "lt": 0, "ln": 0} for k in ("wall", "window", "door")}; n = 0
    for path in plans:
        lp = label_path(path)
        if not lp.exists(): continue
        Lb = np.load(lp); P = cubi.load(path, tag)
        if P is None: continue
        if P["rooms"].shape != Lb["wall"].shape: print("[labels] size mismatch", path); continue
        ok = Lb["ignore"] == 0; crop = P["crop"].astype(bool); n += 1
        pred = {"wall": (P["rooms"] == cubi.WALL) & crop, "window": (P["icons"] == cubi.WINDOW) & crop, "door": (P["icons"] == cubi.DOOR) & crop}
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        for c in acc:
            a = pred[c] & ok; b = Lb[c].astype(bool) & ok
            acc[c]["i"] += int((a & b).sum()); acc[c]["u"] += int((a | b).sum())
            bd = cv2.dilate(b.astype(np.uint8), k3).astype(bool); ad = cv2.dilate(a.astype(np.uint8), k3).astype(bool)
            acc[c]["pt"] += int((a & bd).sum()); acc[c]["pn"] += int(a.sum()); acc[c]["lt"] += int((b & ad).sum()); acc[c]["ln"] += int(b.sum())
    out = {"plans": n, "weights": tag or "zero-shot"}
    for c, v in acc.items():
        pr = v["pt"] / max(1, v["pn"]); rc = v["lt"] / max(1, v["ln"])
        out[c] = {"iou": round(v["i"] / max(1, v["u"]), 3), "precision": round(pr, 3), "recall": round(rc, 3), "f1": round(2 * pr * rc / max(1e-9, pr + rc), 3)}
    return out

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit()
    if a[0] == "split": split(); sys.exit()
    plans = a[1:] or (lambda S: S["test"] + S["train"])(json.load(open(LAB / "split.json")))
    if a[0] == "images":
        (LAB / "review").mkdir(parents=True, exist_ok=True)
        for p in plans:
            box = review_image(p, LAB / "review" / f"{plan_id(p)}.jpg"); json.dump({"plan": p, "box": [int(v) for v in box]}, open(LAB / "review" / f"{plan_id(p)}.box.json", "w"))
        print(f"[labels] {len(plans)} review images in {LAB / 'review'}")
    elif a[0] == "apply": apply_all(plans)
    elif a[0] == "score":   # held-out test plans by default
        test = a[1:] or json.load(open(LAB / "split.json"))["test"]; r = score(test, cubi.TAG or None); print(json.dumps(r, indent=1))
        (LAB / "scores").mkdir(exist_ok=True); json.dump(r, open(LAB / "scores" / f"{cubi.TAG or 'zeroshot'}.json", "w"), indent=1)
