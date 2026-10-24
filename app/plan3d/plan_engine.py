"""Floor plan (raster) -> layout JSON (see LAYOUT_CONTRACT.md). Classical vision does the geometry: walls are the thick
strokes (everything else is thin), openings are gaps in walls, rooms are the enclosed white regions; the VLM names rooms and
fixtures and reviews an overlay. v0: wall extraction + debug overlay."""
import sys, json, pathlib, math
import numpy as np, cv2
from PIL import Image

def load_ink(path, max_side=1600):
    im = Image.open(path).convert("L"); s = min(1.0, max_side / max(im.size)); 
    if s < 1: im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    g = np.asarray(im).astype(np.uint8)
    # paper normalisation: the most common bright level is the paper; stretch it to 255 so thresholds hold on off-white scans
    hist = np.bincount(g.ravel(), minlength=256); bright = hist[150:]; paper = int(150 + bright.argmax()) if bright.sum() else 255
    if paper < 250: g = np.clip(g.astype(np.float32) * (255.0 / paper), 0, 255).astype(np.uint8)
    ink = (g < 190).astype(np.uint8)   # paper is near-white, light-grey fills are fixtures; walls are dark grey (SightMap) or black
    return g, ink, s

def wall_thickness(ink):
    """Stroke thickness of the long thick strokes: 2 x distance-transform value, sampled along the ink skeleton (length-weighted,
    so a filled block or a title does not dominate) and ignoring hairlines (dt <= 1.2)."""
    from skimage.morphology import skeletonize
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, 5); sk = skeletonize(ink.astype(bool)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sk, 8); H, W = ink.shape
    long_ids = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 0.08 * max(H, W)]   # strokes at least 8% of the image long: walls, not letters
    sel = np.isin(lab, long_ids) if long_ids else sk.astype(bool)
    v = dt[sel]; v = v[v > 1.2]
    if v.size < 50: v = dt[sk.astype(bool)]; v = v[v > 1.2]
    if v.size < 50: return 3.0
    return float(2 * np.percentile(v, 60))

def wall_thicknesses(ink):
    """One or two stroke thicknesses present among the long strokes (bimodal when exterior walls are drawn much heavier)."""
    from skimage.morphology import skeletonize
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, 5); sk = skeletonize(ink.astype(bool)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sk, 8); H, W = ink.shape
    long_ids = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 0.08 * max(H, W)]
    sel = np.isin(lab, long_ids) if long_ids else sk.astype(bool); v = dt[sel]; v = v[v > 1.2]
    if v.size < 50: return [wall_thickness(ink)]
    p25, p60, p75 = np.percentile(v, [25, 60, 75])
    if p75 >= 1.4 * p25 and p25 >= 1.4: return [float(2 * p25), float(2 * p75)]   # two wall weights (interior / exterior)
    return [float(2 * p60)]

def walls_mask(ink, thick):
    k = max(2, int(round(thick * 0.45)))
    w = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))   # removes hairlines, text, arcs
    n, lab, stats, _ = cv2.connectedComponentsWithStats(w, 8); keep = np.zeros_like(w)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= thick * thick * 2: keep[lab == i] = 1
    return keep

def wall_rects(wmask, thick):
    """Axis-aligned wall pieces: open the wall mask with a long horizontal kernel (keeps horizontal walls) and a long vertical
    one (keeps vertical walls); each connected component is one wall piece = (orientation, centre coordinate, start, end, thickness)."""
    L = max(int(thick * 2), int(0.01 * min(wmask.shape)), 6); pieces = []   # short jambs between openings must survive
    # filled blocks (fireplaces, columns, counters) are much thicker than walls: take them out first so a block glued to a wall
    # does not swallow it
    kb = int(max(thick * 2.2, 5)); blockmask = cv2.morphologyEx(wmask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kb, kb)))
    blocks = []; compact = np.zeros_like(blockmask)
    bn, blab, bstats, _ = cv2.connectedComponentsWithStats(blockmask, 8)
    for i in range(1, bn):
        x, y, w, h, a = bstats[i]
        if max(w, h) >= 3.5 * min(w, h): continue   # elongated: a thick (exterior) wall, keep it as wall
        blocks.append({"o": "h", "c": y + h / 2, "s0": int(x), "s1": int(x + w), "t": int(h), "x0": int(x), "y0": int(y), "x1": int(x + w), "y1": int(y + h), "block": True}); compact[blab == i] = 1
    core = cv2.erode(compact, cv2.getStructuringElement(cv2.MORPH_RECT, (int(thick) + 2, int(thick) + 2)))   # keep the rim: a wall glued to a block must survive
    wonly = cv2.subtract(wmask, core)
    for o, ker in (("h", cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1))), ("v", cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))):
        m = cv2.morphologyEx(wonly, cv2.MORPH_OPEN, ker); n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if o == "h" and w >= L: pieces.append({"o": "h", "c": y + h / 2, "s0": int(x), "s1": int(x + w), "t": int(h)})
            if o == "v" and h >= L: pieces.append({"o": "v", "c": x + w / 2, "s0": int(y), "s1": int(y + h), "t": int(w)})
    # merge pieces of the same wall split by thin crossings: same orientation, same centre line (within thick), touching or overlapping
    merged = []
    for pc in sorted(pieces, key=lambda q: (q["o"], q["c"], q["s0"])):
        for m in merged:
            if m["o"] == pc["o"] and abs(m["c"] - pc["c"]) <= thick * 0.7 and pc["s0"] <= m["s1"] + 2 and pc["s1"] >= m["s0"] - 2:
                m["s0"], m["s1"] = min(m["s0"], pc["s0"]), max(m["s1"], pc["s1"]); m["t"] = max(m["t"], pc["t"]); break
        else: merged.append(dict(pc))
    def inside_block(pc):
        x0, y0, x1, y1 = ext_of(pc)
        return any(x0 >= b["x0"] - 2 and x1 <= b["x1"] + 2 and y0 >= b["y0"] - 2 and y1 <= b["y1"] + 2 for b in blocks)
    merged = [m for m in merged if not inside_block(m)]   # rims of filled blocks are not walls
    for m in merged: m["block"] = False
    return merged, blocks

def walls_two_tone(g):
    """Plans often draw exterior walls in grey and interior walls in black with different thicknesses (SightMap). Extract
    walls per tone class and union them. Returns (mask, thickness used for geometry = the thinner class)."""
    cls = []
    for lo, hi in ((0, 60), (60, 190), (190, 238)):   # black, dark grey, light grey (SightMap exterior walls can be grey)
        ink = ((g >= lo) & (g < hi)).astype(np.uint8)
        if ink.sum() < 0.0015 * ink.size: continue
        for t in wall_thicknesses(ink):   # a tone class may hold two wall weights (thick exterior, thin interior): extract both
            m = walls_mask(ink, t)
            if m.sum() >= 0.0005 * ink.size: cls.append((int(m.sum()), t, m))
    if not cls:
        ink = (g < 190).astype(np.uint8); t = wall_thickness(ink); return walls_mask(ink, t), t
    cls.sort(key=lambda c: -c[0]); dom = cls[0]
    masks = [c for c in cls if c[0] >= 0.10 * dom[0] and 0.25 <= c[1] / dom[1] <= 4.0]   # minor classes join when they are plausible walls (thin interior next to heavy exterior)
    return np.clip(sum(c[2] for c in masks), 0, 1).astype(np.uint8), float(dom[1])   # union of weights, geometry parameters from the dominant one

def ext_of(pc):   # piece extent as (x0, y0, x1, y1) in pixels
    t = max(pc["t"], 2) / 2
    return (pc["s0"], pc["c"] - t, pc["s1"], pc["c"] + t) if pc["o"] == "h" else (pc["c"] - t, pc["s0"], pc["c"] + t, pc["s1"])

def classify_gap(thin, o, c, a, b, t, thick):
    """What fills a gap in a wall line: window (thin lines along the wall inside the band), door (a quarter-circle arc of
    radius ~gap hanging off one end, on one side), or a plain opening."""
    H, W = thin.shape; gap = b - a
    if gap < 2: return {"kind": "opening", "score": 0.0}
    th = cv2.dilate(thin, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    # window: fraction of positions along the gap that have thin ink within the wall band
    half = max(int(t / 2) + 1, 2); lo, hi = max(0, int(c - half)), min(H if o == "h" else W, int(c + half) + 1)
    band = th[lo:hi, int(a):int(b)] if o == "h" else th[int(a):int(b), lo:hi]
    along = band.any(axis=0) if o == "h" else band.any(axis=1); win = float(along.mean()) if along.size else 0.0
    # a window is drawn as 2-3 straight lines PARALLEL to the wall spanning the gap: require two distinct band rows/cols each
    # covering most of the gap (a tub outline or a text baseline gives one curved/short line only)
    cover = band.mean(axis=1) if o == "h" else band.mean(axis=0)
    strong = [i for i, v in enumerate(cover) if v >= 0.55]
    long_gap = gap > 6 * thick   # the strict tests target long false "windows" across rooms; short real windows keep the simple rule
    if long_gap and (len(strong) < 2 or (max(strong) - min(strong)) < 2): win = min(win, 0.3)
    # outside a window is paper: one side of the band must be nearly blank within 1..3 wall thicknesses
    def side_ink(sign):
        off0, off1 = int(c + sign * (half + thick)), int(c + sign * (half + 3 * thick)); lo_, hi_ = sorted((off0, off1)); lo_, hi_ = max(0, lo_), max(0, hi_)
        strip = th[lo_:hi_, int(a):int(b)] if o == "h" else th[int(a):int(b), lo_:hi_]
        return float(strip.mean()) if strip.size else 0.0
    if long_gap and min(side_ink(1), side_ink(-1)) > 0.02: win = min(win, 0.3)
    # door: sample a quarter circle from each end, each side
    best = 0.0; swing = None
    for end_pos, hinge in ((a, "start"), (b, "end")):
        for side in (1, -1):
            hits = 0; n = 0
            for k in range(1, 13):
                th_ang = math.radians(90 * k / 13); r = gap
                along_v = (1 if hinge == "start" else -1) * r * math.cos(th_ang); across = side * r * math.sin(th_ang)
                x, y = (end_pos + along_v, c + across) if o == "h" else (c + across, end_pos + along_v)
                xi, yi = int(round(x)), int(round(y))
                if 0 <= xi < W and 0 <= yi < H: n += 1; hits += int(th[yi, xi] > 0)
            sc = hits / n if n else 0
            if sc > best: best = sc; swing = f"{hinge}_{'pos' if side > 0 else 'neg'}"
    if win >= 0.55 and best < 0.5: return {"kind": "window", "score": round(win, 2)}
    if best >= 0.3 and gap >= 2.5 * thick: return {"kind": "door", "score": round(best, 2), "swing_raw": swing}
    if win >= 0.35 and gap <= 9 * thick: return {"kind": "window", "score": round(win, 2)}
    return {"kind": "opening", "score": round(max(win, best), 2)}

def bridge(pieces, shape, thick, ink=None, max_gap_frac=0.3):
    """Extend every piece along its axis past each end: to a COLLINEAR piece across a gap (that gap is an opening candidate,
    accepted when thin ink lies in it, i.e. a door arc / window lines / jambs, or when it is short), or to a perpendicular piece
    across a tiny corner gap. Returns the closed wall image and the opening candidates."""
    H, W = shape; max_gap = max_gap_frac * min(H, W); img = np.zeros((H, W), np.uint8); openings = []
    for pc in pieces:
        x0, y0, x1, y1 = ext_of(pc); cv2.rectangle(img, (int(x0), int(y0)), (int(math.ceil(x1)), int(math.ceil(y1))), 1, -1)
    thin = None
    if ink is not None: thin = cv2.subtract(ink, cv2.dilate(img, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))))   # ink here is the loose (<235) version: window lines are often light grey
    for i, pc in enumerate(pieces):
        for end in (0, 1):
            best = None
            for j, q in enumerate(pieces):
                if i == j: continue
                qx0, qy0, qx1, qy1 = ext_of(q)
                if q["o"] == pc["o"]:   # collinear continuation
                    if abs(q["c"] - pc["c"]) > max(2.0, thick * 0.35): continue
                    gap = (q["s0"] - pc["s1"]) if end == 1 else (pc["s0"] - q["s1"])
                    if 0 <= gap <= max_gap and (best is None or gap < best[0]): best = (gap, j, "collinear")
                else:   # perpendicular wall crossing the extension line: close a corner, or reach it across a window/door that runs into the corner
                    lo, hi = (qy0, qy1) if pc["o"] == "h" else (qx0, qx1)
                    if not (lo - thick <= pc["c"] <= hi + thick): continue
                    near = (qx0, qx1) if pc["o"] == "h" else (qy0, qy1)
                    gap = (near[0] - pc["s1"]) if end == 1 else (pc["s0"] - near[1])
                    if 0 <= gap <= 2.5 * thick and (best is None or gap < best[0]): best = (gap, j, "corner")
                    elif 2.5 * thick < gap <= max_gap and thin is not None and (best is None or gap < best[0]):
                        a_ = pc["s1"] if end == 1 else pc["s0"] - gap
                        cls = classify_gap(thin, pc["o"], pc["c"], a_, a_ + gap, max(pc["t"], 3), thick)
                        if cls["kind"] in ("window", "door"): best = (gap, j, "collinear")   # treated like a gap in the wall line
            if not best or best[0] <= thick * 0.5: continue
            gap, j, kind = best; a = pc["s1"] if end == 1 else pc["s0"] - gap; b = a + gap
            if kind == "collinear":
                cls = classify_gap(thin, pc["o"], pc["c"], a, b, max(pc["t"], pieces[j]["t"], 3), thick) if thin is not None else {"kind": "opening", "score": 0}
                if cls["kind"] == "opening" and gap > 9 * thick: continue      # a long gap with neither window lines nor a door arc is open space, not an opening
                openings.append({"piece": i, "o": pc["o"], "c": pc["c"], "a": float(a), "b": float(b), "t": pc["t"], "meets": j, **cls})
            if pc["o"] == "h": cv2.rectangle(img, (int(a), int(pc["c"] - thick / 2)), (int(math.ceil(b)), int(pc["c"] + thick / 2)), 1, -1)
            else: cv2.rectangle(img, (int(pc["c"] - thick / 2), int(a)), (int(pc["c"] + thick / 2), int(math.ceil(b))), 1, -1)
    # de-duplicate openings found from both sides
    uniq = []
    for o in openings:
        if not any(u["o"] == o["o"] and abs(u["c"] - o["c"]) <= thick and abs(u["a"] - o["a"]) <= thick and abs(u["b"] - o["b"]) <= thick for u in uniq): uniq.append(o)
    return img, uniq

def rooms_from(closed, thick):
    free = (closed == 0).astype(np.uint8); H, W = free.shape; ff = free.copy(); mask = np.zeros((H + 2, W + 2), np.uint8)
    for sx, sy in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, 0), (W // 2, H - 1), (0, H // 2), (W - 1, H // 2)):
        if ff[sy, sx]: cv2.floodFill(ff, mask, (sx, sy), 2)
    holes = (ff == 1).astype(np.uint8); n, lab, stats, _ = cv2.connectedComponentsWithStats(holes, 4); rooms = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= (6 * thick) ** 2: rooms.append({"label": i, "area_px": int(stats[i, 4]), "bbox": stats[i, :4].tolist()})
    return lab, rooms

def is_plan(g):
    """A floor plan is mostly paper (after normalisation): >= 45% near-white pixels and <= 35% ink. Photos and 3D renders fail."""
    white = float((g > 235).mean()); ink = float((g < 190).mean())
    return white >= 0.45 and ink <= 0.35   # coloured room fills are fine (1333 Gough); renders/photos are caught by softness()

def softness(path, max_side=800):
    """Ratio of soft gradients to hard edges: drawings ~0.4-1.5, 3D renders and photos > 3."""
    im = Image.open(path).convert("L"); im.thumbnail((max_side, max_side)); g = np.asarray(im).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3); m = np.sqrt(gx * gx + gy * gy) / 4
    soft = float(((m > 4) & (m < 30)).mean()); hard = float((m >= 60).mean()); return soft / max(hard, 1e-6)

def colourful(path, max_side=400):
    """Fraction of saturated pixels: drawings are grey-on-paper, photos and 3D renders are not."""
    im = Image.open(path).convert("RGB"); im.thumbnail((max_side, max_side)); a = np.asarray(im).astype(np.int16)
    sat = (a.max(2) - a.min(2)); return float((sat > 40).mean())

def extract(path, extra=None):
    """extra: list of {'type', 'x0','y0','x1','y1'} in image FRACTIONS to force-bridge (from the VLM review)."""
    g, ink, s = load_ink(path)
    if not is_plan(g) or softness(path) > 3.0: raise ValueError(f"not a floor plan (white {float((g > 235).mean()):.2f}, ink {float((g < 190).mean()):.2f}, mid {float(((g > 70) & (g < 215)).mean()):.2f}, colour {colourful(path):.2f})")
    wm, thick = walls_two_tone(g); pieces, blocks = wall_rects(wm, thick)
    loose = (g < 235).astype(np.uint8)
    closed, openings = bridge(pieces, g.shape, thick, ink=loose)
    # second pass: the typical door width is now known (confident arcs, plausible size); bridges much wider than a door that
    # are not windows are open space, not openings -> rebuild the closed image without them
    dmin, dmax = 0.025 * min(g.shape), 0.12 * min(g.shape)   # a door is 2.5-12% of the plan image regardless of wall weight
    sure = [o["b"] - o["a"] for o in openings if o["kind"] == "door" and o.get("score", 0) >= 0.5 and dmin <= (o["b"] - o["a"]) <= dmax]
    door_ref = float(np.median(sure)) if len(sure) >= 2 else None
    if door_ref:
        keep_o = [o for o in openings if o["kind"] == "window" or 0.6 * door_ref <= (o["b"] - o["a"]) <= 1.6 * door_ref]
        if len(keep_o) < len(openings):
            closed = np.zeros_like(closed)
            for pc in pieces:
                x0, y0, x1, y1 = ext_of(pc); cv2.rectangle(closed, (int(x0), int(y0)), (int(math.ceil(x1)), int(math.ceil(y1))), 1, -1)
            for o in keep_o:
                if o["o"] == "h": cv2.rectangle(closed, (int(o["a"]), int(o["c"] - thick / 2)), (int(math.ceil(o["b"])), int(o["c"] + thick / 2)), 1, -1)
                else: cv2.rectangle(closed, (int(o["c"] - thick / 2), int(o["a"])), (int(o["c"] + thick / 2), int(math.ceil(o["b"]))), 1, -1)
            # corner closures (perpendicular bridges) were not recorded as openings: redo them cheaply by closing tiny gaps
            closed = cv2.morphologyEx(closed, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (int(2.5 * thick) | 1, int(2.5 * thick) | 1)))
            openings = keep_o
    if extra:
        H, W = g.shape
        for e in extra:
            x0, y0, x1, y1 = int(e["x0"] * W), int(e["y0"] * H), int(e["x1"] * W), int(e["y1"] * H)
            # find the wall line the box sits on: the piece whose band intersects the box; bridge along that piece's axis across the box
            hit = None
            for i, pc in enumerate(pieces):
                px0, py0, px1, py1 = ext_of(pc)
                if pc["o"] == "h" and py0 - thick <= (y0 + y1) / 2 <= py1 + thick and not (x1 < px0 - 2 * thick or x0 > px1 + 2 * thick): hit = (i, pc); break
                if pc["o"] == "v" and px0 - thick <= (x0 + x1) / 2 <= px1 + thick and not (y1 < py0 - 2 * thick or y0 > py1 + 2 * thick): hit = (i, pc); break
            if hit is None:   # no piece: bridge the box itself along its long axis
                o = "h" if (x1 - x0) >= (y1 - y0) else "v"; c = (y0 + y1) / 2 if o == "h" else (x0 + x1) / 2; a, b = (x0, x1) if o == "h" else (y0, y1); i = -1
            else:
                i, pc = hit; o = pc["o"]; c = pc["c"]; a, b = (x0, x1) if o == "h" else (y0, y1)
            if o == "h": cv2.rectangle(closed, (int(a), int(c - thick / 2)), (int(b), int(c + thick / 2)), 1, -1)
            else: cv2.rectangle(closed, (int(c - thick / 2), int(a)), (int(c + thick / 2), int(b)), 1, -1)
            if i >= 0: openings.append({"piece": i, "o": o, "c": c, "a": float(a), "b": float(b), "t": pieces[i]["t"], "meets": i, "kind": e["type"], "score": 1.0, "from_review": True})
    lab, rooms = rooms_from(closed, thick)
    # keep pieces (and openings) that border a room; everything else is title, legend, logo
    roomsmask = np.isin(lab, [r["label"] for r in rooms]).astype(np.uint8); near = cv2.dilate(roomsmask, cv2.getStructuringElement(cv2.MORPH_RECT, (int(thick * 2) + 3, int(thick * 2) + 3)))
    keep = []
    for i, pc in enumerate(pieces):
        x0, y0, x1, y1 = [int(v) for v in ext_of(pc)]; sub = near[max(0, y0 - 1):y1 + 2, max(0, x0 - 1):x1 + 2]
        if sub.size and sub.any(): keep.append(i)
    kept = set(keep); remap = {old: new for new, old in enumerate(keep)}
    openings = [dict(o, piece=remap[o["piece"]], meets=remap[o["meets"]]) for o in openings if o["piece"] in kept and o["meets"] in kept]
    return {"gray": g, "ink": ink, "scale": s, "thick": thick, "pieces": [pieces[i] for i in keep], "piece_index": keep, "openings": openings, "room_labels": lab, "rooms": rooms, "closed": closed, "blocks": blocks}

def debug_overlay(path, out):
    E = extract(path); g = E["gray"]; rgb = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    rng = np.random.RandomState(3)
    for r in E["rooms"]:
        col = rng.randint(80, 255, 3); m = E["room_labels"] == r["label"]; rgb[m] = (0.55 * rgb[m] + 0.45 * col).astype(np.uint8)
    for pc in E["pieces"]:
        x0, y0, x1, y1 = [int(v) for v in ext_of(pc)]; cv2.rectangle(rgb, (x0, y0), (x1, y1), (30, 30, 30), -1)
    for pc in E["blocks"]:
        cv2.rectangle(rgb, (pc["x0"], pc["y0"]), (pc["x1"], pc["y1"]), (200, 0, 200), 2)
    for o in E["openings"]:
        col = {"window": (255, 160, 0), "door": (0, 0, 255), "opening": (0, 200, 200)}[o.get("kind", "opening")]
        if o["o"] == "h": cv2.line(rgb, (int(o["a"]), int(o["c"])), (int(o["b"]), int(o["c"])), col, 3)
        else: cv2.line(rgb, (int(o["c"]), int(o["a"])), (int(o["c"]), int(o["b"])), col, 3)
    cv2.imwrite(out, rgb)
    return {"thick_px": round(E["thick"], 1), "pieces": len(E["pieces"]), "openings": {k: sum(1 for o in E["openings"] if o.get("kind") == k) for k in ("window", "door", "opening")}, "rooms": len(E["rooms"]), "blocks": len(E["blocks"]), "shape": g.shape}

# ---------------------------------------------------------------- stage 2: metric layout -----------------------------------
DOOR_M = 0.86   # typical interior door clear width used as the primary scale reference

def rectilinear_polygon(mask, thick):
    """Region mask -> axis-aligned polygon in pixel coords (CCW in image coords, y down)."""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs: return None
    c = max(cs, key=cv2.contourArea); eps = max(1.5, thick * 0.6); ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2).astype(float)
    # snap to rectilinear: make each edge horizontal or vertical by averaging coordinates of near-aligned consecutive points
    pts = ap.tolist(); out = []
    for i, (x, y) in enumerate(pts):
        px, py = pts[i - 1]
        if abs(x - px) < abs(y - py): x = px if abs(x - px) <= thick else x     # mostly vertical edge: share x
        else: y = py if abs(y - py) <= thick else y
        out.append([x, y])
    # remove duplicate / collinear points
    clean = []
    for i, p_ in enumerate(out):
        a = out[i - 1]; b = out[(i + 1) % len(out)]
        if abs(p_[0] - a[0]) < 0.5 and abs(p_[1] - a[1]) < 0.5: continue
        if (abs(a[0] - p_[0]) < 0.5 and abs(p_[0] - b[0]) < 0.5) or (abs(a[1] - p_[1]) < 0.5 and abs(p_[1] - b[1]) < 0.5): continue
        clean.append(p_)
    return clean if len(clean) >= 4 else out

def metric_layout(E, unit, listing, plan_image, sqft=None, ceiling_m=2.6):
    """Pixel geometry -> LAYOUT_CONTRACT.md JSON. Scale from the median door gap (0.86 m); square footage checks it."""
    pieces, openings, thick, lab = E["pieces"], E["openings"], E["thick"], E["room_labels"]
    doors = [o for o in openings if o["kind"] == "door"]
    door_ref = float(np.median([o["b"] - o["a"] for o in doors])) if doors else None
    if door_ref:   # drop "doors" far wider than the typical door: those are false bridges across open space
        openings = [o for o in openings if not (o["kind"] == "door" and (o["b"] - o["a"]) > 1.8 * door_ref)]
        doors = [o for o in openings if o["kind"] == "door"]; door_ref = float(np.median([o["b"] - o["a"] for o in doors]))
    m_per_px = DOOR_M / door_ref if door_ref else None
    rooms_px = []
    for r in E["rooms"]:
        m = (lab == r["label"]); poly = rectilinear_polygon(m, thick)
        if poly: rooms_px.append({"label": r["label"], "poly": poly, "area_px": r["area_px"]})
    unit_area_px = float(sum(r["area_px"] for r in rooms_px))
    scale_from = []
    if m_per_px: scale_from.append("door_width")
    if sqft:
        m_sq = math.sqrt(sqft * 0.092903 / max(unit_area_px, 1)) if unit_area_px else None
        if m_sq:
            scale_from.append("sqft")
            if m_per_px: agreement = round(m_per_px / m_sq, 3); m_per_px = (m_per_px + m_sq) / 2 if 0.85 < agreement < 1.18 else m_per_px
            else: m_per_px = m_sq; agreement = None
    else: agreement = None
    if not m_per_px: m_per_px = 0.02   # last resort: assume ~2 cm per pixel (small plans); flagged
    xs = [ext_of(p)[0] for p in pieces] + [ext_of(p)[2] for p in pieces]; ys = [ext_of(p)[1] for p in pieces] + [ext_of(p)[3] for p in pieces]
    ox, oy = (min(xs) if xs else 0), (min(ys) if ys else 0)
    M = lambda x, y: [round((x - ox) * m_per_px, 3), round((y - oy) * m_per_px, 3)]
    H, W = lab.shape
    # exterior test: a piece is exterior if the free region on one side of it reaches the image border
    free = (E["closed"] == 0).astype(np.uint8); ff = free.copy(); mk = np.zeros((H + 2, W + 2), np.uint8)
    for sx, sy in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)):
        if ff[sy, sx] == 1: cv2.floodFill(ff, mk, (sx, sy), 2)
    outside = (ff == 2)
    walls = []
    for i, pc in enumerate(pieces):
        x0, y0, x1, y1 = ext_of(pc); t = max(pc["t"], thick * 0.6)
        if pc["o"] == "h": a, b = (pc["s0"], pc["c"]), (pc["s1"], pc["c"]); probe = [(int((x0 + x1) / 2), int(y0 - thick)), (int((x0 + x1) / 2), int(y1 + thick))]
        else: a, b = (pc["c"], pc["s0"]), (pc["c"], pc["s1"]); probe = [(int(x0 - thick), int((y0 + y1) / 2)), (int(x1 + thick), int((y0 + y1) / 2))]
        ext = any(0 <= px < W and 0 <= py < H and outside[py, px] for px, py in probe)
        walls.append({"id": f"w{i}", "a": M(*a), "b": M(*b), "thickness_m": round(t * m_per_px, 3), "exterior": bool(ext)})
    ops = []
    for k, o in enumerate(openings):
        pc = pieces[o["piece"]] if o["piece"] < len(pieces) else None
        wid = f"w{o['piece']}"; s0 = (o["a"] - pc["s0"]) * m_per_px if pc else 0; s1 = (o["b"] - pc["s0"]) * m_per_px if pc else 0
        rec = {"id": f"o{k}", "wall": wid, "type": o["kind"], "s0": round(s0, 3), "s1": round(s1, 3), "width_m": round(s1 - s0, 3)}
        if o["kind"] == "window": rec.update({"sill_m": 0.9, "height_m": 1.3})
        elif o["kind"] == "door":
            rec.update({"sill_m": 0.0, "height_m": 2.03})
            sw = o.get("swing_raw") or ""; hinge = "left" if sw.startswith("start") else "right"
            # which side is "in": the builder's left normal of a->b; pos side = +c direction (down for h: +y image; right for v: +x image)
            # for a->b along +x (h): left normal n = (-dz, dx) = (0, 1) in (x,z) = +y image => "pos" side is "in"
            # for a->b along +y (v): n = (-1, 0) => -x side is "in" => "pos" (+x) is "out"
            inside = ("in" if sw.endswith("pos") else "out") if o["o"] == "h" else ("out" if sw.endswith("pos") else "in")
            rec["swing"] = f"{inside}_{hinge}"
        else: rec.update({"sill_m": 0.0, "height_m": 2.1})
        ops.append(rec)
    rooms = []
    for k, r in enumerate(rooms_px):
        poly = [M(x, y) for x, y in r["poly"]]
        # CCW in x,z (z = image y, so image-CCW means CW in a y-up frame; the builder wants CCW in (x, z) plane as given: keep image order and let signed area decide)
        area = 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
        if area < 0: poly = poly[::-1]
        rooms.append({"id": f"r{k}", "name": f"Room {k + 1}", "type": "other", "polygon": poly, "area_m2": round(r["area_px"] * m_per_px ** 2, 2), "walls": [], "centre_px": [float(np.mean([p[0] for p in r["poly"]])), float(np.mean([p[1] for p in r["poly"]]))]})
    fixtures = []
    for k, b in enumerate(E["blocks"]):
        cx, cz = M((b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2)
        fixtures.append({"id": f"f{k}", "type": "block", "rect": {"x": cx, "z": cz, "w": round((b["x1"] - b["x0"]) * m_per_px, 3), "d": round((b["y1"] - b["y0"]) * m_per_px, 3), "rot_deg": 0}, "room": None, "against_wall": None, "height_m": 1.0})
    return {"unit": unit, "listing": listing, "plan_image": plan_image, "scale": {"m_per_px": round(m_per_px, 5), "from": scale_from, "sqft_listed": sqft, "agreement": agreement, "door_ref_px": door_ref, "origin_px": [float(ox), float(oy)], "image_scale": E["scale"]},
            "ceiling_m": ceiling_m, "walls": walls, "openings": ops, "rooms": rooms, "fixtures": fixtures, "materials": {}, "review": {"rounds": 0}}

def reader_anchor(E, R):
    """Match plan_reader v2 rooms (image-fraction rectangles, metres, names) to the extracted regions by centroid; returns
    (m_per_px candidates with weights, region label -> (name, type))."""
    H, W = E["room_labels"].shape; cands = []; names = {}
    regions = []
    for r in E["rooms"]:
        m = E["room_labels"] == r["label"]; ys, xs = np.where(m)
        regions.append({"label": r["label"], "cx": xs.mean() / W, "cy": ys.mean() / H, "w_px": xs.max() - xs.min() + 1, "h_px": ys.max() - ys.min() + 1})
    for rr in R.get("rooms", []):
        fr = [rr.get(k) for k in ("x0_frac", "y0_frac", "x1_frac", "y1_frac")]
        if any(v is None for v in fr):
            pos = rr.get("position") or {}
            if pos.get("x_frac") is None: continue
            fr = [pos["x_frac"] - 0.05, pos["y_frac"] - 0.05, pos["x_frac"] + 0.05, pos["y_frac"] + 0.05]
        inside = [g for g in regions if fr[0] - 0.03 <= g["cx"] <= fr[2] + 0.03 and fr[1] - 0.03 <= g["cy"] <= fr[3] + 0.03]
        if not inside: continue
        g = max(inside, key=lambda q: q["w_px"] * q["h_px"])   # the biggest region inside the reader's rectangle
        names[g["label"]] = (rr.get("name"), rr.get("type"))
        wt = {"printed": 1.0, "scaled_from_plan": 0.6, "estimated": 0.3}.get(rr.get("dims_source") or ("printed" if rr.get("width_text") else "estimated"), 0.3)
        if rr.get("width_m") and g["w_px"] > 5: cands.append((rr["width_m"] / g["w_px"], wt))
        if rr.get("depth_m") and g["h_px"] > 5: cands.append((rr["depth_m"] / g["h_px"], wt))
    return cands, names

def weighted_median(cands):
    if not cands: return None
    cands = sorted(cands); tot = sum(w for _, w in cands); acc = 0
    for v, w in cands:
        acc += w
        if acc >= tot / 2: return v
    return cands[-1][0]

def run(plan_path, listing, unit, out_dir, sqft=None, use_reader=True, repair=None):
    import os
    repair = os.environ.get("REPAIR", "0") == "1" if repair is None else repair
    E = extract(plan_path); R = None; names = {}; anchor = None
    if repair and use_reader:   # review pass: annotate once, re-extract with the openings the VLM says I missed, then the normal pipeline annotates the repaired overlay
        try:
            A0 = vlm_annotate(E, plan_path)
            if A0.get("missing_openings"): E = extract(plan_path, extra=A0["missing_openings"]); print(f"[engine] repair: {len(A0['missing_openings'])} openings added, rooms {len(E['rooms'])}")
        except Exception as e: print(f"[engine] repair unavailable: {type(e).__name__} {e}")
    if use_reader:
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pipeline2")); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
            import plan_reader; R = plan_reader.read_plan(plan_path, sqft)
            cands, names = reader_anchor(E, R); anchor = weighted_median(cands)
            if sqft is None and R.get("total_sqft_printed"): sqft = float(R["total_sqft_printed"])
        except Exception as e: print(f"[engine] reader unavailable: {type(e).__name__} {e}")
    L = metric_layout(E, unit, listing, str(plan_path), sqft=sqft)
    if anchor:   # reader dimensions beat the door estimate: rescale everything by the ratio
        k = anchor / L["scale"]["m_per_px"]; L["scale"]["from"] = ["reader_dims" + ("+printed" if R and R.get("has_dimensions") else "+estimated")] + L["scale"]["from"]; L["scale"]["door_vs_reader"] = round(1 / k, 3)
        L["scale"]["m_per_px"] = round(anchor, 5)
        def sc(v): return round(v * k, 3)
        for w in L["walls"]: w["a"] = [sc(w["a"][0]), sc(w["a"][1])]; w["b"] = [sc(w["b"][0]), sc(w["b"][1])]; w["thickness_m"] = sc(w["thickness_m"])
        for o in L["openings"]: o["s0"], o["s1"], o["width_m"] = sc(o["s0"]), sc(o["s1"]), sc(o["width_m"])
        for r in L["rooms"]: r["polygon"] = [[sc(x), sc(z)] for x, z in r["polygon"]]; r["area_m2"] = round(r["area_m2"] * k * k, 2)
        for f in L["fixtures"]: f["rect"].update({"x": sc(f["rect"]["x"]), "z": sc(f["rect"]["z"]), "w": sc(f["rect"]["w"]), "d": sc(f["rect"]["d"])})
    for r, er in zip(L["rooms"], E["rooms"]):
        if er["label"] in names: r["name"], r["type"] = names[er["label"]][0] or r["name"], names[er["label"]][1] or r["type"]
    L["ceiling_m"] = 2.6
    if use_reader:
        try:
            A = vlm_annotate(E, plan_path)
            printed_anchor = bool(R and R.get("has_dimensions"))
            if not printed_anchor:   # no printed dimensions: the annotation's per-room estimates (matched by mark) anchor the scale
                cands = []; H, W = E["room_labels"].shape
                for a in A.get("rooms", []):
                    k = a["mark"] - 1
                    if not (0 <= k < len(E["rooms"])): continue
                    m = E["room_labels"] == E["rooms"][k]["label"]; ys, xs = np.where(m)
                    if xs.size < 10: continue
                    wt = 1.0 if a.get("dims_source") == "printed" else 0.4
                    if a.get("width_m"): cands.append((a["width_m"] / (xs.max() - xs.min() + 1), wt))
                    if a.get("depth_m"): cands.append((a["depth_m"] / (ys.max() - ys.min() + 1), wt))
                est = weighted_median(cands)
                if est and 0.5 < est / L["scale"]["m_per_px"] < 2.0:
                    k2 = est / L["scale"]["m_per_px"]; L["scale"]["m_per_px"] = round(est, 5); L["scale"]["from"] = ["annotation_dims"] + L["scale"]["from"]
                    def sc2(v): return round(v * k2, 3)
                    for w in L["walls"]: w["a"] = [sc2(w["a"][0]), sc2(w["a"][1])]; w["b"] = [sc2(w["b"][0]), sc2(w["b"][1])]; w["thickness_m"] = sc2(w["thickness_m"])
                    for o in L["openings"]: o["s0"], o["s1"], o["width_m"] = sc2(o["s0"]), sc2(o["s1"]), sc2(o["width_m"])
                    for r in L["rooms"]: r["polygon"] = [[sc2(x), sc2(z)] for x, z in r["polygon"]]; r["area_m2"] = round(r["area_m2"] * k2 * k2, 2)
            L = apply_annotation(L, E, A)
        except Exception as e: print(f"[engine] annotation unavailable: {type(e).__name__} {e}")
    total = sum(r["area_m2"] for r in L["rooms"])
    biggest = max((r["area_m2"] for r in L["rooms"]), default=0)
    if len(L["rooms"]) < 2 or total < 8 or total > 260 or biggest > 90: raise ValueError(f"layout rejected: {len(L['rooms'])} rooms, {total:.1f} m2, biggest {biggest:.1f}")
    out = pathlib.Path(out_dir) / f"{unit}.json"; json.dump(L, open(out, "w"), indent=1)
    return L, out

# ---------------------------------------------------------------- stage 3: fixture candidates (set-of-marks) ----------------
def fixture_candidates(E):
    """Thin-line symbols inside rooms (counters, sinks, stoves, tubs, toilets, closet rods...) as numbered boxes. Text lines
    and door arcs are filtered geometrically; the VLM names what is left."""
    g, thick, lab = E["gray"], E["thick"], E["room_labels"]; H, W = g.shape
    loose = (g < 235).astype(np.uint8)
    walls = np.zeros((H, W), np.uint8)
    for pc in E["pieces"]:
        x0, y0, x1, y1 = ext_of(pc); cv2.rectangle(walls, (int(x0), int(y0)), (int(math.ceil(x1)), int(math.ceil(y1))), 1, -1)
    wallband = cv2.dilate(walls, cv2.getStructuringElement(cv2.MORPH_RECT, (int(thick) + 3, int(thick) + 3)))
    thin = cv2.subtract(loose, wallband)
    roomsmask = np.isin(lab, [r["label"] for r in E["rooms"]]).astype(np.uint8)
    thin = cv2.bitwise_and(thin, cv2.erode(roomsmask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))))
    # door swing squares: remove arcs
    for o in E["openings"]:
        if o["kind"] != "door": continue
        gap = int(o["b"] - o["a"]) + 2
        if o["o"] == "h": cv2.rectangle(thin, (int(o["a"]) - 2, int(o["c"] - gap)), (int(o["b"]) + 2, int(o["c"] + gap)), 0, -1)
        else: cv2.rectangle(thin, (int(o["c"] - gap), int(o["a"]) - 2), (int(o["c"] + gap), int(o["b"]) + 2), 0, -1)
    k = max(3, int(thick * 0.8)) | 1
    joined = cv2.morphologyEx(thin, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, cl, st, _ = cv2.connectedComponentsWithStats(joined, 8); cands = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if max(w, h) < 3 * thick: continue                                   # specks
        if h < 3.2 * thick and w > 3.5 * h: continue                          # a line of text
        if w < 3.2 * thick and h > 3.5 * w and a < 0.5 * w * h: continue      # vertical text or stray line
        if w * h > 0.6 * roomsmask.sum(): continue
        room = int(np.bincount(lab[cl == i][lab[cl == i] > 0]).argmax()) if (lab[cl == i] > 0).any() else None
        cands.append({"x0": int(x), "y0": int(y), "x1": int(x + w), "y1": int(y + h), "area_px": int(a), "fill": round(a / (w * h), 2), "room_label": room, "source": "thin"})
    for b in E["blocks"]:
        room = None; cx, cy = (b["x0"] + b["x1"]) // 2, (b["y0"] + b["y1"]) // 2
        for r in E["rooms"]:
            m = lab == r["label"]; ys, xs = np.where(m)
            if xs.size and xs.min() - thick <= cx <= xs.max() + thick and ys.min() - thick <= cy <= ys.max() + thick: room = r["label"]; break
        cands.append({"x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"], "area_px": (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]), "fill": 1.0, "room_label": room, "source": "block"})
    cands.sort(key=lambda c: (c["y0"], c["x0"]))
    for i, c in enumerate(cands): c["mark"] = i + 1
    return cands

def marks_image(E, cands, out):
    rgb = cv2.cvtColor(E["gray"], cv2.COLOR_GRAY2BGR)
    for c in cands:
        col = (0, 0, 230) if c["source"] == "thin" else (200, 0, 200)
        cv2.rectangle(rgb, (c["x0"], c["y0"]), (c["x1"], c["y1"]), col, 2)
        cv2.rectangle(rgb, (c["x0"], max(0, c["y0"] - 16)), (c["x0"] + 22 + 8 * (c["mark"] > 9), c["y0"]), col, -1)
        cv2.putText(rgb, str(c["mark"]), (c["x0"] + 2, max(12, c["y0"] - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(out, rgb); return out

# ---------------------------------------------------------------- stage 4: VLM annotation (rooms, fixtures, review) ---------
ANNOTATE_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "rooms": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"mark": {"type": "integer"}, "name": {"type": "string"},
        "type": {"type": "string", "enum": ["living", "bedroom", "kitchen", "bathroom", "dining", "hallway", "closet", "office", "laundry", "balcony", "entry", "other"]},
        "width_m": {"type": "number", "description": "E-W size in metres: printed if available, else estimated from doors (0.86 m), tubs (1.5 m), stoves (0.76 m)"}, "depth_m": {"type": "number"}, "dims_source": {"type": "string", "enum": ["printed", "estimated"]}}, "required": ["mark", "name", "type", "width_m", "depth_m", "dims_source"]}},
    "fixtures": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "type": {"type": "string", "enum": ["counter", "island", "sink", "stove", "fridge", "dishwasher", "tub", "shower", "toilet", "vanity", "closet_rod", "fireplace", "washer"]},
        "x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"},
        "room_mark": {"type": "integer", "description": "room number from the overlay, 0 if none"}, "against": {"type": "string", "enum": ["N", "S", "E", "W", "none"]}}, "required": ["type", "x0", "y0", "x1", "y1", "room_mark", "against"]}},
    "sqft_printed": {"type": ["number", "null"]}, "issues": {"type": "array", "items": {"type": "string"}},
    "missing_openings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"type": {"type": "string", "enum": ["door", "window", "opening"]},
        "x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"}}, "required": ["type", "x0", "y0", "x1", "y1"]}, "description": "doors/windows/openings drawn on the plan but absent (not red/blue/cyan) in my overlay, as boxes in ORIGINAL image fractions"},
    "merge_rooms": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}, "description": "groups of my region numbers that are really one room"}},
    "required": ["rooms", "fixtures", "sqft_printed", "issues", "missing_openings", "merge_rooms"]}

ANNOTATE_SYSTEM = """You annotate apartment floor plans. You get the original plan and the same plan with the rooms my program found
tinted and numbered (walls black, windows blue, doors red). Return JSON only.
rooms: for every numbered region, its name as printed (or a sensible name), type, and its E-W width and N-S depth in metres:
printed dimensions when the plan prints them (dims_source printed), otherwise your best estimate from standard sizes (door 0.86 m,
tub 1.5 m, stove 0.76 m, toilet 0.7 m deep) marked estimated. A tinted region that is really a hallway, closet or part of
another room still gets its own entry.
fixtures: every drawn fixture symbol: kitchen counter runs (one rectangle per straight run; an L is two runs), island, sink,
stove/range, refrigerator (Ref.), dishwasher (DW), bathtub, shower, toilet, vanity/bath sink, closet rods (dashed line in a
closet), fireplace, washer/dryer. Give its bounding box as fractions of the ORIGINAL image (0..1, x right, y down), the mark of
the room it sits in (or null), and the compass side of that room it is against (image-up is N) or null if free-standing.
sqft_printed: total square feet if printed on the plan, else null.
issues: anything my overlay got wrong: a room split in two, two rooms merged, a missing or extra door/window, a wall missing.
missing_openings: every door, window or cased opening drawn on the plan that my overlay does NOT mark (no red/blue/cyan line
there), as a small box around the gap in the wall, in fractions of the ORIGINAL image. Be exhaustive: an unmarked door is the
usual reason a bathroom or entry failed to become a room.
merge_rooms: groups of region numbers that belong to one room (e.g. a living room my program split with a false line)."""

def vlm_annotate(E, plan_path, model="claude-sonnet-5-5"):
    import base64, io, hashlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import claude_client as cc, spend
    sig = ",".join(f"{r['bbox'][0]}:{r['bbox'][1]}:{r['area_px'] // 500}" for r in E["rooms"])   # the overlay's room set: names and marks are only valid for it
    key = hashlib.sha1((str(plan_path) + model + "annot3" + sig).encode()).hexdigest()[:10]; cache = pathlib.Path(plan_path).parent / f"annot_{key}.json"
    if cache.exists(): return json.load(open(cache))
    import os
    if os.environ.get("REPAIR", "0") != "1":   # not repairing: an older annotation (without missing_openings) is good enough
        key2 = hashlib.sha1((str(plan_path) + model + "annot2").encode()).hexdigest()[:10]; cache2 = pathlib.Path(plan_path).parent / f"annot_{key2}.json"
        if cache2.exists(): A = json.load(open(cache2)); A.setdefault("missing_openings", []); A.setdefault("merge_rooms", []); return A
    tmp = "/tmp/_marks_overlay.png"
    rgb = cv2.cvtColor(E["gray"], cv2.COLOR_GRAY2BGR); rng = np.random.RandomState(3)
    for k, r in enumerate(E["rooms"]):
        col = rng.randint(80, 255, 3); m = E["room_labels"] == r["label"]; rgb[m] = (0.55 * rgb[m] + 0.45 * col).astype(np.uint8)
        ys, xs = np.where(m); cx, cy = int(xs.mean()), int(ys.mean())
        cv2.rectangle(rgb, (cx - 14, cy - 12), (cx + 14, cy + 10), (0, 0, 0), -1); cv2.putText(rgb, str(k + 1), (cx - 10, cy + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    for pc in E["pieces"]:
        x0, y0, x1, y1 = [int(v) for v in ext_of(pc)]; cv2.rectangle(rgb, (x0, y0), (x1, y1), (30, 30, 30), -1)
    for o in E["openings"]:
        col = {"window": (255, 160, 0), "door": (0, 0, 255), "opening": (0, 200, 200)}[o.get("kind", "opening")]
        if o["o"] == "h": cv2.line(rgb, (int(o["a"]), int(o["c"])), (int(o["b"]), int(o["c"])), col, 3)
        else: cv2.line(rgb, (int(o["c"]), int(o["a"])), (int(o["c"]), int(o["b"])), col, 3)
    cv2.imwrite(tmp, rgb)
    def img_block(path, max_px=1400):
        from PIL import Image as PI
        im = PI.open(path).convert("RGB"); im.thumbnail((max_px, max_px)); b = io.BytesIO(); im.save(b, "PNG")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(b.getvalue()).decode()}}
    content = [{"type": "text", "text": "Original plan:"}, img_block(plan_path), {"type": "text", "text": f"My overlay with {len(E['rooms'])} numbered rooms:"}, img_block(tmp)]
    c = cc.client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, system=ANNOTATE_SYSTEM, messages=messages).input_tokens; spend.check("anthropic", spend.anthropic_estimate(model, n_in, 4000))
    r = c.messages.create(model=model, max_tokens=4000, system=ANNOTATE_SYSTEM, messages=messages, output_config={"format": {"type": "json_schema", "schema": ANNOTATE_SCHEMA}, "effort": "medium"})
    usd = spend.anthropic_charge(model, r.usage, note=f"annotate {pathlib.Path(plan_path).name}")
    txt = next((b.text for b in r.content if b.type == "text"), None)
    if not txt: raise RuntimeError(f"annotate: no JSON (stop {r.stop_reason})")
    A = json.loads(txt); A["_usd"] = round(usd, 4); json.dump(A, open(cache, "w"), indent=1); return A

def apply_annotation(L, E, A):
    """Room names/types from the marks; fixtures from fractional boxes -> metres, snapped to the nearest wall of their room."""
    H, W = E["gray"].shape; sc = L["scale"]; mpp = sc["m_per_px"]; ox, oy = sc["origin_px"]
    marks = {a["mark"]: a for a in A.get("rooms", [])}
    for k, r in enumerate(L["rooms"]):
        a = marks.get(k + 1)
        if a: r["name"], r["type"] = a["name"], a["type"]
    fixtures = []
    HEIGHTS = {"counter": 0.9, "island": 0.9, "sink": 0.9, "stove": 0.9, "fridge": 1.8, "dishwasher": 0.86, "tub": 0.55, "shower": 2.0, "toilet": 0.75, "vanity": 0.85, "closet_rod": 1.7, "fireplace": 1.1, "washer": 0.9}
    for k, f in enumerate(A.get("fixtures", [])):
        x0, y0, x1, y1 = f["x0"] * W, f["y0"] * H, f["x1"] * W, f["y1"] * H
        cx, cz = (x0 + x1) / 2, (y0 + y1) / 2; w, d = (x1 - x0), (y1 - y0)
        room = L["rooms"][f["room_mark"] - 1]["id"] if f.get("room_mark") and 0 < f["room_mark"] <= len(L["rooms"]) else None
        # snap to the room's wall on the stated side: move the box flush to the room polygon edge
        if f.get("against") == "none": f["against"] = None
        if room and f.get("against"):
            poly = L["rooms"][f["room_mark"] - 1]["polygon"]; xs = [p[0] for p in poly]; zs = [p[1] for p in poly]
            side = f["against"]; depth_m = min(w, d) * mpp if f["type"] in ("counter", "vanity", "tub", "fridge", "dishwasher", "stove", "sink", "washer", "closet_rod") else None
            if depth_m and side in ("N", "S"): d = depth_m / mpp; cz = (min(zs) / mpp + oy + d / 2) if side == "N" else (max(zs) / mpp + oy - d / 2)
            if depth_m and side in ("E", "W"): w = depth_m / mpp; cx = (max(xs) / mpp + ox - w / 2) if side == "E" else (min(xs) / mpp + ox + w / 2)
        fixtures.append({"id": f"f{k}", "type": f["type"], "rect": {"x": round((cx - ox) * mpp, 3), "z": round((cz - oy) * mpp, 3), "w": round(w * mpp, 3), "d": round(d * mpp, 3), "rot_deg": {"N": 0, "S": 180, "E": 270, "W": 90}.get(f.get("against") or "", 0)},
                         "room": room, "against_wall": f.get("against"), "height_m": HEIGHTS.get(f["type"], 0.9)})
    L["fixtures"] = fixtures; L["review"] = {"rounds": 1, "issues": A.get("issues", []), "usd": A.get("_usd")}
    if A.get("sqft_printed") and not L["scale"].get("sqft_listed"): L["scale"]["sqft_printed"] = A["sqft_printed"]
    return L

if __name__ == "__main__":
    if sys.argv[1] == "layout":   # plan_engine.py layout <plan image> [sqft] [--novlm]  -> app/plan3d/layouts/<listing>_<plan stem>.json
        novlm = "--novlm" in sys.argv; args = [a for a in sys.argv[2:] if not a.startswith("--")]
        pth = pathlib.Path(args[0]); listing = pth.parts[-3]; unit = f"{listing}_{pth.stem}"
        L, out = run(pth, listing, unit, pathlib.Path(__file__).parent / "layouts", sqft=float(args[1]) if len(args) > 1 else None, use_reader=not novlm)
        print(json.dumps({"unit": unit, "m_per_px": L["scale"]["m_per_px"], "from": L["scale"]["from"], "walls": len(L["walls"]), "openings": len(L["openings"]), "rooms": [(r["id"], r["area_m2"]) for r in L["rooms"]], "fixtures": len(L["fixtures"])}), "->", out)
    else:
        for p in sys.argv[1:]:
            out = str(pathlib.Path("/private/tmp/claude-501/-Users-maciejkopiec-sunlit/d4d8b9e5-3e28-44c7-9951-fd28dd174531/scratchpad") / ("walls_" + pathlib.Path(p).parts[-3] + "_" + pathlib.Path(p).stem + ".png"))
            print(p, debug_overlay(p, out), out)


