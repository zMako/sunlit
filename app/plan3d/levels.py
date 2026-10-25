"""Multi-level (townhouse) plans: the drawings cubi.py found on one plan image become stacked levels.

  - every wall / room / fixture gets "level"; upper levels are shifted (x, z) so they sit over the level below (template
    match of the predicted wall masks); layout["levels"] = [{id, name, elevation_m, plan_offset_m}]
  - which drawing is the lower level: "UP" vs "DN" stair labels and level captions (ENTRY / LOWER / FIRST vs UPPER / SECOND)
    from the plan text (room_names.ocr); without stair or level words two drawings are variants (TYPICAL / ALTERNATE), not
    floors, and the unit is left alone
  - stairs: tread lines (a run of short parallel lines, evenly spaced 18-35 cm) next to the UP / DN label; else the small
    room that holds the label. layout["stairs"] = [{from_level, to_level, rect: {x, z, w, d, rot_deg}, climb: [ux, uz]}];
    rooms of the upper level get "floor_cut" (floor polygon minus the stairwell), rooms below get "ceiling_cut"

  levels.py [units ...]   (default: every unit whose plan has two or more drawings)"""
import sys, json, re, math, pathlib, subprocess
import numpy as np, cv2
from PIL import Image
from shapely.geometry import Polygon, box as sbox, Point
from shapely import affinity
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")
sys.path.insert(0, str(HERE)); import cubi, room_names

LOWER = re.compile(r"\b(ENTRY|GROUND|LOWER|FIRST|1ST|MAIN|STREET)\b"); UPPER = re.compile(r"\b(UPPER|SECOND|2ND|THIRD|3RD|LOFT|TOP)\b")
LEVELW = re.compile(r"\b(LEVEL|FLOOR|STORY|STOREY)\b"); UPW = re.compile(r"^(UP)\.?$"); DNW = re.compile(r"^(DN|DOWN)\.?$")

def plan_path(L): return L["plan_image"] if L["plan_image"].startswith("/") else str(ROOT / L["plan_image"])

def frames(L):
    sc = L["scale"]; m, (ox, oy), s = sc["m_per_px"], sc["origin_px"], sc.get("image_scale", 1) or 1
    to_px = lambda x, z: ((x / m + ox) / s, (z / m + oy) / s); mpp = m * s   # metres per original px
    to_m = lambda px, py: ((px * s - ox) * m, (py * s - oy) * m)
    return to_px, to_m, mpp

def words_px(L):
    W, H = Image.open(plan_path(L)).size; out = []
    for w in room_names.ocr(plan_path(L)):
        x, y, bw, bh = w["box"]; out.append({"t": w["text"].upper().strip(), "x": (x + bw / 2) * W, "y": (1 - y - bh / 2) * H, "h": bh * H})
    return out

def level_boxes(L):
    P, _ = cubi.load_engine(plan_path(L)); k = P["k"]
    return [[v / k for v in lv["bbox"]] for lv in P["levels"]], P

def assign(L, boxes):
    to_px, _, _ = frames(L)
    def which(px, py):
        best, bd = 0, 1e18
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            dx = max(x0 - px, 0, px - x1); dy = max(y0 - py, 0, py - y1); d = dx * dx + dy * dy
            if d < bd: best, bd = i, d
        return best
    for w in L["walls"]: w["level"] = which(*to_px((w["a"][0] + w["b"][0]) / 2, (w["a"][1] + w["b"][1]) / 2))
    for r in L["rooms"]: c = Polygon(r["polygon"]).buffer(0).representative_point(); r["level"] = which(*to_px(c.x, c.y))
    for f in L.get("fixtures", []): f["level"] = which(*to_px(f["rect"]["x"], f["rect"]["z"]))

def order_levels(boxes, words):
    """drawing indices from the lowest level up, the names, and whether this is a multi-level plan at all"""
    info = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        h = y1 - y0; inside = [w for w in words if x0 <= w["x"] <= x1 and y0 <= w["y"] <= y1]
        near = [w for w in words if x0 - 0.05 * (x1 - x0) <= w["x"] <= x1 + 0.05 * (x1 - x0) and (y0 - 0.25 * h <= w["y"] <= y0 or y1 <= w["y"] <= y1 + 0.25 * h)
                and (LEVELW.search(w["t"]) or LOWER.search(w["t"]) or UPPER.search(w["t"]))]
        # the caption: the one OCR line closest to the drawing (a neighbour's caption can also fall in the search band)
        cap = min(near, key=lambda w: min(abs(w["y"] - y0), abs(w["y"] - y1)) + 0.3 * abs(w["x"] - (x0 + x1) / 2))["t"] if near else ""
        up = [w for w in inside if UPW.match(w["t"])]; dn = [w for w in inside if DNW.match(w["t"])]
        score = (2 if up else 0) - (2 if dn else 0) + (3 if LOWER.search(cap) else 0) - (3 if UPPER.search(cap) else 0)
        info.append({"i": i, "score": score, "caption": cap.title() if cap else None, "up": up, "dn": dn})
    multi = any(d["up"] or d["dn"] for d in info) or sum(1 for d in info if d["caption"] and LEVELW.search(d["caption"].upper())) >= 2
    order = [d["i"] for d in sorted(info, key=lambda d: (-d["score"], d["i"]))]
    return order, info, multi

def wall_mask(P, bbox_orig):
    k = P["k"]; x0, y0, x1, y1 = [int(round(v * k)) for v in bbox_orig]; m = ((P["rooms"] == cubi.WALL) & P["crop"].astype(bool))[y0:y1, x0:x1].astype(np.uint8)
    return cv2.dilate(m, np.ones((9, 9), np.uint8)).astype(np.float32), (x0, y0)

def align(P, base_box, box):
    """(dx, dy) in original px that moves drawing `box` onto `base_box`: template match of the dilated wall masks, searched
    over shifts up to 30% of the drawing size around the top-left alignment; falls back to centring the boxes"""
    A, (ax, ay) = wall_mask(P, base_box); B, (bx, by) = wall_mask(P, box); k = P["k"]
    mh, mw = int(0.3 * max(A.shape[0], B.shape[0])), int(0.3 * max(A.shape[1], B.shape[1]))
    canvas = np.zeros((max(A.shape[0], B.shape[0]) + 2 * mh, max(A.shape[1], B.shape[1]) + 2 * mw), np.float32); canvas[mh:mh + A.shape[0], mw:mw + A.shape[1]] = A
    if B.shape[0] > canvas.shape[0] or B.shape[1] > canvas.shape[1] or B.sum() == 0: return ((base_box[0] + base_box[2]) - (box[0] + box[2])) / 2, ((base_box[1] + base_box[3]) - (box[1] + box[3])) / 2, 0.0
    r = cv2.matchTemplate(canvas, B, cv2.TM_CCORR_NORMED); _, score, _, (lx, ly) = cv2.minMaxLoc(r)
    # B's top-left lands at canvas (lx, ly) = A-crop (lx - mw, ly - mh) = image (ax + lx - mw, ay + ly - mh); B now sits at (bx, by)
    return (ax + lx - mw - bx) / k, (ay + ly - mh - by) / k, float(score)

def has_open_below(bbox, words):
    x0, y0, x1, y1 = bbox; inside = " ".join(w["t"] for w in words if x0 <= w["x"] <= x1 and y0 <= w["y"] <= y1)
    return bool(re.search(r"OPEN", inside) and re.search(r"BELOW", inside))

def footprint(P, bbox_orig):
    """the drawing's footprint (inside of its outer walls, walls included) as a polygon in original px"""
    k = P["k"]; x0, y0, x1, y1 = [int(round(v * k)) for v in bbox_orig]; ks = int(cubi.TARGET_T * 6) | 1; pad = ks + 4   # padding wider than the kernel: the closing must not reach the flood seed
    m = ((P["rooms"] == cubi.WALL) & P["crop"].astype(bool))[y0:y1, x0:x1].astype(np.uint8)
    m = cv2.copyMakeBorder(m, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((ks, ks), np.uint8))   # bridge door / window gaps in the outline
    ff = m.copy(); msk = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8); cv2.floodFill(ff, msk, (0, 0), 2)
    inside = (ff != 2).astype(np.uint8); cs, _ = cv2.findContours(inside, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs: return None
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(float)
    poly = Polygon([((x - pad + x0) / k, (y - pad + y0) / k) for x, y in c]).buffer(0)
    return poly.simplify(2.0 / k) if poly.area > 0 else None

def treads(gray, cx, cy, R, mpp):
    """the stair next to a stair label at (cx, cy): tread-length straight lines (0.45-1.6 m, horizontal or vertical) grown
    into a cluster from the label outwards; its bounding box is the stair compartment (straight, L or winder stairs alike).
    -> (x0, y0, x1, y1, axis of the long side 'h'|'v') in original px, or None"""
    H, W = gray.shape; x0, y0, x1, y1 = int(max(0, cx - R)), int(max(0, cy - R)), int(min(W, cx + R)), int(min(H, cy + R))
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0: return None
    ink = (crop < 190).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(ink, 1, np.pi / 180, threshold=20, minLineLength=int(0.4 / mpp), maxLineGap=int(0.04 / mpp) + 1)
    if lines is None: return None
    segs = []
    for xa, ya, xb, yb in lines.reshape(-1, 4):
        dx, dy = abs(int(xb) - int(xa)), abs(int(yb) - int(ya)); ln = math.hypot(dx, dy) * mpp
        if 0.45 <= ln <= 1.6 and (dy <= 0.08 * dx or dx <= 0.08 * dy): segs.append((x0 + min(xa, xb), y0 + min(ya, yb), x0 + max(xa, xb), y0 + max(ya, yb)))
    if not segs: return None
    def dist(sg, bx):   # gap between a segment's bbox and a box
        return max(bx[0] - sg[2], 0, sg[0] - bx[2]) + max(bx[1] - sg[3], 0, sg[1] - bx[3])
    seed = (cx - 1.0 / mpp, cy - 1.0 / mpp, cx + 1.0 / mpp, cy + 1.0 / mpp); clus = [sg for sg in segs if dist(sg, seed) == 0]
    if not clus: return None
    bx = [min(s_[0] for s_ in clus), min(s_[1] for s_ in clus), max(s_[2] for s_ in clus), max(s_[3] for s_ in clus)]
    for _ in range(6):   # grow: treads within 0.35 m of the cluster, while the compartment stays stair-sized
        add = [sg for sg in segs if sg not in clus and dist(sg, bx) <= 0.35 / mpp]
        if not add: break
        nb = [min(bx[0], *[a[0] for a in add]), min(bx[1], *[a[1] for a in add]), max(bx[2], *[a[2] for a in add]), max(bx[3], *[a[3] for a in add])]
        if (nb[2] - nb[0]) * mpp > 4.5 or (nb[3] - nb[1]) * mpp > 4.5: break
        clus += add; bx = nb
    if len(clus) < 4: return None
    w_, h_ = (bx[2] - bx[0]) * mpp, (bx[3] - bx[1]) * mpp
    if max(w_, h_) < 1.2 or min(w_, h_) < 0.6: return None
    return (bx[0], bx[1], bx[2], bx[3], "h" if w_ >= h_ else "v")

def stairs_for(L, boxes, info, order, offsets_px):
    """one straight stair per level change, in the shared (aligned) metric frame"""
    to_px, to_m, mpp = frames(L); gray = np.asarray(Image.open(plan_path(L)).convert("L")); out = []
    for lo, hi in zip(order[:-1], order[1:]):
        cands = []
        for lv, key in ((lo, "up"), (hi, "dn"), (lo, "dn"), (hi, "up")):
            for w in next(d for d in info if d["i"] == lv)[key]:
                t = treads(gray, w["x"], w["y"], 3.0 / mpp, mpp)
                if t: cands.append((lv, t, w))
        if not cands:   # the small room that holds the label
            for lv, key in ((lo, "up"), (hi, "dn")):
                for w in next(d for d in info if d["i"] == lv)[key]:
                    for r in L["rooms"]:
                        if r.get("level") != lv or r["area_m2"] > 7: continue
                        poly = Polygon([to_px(x, z) for x, z in r["polygon"]])
                        if poly.contains(Point(w["x"], w["y"])):
                            bx0, by0, bx1, by1 = poly.bounds; cands.append((lv, (bx0, by0, bx1, by1, "h" if (bx1 - bx0) >= (by1 - by0) else "v"), w)); break
        if not cands: continue
        lv, (x0, y0, x1, y1, axis), w = cands[0]
        dx, dy = offsets_px[lv]; x0, x1, y0, y1, wx, wy = x0 + dx, x1 + dx, y0 + dy, y1 + dy, w["x"] + dx, w["y"] + dy
        (ax, az), (bx, bz) = to_m(x0, y0), to_m(x1, y1); cx, cz = (ax + bx) / 2, (az + bz) / 2; sx, sz = abs(bx - ax), abs(bz - az)
        # the stair climbs along the compartment's long side ('h': along x), starting at the label's end on the lower level
        lab_m = to_m(wx, wy)
        if axis == "h": climb = [1.0 if lab_m[0] < cx else -1.0, 0.0]; wid, run = sz, sx
        else: climb = [0.0, 1.0 if lab_m[1] < cz else -1.0]; wid, run = sx, sz
        if lv == hi: climb = [-climb[0], -climb[1]]   # the label was the DN one on the upper level: it marks the top
        run = max(run, 1.8); wid = min(max(wid, 0.8), 1.3)
        out.append({"from_level": order.index(lo), "to_level": order.index(hi), "rect": {"x": round(cx, 3), "z": round(cz, 3), "w": round(run if axis == "h" else wid, 3), "d": round(wid if axis == "h" else run, 3), "rot_deg": 0},
                    "climb": climb, "source": "treads" if axis and cands[0][1] is not None else "room"})
    return out

def apply_levels(L):
    boxes, P = level_boxes(L)
    if len(boxes) < 2: return None
    words = words_px(L); order, info, multi = order_levels(boxes, words)
    if not multi: return "variants"
    assign(L, boxes); to_px, to_m, mpp = frames(L); base = order[0]; offsets = {base: (0.0, 0.0)}; scores = {}
    for i in order[1:]: dx, dy, sc = align(P, boxes[base], boxes[i]); offsets[i] = (dx, dy); scores[i] = round(sc, 3)
    rank = {i: order.index(i) for i in order}; ceil = L.get("ceiling_m", 2.6)
    def sh(lv): return offsets[lv][0] * mpp, offsets[lv][1] * mpp   # metres
    for w in L["walls"]:
        ox, oz = sh(w["level"]); w["a"] = [round(w["a"][0] + ox, 3), round(w["a"][1] + oz, 3)]; w["b"] = [round(w["b"][0] + ox, 3), round(w["b"][1] + oz, 3)]; w["level"] = rank[w["level"]]
    for r in L["rooms"]:
        ox, oz = sh(r["level"]); r["polygon"] = [[round(x + ox, 3), round(z + oz, 3)] for x, z in r["polygon"]]; r["level"] = rank[r["level"]]
    for f in L.get("fixtures", []):
        ox, oz = sh(f["level"]); f["rect"]["x"] = round(f["rect"]["x"] + ox, 3); f["rect"]["z"] = round(f["rect"]["z"] + oz, 3); f["level"] = rank[f["level"]]
    L["levels"] = [{"id": rank[i], "name": next(d for d in info if d["i"] == i)["caption"] or f"Level {rank[i] + 1}", "elevation_m": round(rank[i] * ceil, 3),
                    "plan_offset_m": [round(-sh(i)[0], 3), round(-sh(i)[1], 3)], "align_score": scores.get(i)} for i in order]
    L["levels"].sort(key=lambda v: v["id"]); seen = set()
    for v in L["levels"]:
        if v["name"] in seen: v["name"] = f"Level {v['id'] + 1}"
        seen.add(v["name"])
    L["stairs"] = stairs_for(L, boxes, info, order, offsets)
    # the stairwell is open: the stair's own drawing (stringers, landing edges) and any wall crossing the compartment were read
    # as walls; cut every wall of the two levels at the compartment's edge (inside part removed, a crossing wall split in two)
    from shapely.geometry import LineString
    cut_any = []
    for st in L["stairs"]:
        R = st["rect"]; inner = sbox(R["x"] - R["w"] / 2 + 0.06, R["z"] - R["d"] / 2 + 0.06, R["x"] + R["w"] / 2 - 0.06, R["z"] + R["d"] / 2 - 0.06)
        walls = []; ops = []
        for w in L["walls"]:
            if w["level"] not in (st["from_level"], st["to_level"]): walls.append(w); continue
            seg = LineString([w["a"], w["b"]]); ln = seg.length
            if ln < 1e-6 or not seg.intersects(inner): walls.append(w); continue
            rest = seg.difference(inner); parts = [g for g in (rest.geoms if hasattr(rest, "geoms") else [rest]) if not g.is_empty and g.length > 0.15]
            cut_any.append(w["id"]); wo = [o for o in L["openings"] if o["wall"] == w["id"]]
            ax, az = w["a"]; ux, uz = (w["b"][0] - ax) / ln, (w["b"][1] - az) / ln
            for k, g in enumerate(parts):
                (x0, z0), (x1, z1) = list(g.coords)[0], list(g.coords)[-1]
                t0, t1 = sorted(((x0 - ax) * ux + (z0 - az) * uz, (x1 - ax) * ux + (z1 - az) * uz))
                nw = dict(w, id=f"{w['id']}_{k}", a=[round(ax + ux * t0, 3), round(az + uz * t0, 3)], b=[round(ax + ux * t1, 3), round(az + uz * t1, 3)]); walls.append(nw)
                for o in wo:   # openings that fit in this piece move onto it
                    if o["s0"] >= t0 - 0.02 and o["s1"] <= t1 + 0.02: ops.append(dict(o, wall=nw["id"], s0=round(o["s0"] - t0, 3), s1=round(o["s1"] - t0, 3)))
        keep_ids = {w["id"] for w in walls}
        L["walls"] = walls; L["openings"] = [o for o in L["openings"] if o["wall"] in keep_ids] + ops
        st["walls_cut"] = sorted(set(cut_any))
    # each level's footprint (metres, shared frame): its floor slab (levels above ground) and ceiling slab, minus stairwells
    holes = {}
    for st in L["stairs"]:
        R = st["rect"]; h = sbox(R["x"] - R["w"] / 2, R["z"] - R["d"] / 2, R["x"] + R["w"] / 2, R["z"] + R["d"] / 2)
        holes.setdefault(("floor", st["to_level"]), []).append(h); holes.setdefault(("ceiling", st["from_level"]), []).append(h)
    def rings(g):
        geoms = list(g.geoms) if hasattr(g, "geoms") else [g]
        return [{"outer": [[round(x, 3), round(z, 3)] for x, z in q.exterior.coords[:-1]], "holes": [[[round(x, 3), round(z, 3)] for x, z in hh.coords[:-1]] for hh in q.interiors]} for q in geoms if q.area > 0.05]
    open_below = {rank[i] for i in order if has_open_below(boxes[i], words)}   # mezzanines: the outline also holds a double-height void
    for i in order:
        if rank[i] in open_below: continue   # its floor is its rooms only (no slab), and the level below keeps room ceilings
        fp = footprint(P, boxes[i])
        if fp is None: continue
        dx, dy = offsets[i]; fm = Polygon([to_m(x + dx, y + dy) for x, y in fp.exterior.coords]).buffer(0)
        lv = next(v for v in L["levels"] if v["id"] == rank[i]); lv["footprint"] = rings(fm)
        for kind in ("floor", "ceiling"):
            if kind == "ceiling" and rank[i] + 1 in open_below: continue
            g = fm
            for h in holes.get((kind, rank[i]), []): g = g.difference(h)
            lv[f"{kind}_slab"] = rings(g)
    for st in L["stairs"]:   # stairwell: the upper level's floor and the lower level's ceiling are open over the stair
        R = st["rect"]; hole = sbox(R["x"] - R["w"] / 2, R["z"] - R["d"] / 2, R["x"] + R["w"] / 2, R["z"] + R["d"] / 2)
        for r in L["rooms"]:
            P_ = Polygon(r["polygon"]).buffer(0)
            if not P_.intersects(hole) or P_.intersection(hole).area < 0.05: continue
            cut = P_.difference(hole); geoms = list(cut.geoms) if hasattr(cut, "geoms") else [cut]
            rings = [{"outer": [[round(x, 3), round(z, 3)] for x, z in g.exterior.coords[:-1]], "holes": [[[round(x, 3), round(z, 3)] for x, z in h.coords[:-1]] for h in g.interiors]} for g in geoms if g.area > 0.05]
            if r["level"] == st["to_level"]: r["floor_cut"] = rings
            if r["level"] == st["from_level"]: r["ceiling_cut"] = rings
    return "levels"

def refresh_names(L):
    """level names from the plan captions again (geometry untouched)"""
    boxes, P = level_boxes(L); order, info, _ = order_levels(boxes, words_px(L)); seen = set()
    for rank, i in enumerate(order):
        lv = next((v for v in L["levels"] if v["id"] == rank), None); cap = next(d for d in info if d["i"] == i)["caption"]
        name = cap if cap and cap not in seen else f"Level {rank + 1}"; n = rank + 1
        while name in seen: n += 1; name = f"Level {n}"
        seen.add(name)
        if lv: lv["name"] = name

if __name__ == "__main__":
    idx_f = HERE / "layouts" / "index.json"; idx = json.load(open(idx_f)); by = {d["unit"]: d for d in idx}
    if "--fix-open" in sys.argv:   # units stacked before the mezzanine rule: drop the slabs over open-to-below voids
        for f in sorted((HERE / "layouts").glob("*.json")):
            if f.name == "index.json": continue
            L = json.load(open(f))
            if not L.get("levels"): continue
            boxes, P = level_boxes(L); order, _, _ = order_levels(boxes, words_px(L)); words = words_px(L); hit = []
            for rank, i in enumerate(order):
                if has_open_below(boxes[i], words):
                    lv = next(v for v in L["levels"] if v["id"] == rank); lv.pop("floor_slab", None); hit.append(rank)
                    below = next((v for v in L["levels"] if v["id"] == rank - 1), None)
                    if below: below.pop("ceiling_slab", None)
            if hit: json.dump(L, open(f, "w"), indent=1); print(f"[levels] {L['unit']}: open to below on level(s) {hit}")
        sys.exit()
    if "--names" in sys.argv:
        for f in sorted((HERE / "layouts").glob("*.json")):
            if f.name == "index.json": continue
            L = json.load(open(f))
            if not L.get("levels"): continue
            refresh_names(L); json.dump(L, open(f, "w"), indent=1); print(f"[levels] {L['unit']}: {[v['name'] for v in L['levels']]}")
        sys.exit()
    units = sys.argv[1:]
    if not units:
        for d in idx:
            P, _ = cubi.load_engine(str(ROOT / "feasibility/listings" / d["listing"] / "plans" / pathlib.Path(d["plan_image"]).name))
            if P and len(P["levels"]) >= 2 and d.get("walls_from"): units.append(d["unit"])
    stats = {}
    for u in units:
        f = HERE / "layouts" / f"{u}.json"; L = json.load(open(f))
        if L.get("levels"): stats["already"] = stats.get("already", 0) + 1; continue
        try: res = apply_levels(L)
        except Exception as e: print(f"[levels] {u}: {type(e).__name__} {e}"); continue
        stats[res] = stats.get(res, 0) + 1
        if res != "levels": continue
        json.dump(L, open(f, "w"), indent=1)
        subprocess.run([PY, str(HERE / "rooms_export.py"), u], capture_output=True, text=True, cwd=str(ROOT))
        if u in by: by[u]["levels"] = len(L["levels"]); by[u]["stairs"] = len(L["stairs"])
        print(f"[levels] {u}: {[(v['name'], v['elevation_m'], v['align_score']) for v in L['levels']]} stairs {[(s['rect'], s['climb']) for s in L['stairs']]}")
    json.dump(idx, open(idx_f, "w"), indent=1); print(f"[levels] {stats}")
