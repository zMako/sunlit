"""Doors that read and work like real doors: standard widths, the swing read from the plan's arc, a style per listing.

Plans are drawn loosely and the reader measures door gaps short (a third of all doors came out under 0.70 m, a size you
cannot walk through), and hinge / swing were near random. Per door opening, from the rooms on its two sides:
  - entry (exterior wall): 0.91 m swing door; wide exterior (>= 1.3 m): two-leaf glass door (balcony / patio)
  - into a closet / laundry (or a space under 2.2 m2): 0.71 m swing, or two leaves when the drawn gap is >= 1.0 m
  - into a bath: 0.76 m; anything else 0.81 m (0.91 m when drawn 1.05-1.3 m)
  - wider than 1.3 m between two ordinary rooms: a cased opening (no leaf)
  Widened around the drawn centre, kept inside the wall and clear of the other openings on it (shrunk if the wall is short).
Swing: the four (hinge end x side) quarter-arcs of the drawn leaf are tested against the plan's ink; a clear winner is
used ("plan arc"). Otherwise the architects' rule: the door opens into the room it serves (bath, bedroom, closet before
hall / living; never outwards), hinged at the end nearer the wall's end so it folds back against the wall ("rule").
Style: layout["door_style"] from door_styles.json (CLIP on the listing photos), default "shaker".

  doors.py [units ...]   (default: every layout), then rooms_export"""
import sys, json, math, pathlib, subprocess
import numpy as np, cv2
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")
STYLES = HERE / "door_styles.json"
SERVED = {"bathroom": 5, "closet": 5, "laundry": 5, "bedroom": 4, "office": 4, "kitchen": 2, "dining": 2, "other": 2, "living": 1, "entry": 1, "hallway": 0, "balcony": 0}

def pip(x, z, poly):
    inside = False
    for i in range(len(poly)):
        x1, z1 = poly[i - 1]; x2, z2 = poly[i]
        if (z2 > z) != (z1 > z) and x < (x1 - x2) * (z - z2) / ((z1 - z2) or 1e-12) + x2: inside = not inside
    return inside

def area(poly): return abs(sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly)))) / 2

def load_plan_ink(L):
    p = L["plan_image"] if L["plan_image"].startswith("/") else str(ROOT / L["plan_image"])
    g = np.asarray(Image.open(p).convert("L")); ink = cv2.dilate((g < 200).astype(np.uint8), np.ones((5, 5), np.uint8))
    return ink

def to_px(L, level):
    sc = L["scale"]; m, (ox, oy), s = sc["m_per_px"], sc["origin_px"], sc.get("image_scale", 1) or 1
    off = next((v.get("plan_offset_m", [0, 0]) for v in L.get("levels", []) if v["id"] == level), [0, 0])
    def f(x, z): return ((x + off[0]) / m + ox) / s, ((z + off[1]) / m + oy) / s, m * s   # px x, px y, metres per px
    return f

def arc_swing(ink, L, w, o, level):
    """the drawn leaf's quarter arc: (hinge 'left'|'right', side 'in'|'out', score, margin) or None"""
    fx = to_px(L, level); a = np.array(w["a"], float); b = np.array(w["b"], float); d = (b - a) / (np.linalg.norm(b - a) or 1); n = np.array([-d[1], d[0]])
    R0 = o["s1"] - o["s0"]; H, W_ = ink.shape; scores = []
    for hinge, s_h, along in (("left", o["s0"], 1.0), ("right", o["s1"], -1.0)):
        for side, sg in (("in", 1.0), ("out", -1.0)):
            best = 0.0
            for rf in (1.0, 1.15):
                R = R0 * rf; hits = tot = 0
                for k in range(14):
                    th = math.radians(15 + 60 * k / 13); q = a + d * s_h + d * along * R * math.cos(th) + n * sg * R * math.sin(th)
                    px, py, _ = fx(q[0], q[1]); xi, yi = int(round(px)), int(round(py))
                    if 0 <= xi < W_ and 0 <= yi < H: tot += 1; hits += int(ink[yi, xi] > 0)
                if tot >= 8: best = max(best, hits / tot)
            scores.append((best, hinge, side))
    scores.sort(reverse=True)
    top, second = scores[0], scores[1]
    if top[0] >= 0.55 and top[0] - second[0] >= 0.15: return top[1], top[2], round(top[0], 2), round(top[0] - second[0], 2)
    return None

def fix_layout(L, style_of=None):
    rooms = L["rooms"]; walls = {w["id"]: w for w in L["walls"]}; ink = None; stats = {"widened": 0, "arc": 0, "rule": 0, "cased": 0, "two_leaf": 0, "duplicates_removed": 0}
    def room_at(x, z, level):
        for r in rooms:
            if (r.get("level") or 0) == level and pip(x, z, r["polygon"]): return r
        return None
    # duplicates: the engine sometimes finds the same doorway two or three times on short parallel wall pieces; keep the one
    # with the drawn arc (else the most door-like drawn width) and give the others back to the wall
    def centre(o):
        w = walls.get(o["wall"]); a = np.array(w["a"], float); b = np.array(w["b"], float); ln = float(np.linalg.norm(b - a)) or 1
        return a + (b - a) / ln * (o["s0"] + o["s1"]) / 2, (b - a) / ln, w.get("level") or 0
    dl = [o for o in L["openings"] if o["type"] in ("door", "closet_door") and o["wall"] in walls]; drop = set()
    if dl:
        ink = load_plan_ink(L)
        def quality(o):
            w = walls[o["wall"]]; wd = o.get("width_drawn_m") or (o["s1"] - o["s0"]); sw = arc_swing(ink, L, w, dict(o, s0=(o["s0"] + o["s1"]) / 2 - wd / 2, s1=(o["s0"] + o["s1"]) / 2 + wd / 2), w.get("level") or 0)
            return (1 if sw else 0, sw[2] if sw else 0, -abs(wd - 0.8))
        for i, o in enumerate(dl):
            if id(o) in drop: continue
            ci, ui, li = centre(o)
            group = [o] + [q for q in dl[i + 1:] if id(q) not in drop and centre(q)[2] == li and abs(float(np.dot(ui, centre(q)[1]))) > 0.9 and float(np.linalg.norm(centre(q)[0] - ci)) < 0.6]
            if len(group) > 1:
                keep = max(group, key=quality)
                for q in group:
                    if q is not keep: drop.add(id(q))
        if drop: L["openings"] = [o for o in L["openings"] if id(o) not in drop]; stats["duplicates_removed"] = len(drop)
    by_wall = {}
    for o in L["openings"]: by_wall.setdefault(o["wall"], []).append(o)
    for o in L["openings"]:
        if o["type"] not in ("door", "closet_door"): continue
        w = walls.get(o["wall"])
        if not w: continue
        lvl = w.get("level") or 0; a = np.array(w["a"], float); b = np.array(w["b"], float); ln = float(np.linalg.norm(b - a))
        if ln < 0.3: continue
        d = (b - a) / ln; n = np.array([-d[1], d[0]]); sc = (o["s0"] + o["s1"]) / 2; c = a + d * sc
        w0 = o.get("width_drawn_m") or (o["s1"] - o["s0"])   # re-runs keep measuring the drawn gap
        rin = room_at(*(c + n * 0.45), lvl); rout = room_at(*(c - n * 0.45), lvl)
        ext = bool(w.get("exterior")) or rin is None or rout is None
        def closetish(r): return r is not None and (r["type"] in ("closet", "laundry") or (area(r["polygon"]) < 2.2 and r["type"] != "bathroom"))
        bath = any(r is not None and r["type"] == "bathroom" for r in (rin, rout))
        clos = (closetish(rin) or closetish(rout)) and not bath   # a small nook beside a bath is the tub / vanity alcove: a bath door
        leaves, style, target = 1, None, None
        if ext:
            if w0 >= 1.3: leaves, style, target = 2, "glass", min(max(w0, 1.3), 2.4)
            else: target = 0.91
        elif clos:
            if w0 >= 1.0: leaves, style, target = 2, "bifold", min(w0, 2.4); o["type"] = "closet_door"
            else: target = max(w0, 0.71)
        elif w0 > 1.3:   # a wide gap between two ordinary rooms: an open, cased passage
            o["type"] = "opening"; o.pop("swing", None); o.update(sill_m=0.0, height_m=2.1); stats["cased"] += 1; continue
        elif bath: target = min(max(w0, 0.76), 0.91)
        else: target = 0.81 if w0 <= 1.05 else 0.91
        # widen / narrow around the drawn centre, inside the wall and clear of its other openings
        lo, hi = 0.05, ln - 0.05
        for q in by_wall.get(o["wall"], []):
            if q is o: continue
            if q["s1"] <= o["s0"] + 1e-3: lo = max(lo, q["s1"] + 0.08)
            elif q["s0"] >= o["s1"] - 1e-3: hi = min(hi, q["s0"] - 0.08)
        target = min(target, max(hi - lo, w0))
        s0 = sc - target / 2; s1 = sc + target / 2
        if s0 < lo: s1 += lo - s0; s0 = lo
        if s1 > hi: s0 -= s1 - hi; s1 = hi
        s0 = max(s0, 0.0); s1 = min(s1, ln)
        if abs((s1 - s0) - w0) > 0.03: stats["widened"] += 1
        o["width_drawn_m"] = round(w0, 3)
        drawn = dict(o, s0=sc - w0 / 2, s1=sc + w0 / 2)   # the drawn span: the arc is measured on it
        o["s0"], o["s1"], o["width_m"] = round(s0, 3), round(s1, 3), round(s1 - s0, 3); o["leaves"] = leaves
        if style: o["style"] = style
        if o["type"] == "door" and o.get("sill_m") is None: o.update(sill_m=0.0, height_m=2.03)
        # swing: the drawn arc, else the rule
        sw = None
        if leaves == 1:
            if ink is None: ink = load_plan_ink(L)
            sw = arc_swing(ink, L, w, drawn, lvl)
        if sw: o["swing"] = f"{sw[1]}_{sw[0]}"; o["swing_from"] = "plan arc"; stats["arc"] += 1
        else:
            pr = lambda r: -1 if r is None else SERVED.get(r["type"], 2) + (0.5 if area(r["polygon"]) < 6 else 0)
            side = "in" if pr(rin) >= pr(rout) else "out"
            hinge = "left" if o["s0"] <= ln - o["s1"] else "right"   # the end nearer the wall's end: the leaf folds back against that wall
            o["swing"] = f"{side}_{hinge}"; o["swing_from"] = "rule"; stats["rule"] += 1
        if leaves == 2: stats["two_leaf"] += 1
    if style_of: L["door_style"] = style_of
    elif "door_style" not in L: L["door_style"] = "shaker"
    L.setdefault("review", {})["doors"] = stats
    return stats

if __name__ == "__main__":
    styles = json.load(open(STYLES)) if STYLES.exists() else {}
    units = sys.argv[1:] or [f.stem for f in sorted((HERE / "layouts").glob("*.json")) if f.name != "index.json"]
    tot = {}
    for u in units:
        f = HERE / "layouts" / f"{u}.json"; L = json.load(open(f))
        st = (styles.get(L.get("listing")) or {}).get("style")
        try: s = fix_layout(L, st)
        except Exception as e: print(f"[doors] {u}: {type(e).__name__} {e}"); continue
        json.dump(L, open(f, "w"), indent=1)
        subprocess.run([PY, str(HERE / "rooms_export.py"), u], capture_output=True, text=True, cwd=str(ROOT))
        for k, v in s.items(): tot[k] = tot.get(k, 0) + v
    print(f"[doors] {len(units)} units: {tot}")
