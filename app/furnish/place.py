"""Furniture placement for a rectilinear room. Items come with true dimensions (w along the item's own x, d along its z, h up),
a category, and optional relations (e.g. coffee table in front of the sofa). Wall-backed items slide along walls, back to the
wall; relational items hang off their anchor; everything must stay inside the polygon, off door swings, off windows if taller
than the sill, and leave a 0.75 m walking path from every door to every item's front. Greedy by priority with scored
candidates, then a grid walk check that rejects placements which wall something in.
Room JSON = app/rooms/<room>.json (polygon, edges, windows, doors). Usage: place.py <room.json> <items.json> [out.json]"""
import sys, json, math, pathlib
import numpy as np
from shapely.geometry import Polygon, box, Point, LineString
from shapely.affinity import rotate, translate
from shapely.ops import unary_union

WALL_BACKED = {"bed": 1, "sofa": 1, "wardrobe": 2, "dresser": 2, "bookcase": 2, "desk": 2, "tv_bench": 2, "nightstand": 3, "mirror": 3, "wall_lamp": 3}   # dining tables stand free, chairs go around them
RELATIONAL = {"coffee_table": ("sofa", "front", 0.45), "rug": ("sofa|bed|dining_table", "under", 0.0), "desk_chair": ("desk", "front", 0.10), "floor_lamp": ("sofa|armchair|bed|desk|dining_table|dresser", "side", 0.10),
              "armchair": ("sofa", "corner", 0.30), "dining_chair": ("dining_table", "around", 0.05),
              "side_table": ("sofa|armchair", "side", 0.08), "ottoman": ("armchair|sofa", "front", 0.35), "bench": ("bed", "foot", 0.15),
              "table_lamp": ("nightstand|side_table|desk|dresser", "on", 0.0), "pendant_lamp": ("dining_table|coffee_table|bed", "above", 0.0)}
DEPTH = {"table_lamp": 6, "pendant_lamp": 6, "ottoman": 6}            # relational items whose anchor is itself relational go last
HANG_BOTTOM = {"dining_table": 1.55, "coffee_table": 1.85, "bed": 1.95}   # pendant: height of the shade's bottom above the floor, by what it hangs over
CORNER_LOVERS = {"plant_pot", "plant", "floor_lamp", "stool"}            # free-standing pieces that look best in a corner
LOW_UNDER_WINDOW = {"bed", "sofa", "desk", "dining_table", "coffee_table", "rug", "nightstand", "tv_bench", "dining_chair", "desk_chair", "armchair"}
PATH_W = 0.75

# Catalogue dimensions come from a dozen scrapers that do not agree on which number is width, depth or height (a rug listed
# 1.7 x 0.003 x 2.4 stands up as a wall). canon_dims() makes them consistent per category before anything is placed.
WIDE_ON_WALL = {"sofa", "wardrobe", "dresser", "bookcase", "desk", "tv_bench", "nightstand", "bench", "dining_table", "coffee_table"}
def canon_dims(i):
    w, d, h = (float(i.get("width_m") or 0), float(i.get("depth_m") or 0), float(i.get("height_m") or 0)); cat = i.get("category")
    if not (w and d and h): return i
    v = sorted([w, d, h])
    if cat == "rug": h = v[0]; w, d = sorted([v[1], v[2]])                       # flat: thickness is the smallest number
    elif cat == "mirror": d = v[0]; w, h = [x for x in (w, d, h) if x != v[0]][:2] if len({w, d, h}) == 3 else (v[1], v[2])   # thin: depth is the smallest
    elif cat == "bed": w, d = min(w, d), max(w, d)                               # a bed is longer than it is wide; the headboard is the width
    elif cat in WIDE_ON_WALL: w, d = max(w, d), min(w, d)                         # wall-backed pieces are wider than deep
    elif cat in ("dining_chair", "desk_chair", "bar_stool", "stool"):
        if h < 0.95 * max(w, d): h, (d, w) = v[2], sorted([v[0], v[1]])                # a chair is taller than it is deep: height is the largest number
    elif cat in ("floor_lamp", "table_lamp"):
        if h < max(w, d) and max(w, d) / max(h, 1e-6) > 1.6: h, (w, d) = v[2], sorted([v[0], v[1]])   # tall things: height is the largest number
    i = dict(i); i["width_m"], i["depth_m"], i["height_m"] = round(w, 3), round(d, 3), round(h, 3); return i

# products the keyword classifier filed under the wrong category (name -> category), applied on load
RECAT = [("hooks", "other"), ("tray", "other"), ("alphabet of light", "other"), ("pot 33", "armchair"), ("ridge", "other"), ("avail", "other"), ("coil", "other"), ("gaze", "other"),
         ("table + benches", "other"), ("wall mount", "other"), ("floor panel", "other"), ("wall panel", "other"), ("magazine holder", "other"), ("carafe", "other"), ("vase", "other"), ("jug", "other")]
_ORIENT = None
def _orient():
    global _ORIENT
    if _ORIENT is None:
        try: _ORIENT = json.load(open(pathlib.Path(__file__).parent / "designer" / "orient.json"))
        except Exception: _ORIENT = {}
    return _ORIENT
_SIBLINGS = None
def _sibling_category(i):
    """For an item filed under 'other': the category of a same-brand item whose name is a prefix of this one ('AAC 121' -> 'AAC 121 Soft')."""
    global _SIBLINGS
    if _SIBLINGS is None:
        try:
            cat = json.load(open(pathlib.Path(__file__).parent / "catalog.json"))["items"]
            _SIBLINGS = {}
            for x in cat:
                if x.get("category") not in (None, "other") and len(x.get("name") or "") >= 5: _SIBLINGS.setdefault(x.get("brand") or "", []).append(((x["name"] or "").lower(), x["category"]))
        except Exception: _SIBLINGS = {}
    n = (i.get("name") or "").lower(); best = None
    for name, c in _SIBLINGS.get(i.get("brand") or "", []):
        if n != name and n.startswith(name) and (best is None or len(name) > len(best[0])): best = (name, c)
    return best[1] if best else None
import re as _re
LIGHT_RE = [(_re.compile(r"\b(wall|parete|sconce|applique)\b", _re.I), "wall_lamp"), (_re.compile(r"\b(ceiling|soffitto|plafon|recessed|downlight|spot|spots)\b", _re.I), "ceiling_lamp")]
def fix_item(i):
    n = (i.get("name") or "").lower()
    if i.get("category") in ("other", "table_lamp", "pendant_lamp", "floor_lamp") and i.get("id", "").startswith("dsg-"):   # lights the keyword classifier could not place: wall and ceiling fixtures
        for rx, c in LIGHT_RE:
            if rx.search(i.get("name") or ""): i = dict(i, category=c); break
    if i.get("category") == "other" and i.get("id", "").startswith("dsg-"):
        c = _sibling_category(i)
        if c: i = dict(i, category=c)
    od = _orient().get(i.get("id") or "")
    if od and "catalog_dims_from_old_bbox" in (od.get("flags") or []) and od.get("dims_after_m") and (od.get("confidence") or 0) >= 0.6:   # dims were measured from the mis-oriented file: take the re-oriented box
        w, d, h = od["dims_after_m"]; i = dict(i, width_m=w, depth_m=d, height_m=h)
    for k, c in RECAT:
        if k in n and i.get("category") != c: i = dict(i, category=c); break
    return canon_dims(i)

def footprint(x, z, w, d, rot_deg):
    return translate(rotate(box(-w / 2, -d / 2, w / 2, d / 2), -rot_deg, origin=(0, 0), use_radians=False), x, z)   # yaw is three.js rotation.y: local +z -> (sin, cos); shapely rotates CCW in (x, z)

def normalize(R):
    """Accept the main pipeline's JSON (polygon + edges + openings) or Path B's (layout.corners only)."""
    if "polygon" not in R and R.get("layout", {}).get("corners"): R = dict(R, polygon=R["layout"]["corners"])
    if "edges" not in R:
        P = Polygon(R["polygon"]); pts = list(P.exterior.coords)[:-1]
        if not P.exterior.is_ccw: pts = pts[::-1]
        edges = []
        for i in range(len(pts)):
            a, b = np.array(pts[i]), np.array(pts[(i + 1) % len(pts)]); d = b - a; L = float(np.linalg.norm(d)); d = d / max(L, 1e-9); n = np.array([d[1], -d[0]])   # CCW polygon: right-hand normal points outward
            edges.append({"a": a.tolist(), "b": b.tolist(), "dir": d.tolist(), "n": n.tolist(), "offset": float(n @ a), "len": L, "inferred": False, "axis": i % 2})
        R = dict(R, edges=edges)
    R.setdefault("windows", []); R.setdefault("doors", []); return R

class Room:
    def __init__(self, R):
        R = normalize(R); self.poly = Polygon(R["polygon"]); self.edges = R["edges"]; self.windows = R.get("windows", []); self.doors = [d for d in R.get("doors", []) if 0.55 <= d.get("width_m", 0) <= 1.5]   # wider "doors" are closets or openings: no swing, no keep-out
        self.walls = []
        for i, e in enumerate(self.edges):
            a, b = np.array(e["a"]), np.array(e["b"]); dirv = np.array(e["dir"]); n_out = np.array(e["n"]); inward = -n_out
            # make sure inward points into the polygon
            mid = (a + b) / 2
            if not self.poly.contains(Point(*(mid + inward * 0.2))): inward = -inward
            self.walls.append({"i": i, "a": a, "b": b, "dir": dirv, "in": inward, "len": float(e["len"]), "inferred": e.get("inferred", False)})
        # door swings: a square of the door width inside the room in front of each door, plus a 0.6 m approach strip
        self.swings = []; self.door_pts = []
        for d in self.doors:
            w = self.walls[d["edge"]]; s = (d["s0"] + d["s1"]) / 2; wd = min(max(d["width_m"], 0.7), 1.0)
            c = w["a"] + w["dir"] * s; sq = box(-wd / 2, 0, wd / 2, wd); ang = math.degrees(math.atan2(w["in"][0], w["in"][1]))   # local +z -> inward
            self.swings.append(translate(rotate(sq, -ang, origin=(0, 0)), c[0], c[1]).intersection(self.poly)); self.door_pts.append(c + w["in"] * 0.4)
        self.win_spans = {}
        for wn in self.windows: self.win_spans.setdefault(wn["edge"], []).append((wn["s0"], wn["s1"], wn.get("sill_m", 0.9)))

    def yaw_for_inward(self, inward):   # rotation (deg) so that the item's local +z (front) points along `inward`
        return math.degrees(math.atan2(inward[0], inward[1]))

    def wall_candidates(self, w_m, d_m, step=0.1):
        for w in self.walls:
            if w["len"] < w_m: continue
            for t in np.arange(w_m / 2, w["len"] - w_m / 2 + 1e-6, step):
                c = w["a"] + w["dir"] * t + w["in"] * (d_m / 2 + 0.02)
                yield float(c[0]), float(c[1]), self.yaw_for_inward(w["in"]), w, float(t)

    def blocks_window(self, wall, t, w_m, h_m, cat):
        if cat in ("mirror", "wall_lamp"): return any(t + w_m / 2 > s0 and t - w_m / 2 < s1 for s0, s1, _ in self.win_spans.get(wall["i"], []))   # hung at eye height: never on the glass
        if cat in LOW_UNDER_WINDOW and h_m <= 1.1: return False
        for s0, s1, sill in self.win_spans.get(wall["i"], []):
            if h_m > sill and (t + w_m / 2 > s0 and t - w_m / 2 < s1): return True
        return False

    def openness(self, x, z, inward, r=2.4):
        """Share of sample points in a half-disc of radius r in front of (x, z) that lie inside the room: ~1 in the open middle of a room, small at a corridor mouth or beside a jog."""
        from shapely.prepared import prep
        if not hasattr(self, "_prep"): self._prep = prep(self.poly)
        side = np.array([inward[1], -inward[0]]); n = 0; k = 0
        for a in (0.25, 0.6, 0.95):
            for b in (-0.9, -0.6, -0.3, 0.0, 0.3, 0.6, 0.9):
                if a * a + b * b > 1.0: continue
                p = np.array([x, z]) + inward * (a * r) + side * (b * r); n += 1; k += self._prep.contains(Point(p[0], p[1]))
        return k / max(n, 1)

    def door_distance(self, wall, t, w_m):
        best = 9.0
        for d in self.doors:
            if d["edge"] != wall["i"]: continue
            gap = max(d["s0"] - (t + w_m / 2), (t - w_m / 2) - d["s1"]); best = min(best, gap)
        return best

def place(R, items):
    room = Room(R); placed = []; occupied = []
    # built-in fixtures from the plan (counters, tubs, closets...) occupy floor: never placed over, counted as obstacles for the walking path
    for fx in R.get("fixtures", []) or []:
        rc = fx.get("rect") or {}
        if not rc: continue
        occupied.append({"fp": footprint(rc["x"], rc["z"], rc["w"], rc["d"], rc.get("rot_deg", 0)), "cat": "fixture", "front": None, "name": fx.get("type", "fixture")})
    ceiling = float(R.get("ceiling_m") or 2.6)
    def feasible(fp, cat, h_m, ignore=None):
        if not room.poly.buffer(0.03).contains(fp): return False
        for s in room.swings:
            if fp.intersects(s) and cat != "rug": return False
        for o in occupied:
            if o["cat"] == "rug" or cat == "rug" or o.get("floor") is False or o is ignore: continue   # rugs, hung and carried pieces take no floor
            if fp.intersects(o["fp"]): return False
        return True
    def walkable(extra=None):
        # 10 cm grid BFS from each door; every item's front cell must be reachable
        SMALL = {"rug", "fixture_small", "nightstand", "side_table", "floor_lamp", "table_lamp", "mirror", "plant_pot", "plant", "stool", "ottoman", "pendant_lamp", "wall_lamp", "ceiling_lamp"}   # you step around these: they neither block a corridor nor need one
        big = lambda o: o["cat"] not in SMALL and o["fp"].area >= 0.3
        fps = [o["fp"] for o in occupied if big(o)] + ([extra] if extra is not None else [])
        minx, minz, maxx, maxz = room.poly.bounds; g = 0.1; nx, nz = int((maxx - minx) / g) + 1, int((maxz - minz) / g) + 1
        free = np.zeros((nx, nz), bool)
        from shapely.prepared import prep
        inner = prep(room.poly.buffer(-PATH_W / 2 + 0.05)); blocked = prep(unary_union([f.buffer(PATH_W / 2 - 0.05) for f in fps])) if fps else None
        for i in range(nx):
            for j in range(nz):
                p = Point(minx + i * g, minz + j * g); free[i, j] = inner.contains(p) and not (blocked and blocked.contains(p))
        if not room.door_pts: return True
        seen = np.zeros_like(free); st = []
        for dp in room.door_pts:
            i, j = int((dp[0] - minx) / g), int((dp[1] - minz) / g)
            for di in range(-4, 5):
                for dj in range(-4, 5):
                    ii, jj = i + di, j + dj
                    if 0 <= ii < nx and 0 <= jj < nz and free[ii, jj] and not seen[ii, jj]: seen[ii, jj] = True; st.append((ii, jj))
        while st:
            i, j = st.pop()
            for ii, jj in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= ii < nx and 0 <= jj < nz and free[ii, jj] and not seen[ii, jj]: seen[ii, jj] = True; st.append((ii, jj))
        # every item must be approachable: a reachable free cell within 0.9 m of its front point OR within 0.7 m of its footprint
        # (a coffee table in front of a sofa is fine: you approach the sofa from the side)
        for o in occupied:
            if o["cat"] in ("rug", "fixture") or o["front"] is None or not big(o): continue
            f = o["front"]; i, j = int((f[0] - minx) / g), int((f[1] - minz) / g); R_ = 9
            ok = any(0 <= i + di < nx and 0 <= j + dj < nz and seen[i + di, j + dj] for di in range(-R_, R_ + 1) for dj in range(-R_, R_ + 1))
            if not ok:
                near = prep(o["fp"].buffer(0.7)); bx0, bz0, bx1, bz1 = o["fp"].buffer(0.7).bounds
                for ii in range(max(0, int((bx0 - minx) / g)), min(nx, int((bx1 - minx) / g) + 1)):
                    for jj in range(max(0, int((bz0 - minz) / g)), min(nz, int((bz1 - minz) / g) + 1)):
                        if seen[ii, jj] and near.contains(Point(minx + ii * g, minz + jj * g)): ok = True; break
                    if ok: break
            if not ok: return False
        return True
    def commit(it, x, z, yaw, wall=None, t=None):
        fp = footprint(x, z, it["w_m"], it["d_m"], yaw); inward = np.array([math.sin(math.radians(yaw)), math.cos(math.radians(yaw))])
        front = np.array([x, z]) + inward * (it["d_m"] / 2 + 0.3)
        o = dict(it, x=round(x, 3), z=round(z, 3), rot_deg=round(yaw, 1), fp=fp, front=front, cat=it["category"], wall=wall["i"] if wall else None, t=t); occupied.append(o); placed.append(o); return o
    # pinned items (already placed earlier, e.g. by the streaming agent or the user) keep their position and become obstacles
    for it in items:
        if it.get("pinned") and it.get("x") is not None and it.get("z") is not None:
            yaw = (-(it.get("rot_deg") or 0)) % 360
            o = commit(it, float(it["x"]), float(it["z"]), yaw)
            # wall/t are unknown for pinned items; nightstands need them: recover the wall if the item sits against one
            for w in room.walls:
                d_ = abs(float((np.array([it["x"], it["z"]]) - w["a"]) @ w["in"]) - it["d_m"] / 2)
                if d_ < 0.12: o["wall"] = w["i"]; o["t"] = float((np.array([it["x"], it["z"]]) - w["a"]) @ w["dir"]); break
    order = sorted([it for it in items if not it.get("pinned")], key=lambda it: (DEPTH.get(it["category"]) or WALL_BACKED.get(it["category"], 5 if it["category"] in RELATIONAL else 4), -it["w_m"] * it["d_m"]))
    for it in order:
        cat = it["category"]; w_m, d_m, h_m = it["w_m"], it["d_m"], it["h_m"]
        if cat == "mirror" and h_m < 1.3:   # wall-hung: centred at eye height, no floor taken
            it["y_m"] = round(1.55 - h_m / 2, 3); it["floor"] = False
        if cat == "wall_lamp": it["y_m"] = round(1.75 - h_m / 2, 3); it["floor"] = False   # sconce height
        if cat == "ceiling_lamp":   # one fixture per room, in the open middle of the ceiling; skipped when a pendant already lights a small room
            if any(o["cat"] in ("pendant_lamp", "ceiling_lamp") for o in placed) and room.poly.area < 20: it["unplaced"] = "the room already has a ceiling light"; continue
            core = room.poly.buffer(-0.9); core = max(core.geoms, key=lambda g: g.area) if hasattr(core, "geoms") else core
            c0 = (core if not core.is_empty else room.poly).representative_point(); it["y_m"] = round(max(1.9, ceiling - h_m - 0.02), 3); it["floor"] = False
            commit(it, float(c0.x), float(c0.y), 0.0); continue
        if cat in WALL_BACKED:
            best = None
            for x, z, yaw, wall, t in room.wall_candidates(w_m, d_m):
                if room.blocks_window(wall, t, w_m, h_m, cat): continue
                fp = footprint(x, z, w_m, d_m, yaw)
                if not feasible(fp, cat, h_m): continue
                dd = room.door_distance(wall, t, w_m)
                if dd < 0.3: continue
                score = 0.0
                score += 1.0 if not wall["inferred"] else 0.0                                   # measured walls are real walls
                score += 0.6 * (1 - abs(t - wall["len"] / 2) / (wall["len"] / 2))                # centred on the wall
                score += (2.2 if cat in ("sofa", "bed", "tv_bench", "desk") else 1.0) * room.openness(x, z, wall["in"])   # facing the open part of the room, not a corridor mouth
                score += min(dd, 2.0) * 0.3                                                       # away from doors
                if cat in ("bed", "sofa"): score += 0.8 * (not room.win_spans.get(wall["i"])) + 0.2 * wall["len"] / 6   # bed/sofa prefer the windowless long wall
                if cat == "tv_bench":                                                              # opposite the sofa
                    sofa = next((o for o in placed if o["cat"] == "sofa"), None)
                    if sofa is not None: score += 1.5 * (np.dot(wall["in"], np.array([math.sin(math.radians(sofa["rot_deg"])), math.cos(math.radians(sofa["rot_deg"]))])) < -0.9)
                if cat == "nightstand":
                    bed = next((o for o in placed if o["cat"] == "bed"), None)
                    if bed is None or bed["wall"] != wall["i"]: continue
                    gap = abs(t - bed["t"]) - bed["w_m"] / 2 - w_m / 2
                    if not (0.0 <= gap <= 0.12): continue
                    score += 3.0 - 10 * gap
                if cat == "wall_lamp":   # above a nightstand or beside the bed or mirror; two sconces go to opposite sides of the bed
                    near = [o for o in placed if o["cat"] in ("nightstand", "bed", "mirror", "desk", "sofa")]
                    if near:
                        dmin = min(math.hypot(x - o["x"], z - o["z"]) for o in near); score += 2.0 * max(0.0, 1.0 - dmin / 1.6)
                        if any(o["cat"] == "wall_lamp" and math.hypot(x - o["x"], z - o["z"]) < 1.2 for o in placed): score -= 3.0
                    else: score -= 1.0
                if cat == "desk": score += 1.0 * bool(room.win_spans.get(wall["i"]))                # desks like windows
                if cat == "dining_table": score += 0.5 * (h_m <= 0.8)
                if best is None or score > best[0]: best = (score, x, z, yaw, wall, t)
            if best:
                _, x, z, yaw, wall, t = best; o = commit(it, x, z, yaw, wall, t)
                if not walkable(): occupied.remove(o); placed.remove(o); it["unplaced"] = "blocks the walking path"
            else: it["unplaced"] = "no wall position fits"
        elif cat in RELATIONAL:
            anchor_cats, mode, gap = RELATIONAL[cat]; pool = [o for o in placed if o["cat"] in anchor_cats.split("|")]
            if mode == "on":   # second lamp goes on the second nightstand: skip supports that already carry something (works across the agent's re-runs, where items come back pinned)
                carried = [Point(q["x"], q["z"]) for q in placed if q.get("floor") is False and q["cat"] in RELATIONAL and RELATIONAL[q["cat"]][1] == "on"]
                pool = [o for o in pool if not any(o["fp"].buffer(0.02).contains(pt) for pt in carried)]   # every support taken: the lamp is skipped, never stacked
            if mode == "above":
                hung = [Point(q["x"], q["z"]) for q in placed if q.get("floor") is False and q["cat"] == "pendant_lamp"]
                pool = [o for o in pool if not any(o["fp"].buffer(0.3).contains(pt) for pt in hung)] or pool
            if mode == "on": pool = [o for o in pool if o["h_m"] <= 1.1]                             # a lamp on a dresser is fine, on a wardrobe not
            anchor = pool[0] if pool else None
            if anchor is None: it["unplaced"] = f"needs a {anchor_cats.replace('|', ' or ')}"; continue
            yaw = anchor["rot_deg"]; fwd = np.array([math.sin(math.radians(yaw)), math.cos(math.radians(yaw))]); side = np.array([fwd[1], -fwd[0]]); c = np.array([anchor["x"], anchor["z"]])
            cands = []
            if mode == "front":
                if cat in ("coffee_table", "tv_bench") and d_m > w_m: it["w_m"], it["d_m"] = d_m, w_m; w_m, d_m = d_m, w_m   # long side parallel to the anchor
                cands = [(c + fwd * (anchor["d_m"] / 2 + gap + d_m / 2), yaw + 180 if cat == "desk_chair" else yaw)]
            elif mode == "under":   # rug: long side along the anchor; under the front third of a sofa, the foot half of a bed, centred under a dining table
                along, across = max(w_m, d_m), min(w_m, d_m)
                if anchor["cat"] == "dining_table" and anchor["d_m"] > anchor["w_m"]: along, across = across, along   # follow the table's long side
                it["w_m"], it["d_m"] = along, across; w_m, d_m = along, across
                if anchor["cat"] == "dining_table": cands = [(c, yaw)] + [(c + fwd * o, yaw) for o in (0.15, -0.15, 0.3, -0.3)]
                else:
                    start = anchor["d_m"] / 2 - (0.3 if anchor["cat"] != "bed" else 0.9)
                    cands = [(c + fwd * (start + across / 2 - o) + side * l, yaw) for o in (0.0, 0.15, 0.3, 0.45, 0.6, 0.75) for l in (0.0, 0.3, -0.3)]
            elif mode == "side": cands = [(c + side * s * (anchor["w_m"] / 2 + gap + w_m / 2) + fwd * max(0.0, (anchor["d_m"] - d_m) / 2 - 0.05), yaw) for s in (1, -1)]   # flush with the anchor's front
            elif mode == "corner": cands = [(c + side * s * (anchor["w_m"] / 2 + gap + w_m / 2) + fwd * (anchor["d_m"] / 2 + 0.2), yaw - s * 60) for s in (1, -1)]   # turned toward the sofa's front, not away
            elif mode == "foot":   # bench across the foot of the bed, long side along the bed's width
                if d_m > w_m: it["w_m"], it["d_m"] = d_m, w_m; w_m, d_m = d_m, w_m
                cands = [(c + fwd * (anchor["d_m"] / 2 + gap + d_m / 2), yaw)]
            elif mode == "on":     # lamp on top of its support, toward the back, no floor taken
                it["y_m"] = round(anchor["h_m"], 3); it["floor"] = False
                back = -fwd * max(0.0, (anchor["d_m"] - d_m) / 2 - 0.05)
                cands = [(c + back, yaw), (c, yaw)]
            elif mode == "above":  # pendant over the anchor's centre; shade bottom at a sensible height, never above the ceiling
                bottom = min(HANG_BOTTOM.get(anchor["cat"], ceiling - h_m - 0.1), ceiling - h_m - 0.02)
                it["y_m"] = round(max(bottom, 1.2), 3); it["floor"] = False
                cands = [(c + fwd * (-(anchor["d_m"] / 2 - 0.9) if anchor["cat"] == "bed" else 0.0), yaw)]
            elif mode == "around":   # chairs facing the table: long sides first (two per side when the side is long), then the ends, then the diagonals of a round table
                off = anchor["d_m"] / 2 + gap + d_m / 2; offw = anchor["w_m"] / 2 + gap + d_m / 2; spots = []
                def row(normal, dist, length, face):   # chairs along one side: centred, or split in two when the side is long
                    along = np.array([normal[1], -normal[0]]); k = max(1, min(4, int(length // 0.65)))
                    for q in ([0.0] if k == 1 else [((i + 0.5) / k - 0.5) * length * 0.9 for i in range(k)]): spots.append((c + normal * dist + along * q, face))
                row(fwd, off, anchor["w_m"], yaw + 180); row(-fwd, off, anchor["w_m"], yaw); row(side, offw, anchor["d_m"], yaw - 90); row(-side, offw, anchor["d_m"], yaw + 90)   # faces: chair's front (+z) toward the table
                if abs(anchor["w_m"] - anchor["d_m"]) < 0.1 and anchor["w_m"] >= 1.1:   # round or square: seats on the diagonals too
                    for sx, sz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                        dv = (fwd * sz + side * sx); dv = dv / np.linalg.norm(dv); face = math.degrees(math.atan2(-dv[0], -dv[1]))
                        for r in np.arange(anchor["w_m"] / 2 + gap + d_m / 2, anchor["w_m"] / 2 * 1.42 + gap + d_m / 2 + 0.01, 0.05):   # slide out until clear of the table's square footprint
                            if not footprint(*(c + dv * r), w_m, d_m, face).intersects(anchor["fp"]): spots.append((c + dv * r, face)); break
                # interleave: opposite sides first so two chairs face each other before a side fills up
                spots.sort(key=lambda sp: float(np.linalg.norm(np.array(sp[0]) - c)))
                cands = spots
            done = False
            for p, y in cands:
                fp = footprint(p[0], p[1], w_m, d_m, y)
                if mode in ("on", "above"): ok = room.poly.buffer(0.03).contains(fp) and (mode == "above" or anchor["fp"].buffer(0.1).contains(fp) or (anchor["fp"].contains(fp.centroid) and fp.area <= anchor["fp"].area * 1.3))   # a lamp may overhang a small table a little
                else: ok = feasible(fp, cat, h_m)
                if ok:
                    o = commit(it, float(p[0]), float(p[1]), y); done = True
                    if mode in ("on", "above"): anchor["carries"] = o["id"]
                    break
            if not done: it["unplaced"] = "no room next to its anchor" if mode not in ("on", "above") else f"does not fit on the {anchor['cat'].replace('_', ' ')}"
        else:   # free-standing: best open spot by distance to walls/items (coarse grid)
            best = None; minx, minz, maxx, maxz = room.poly.bounds
            for x in np.arange(minx + w_m / 2, maxx - w_m / 2, 0.2):
                for z in np.arange(minz + d_m / 2, maxz - d_m / 2, 0.2):
                    fp = footprint(x, z, w_m, d_m, 0)
                    if not feasible(fp, cat, h_m): continue
                    dist = min([room.poly.exterior.distance(fp)] + [fp.distance(o["fp"]) for o in occupied if o["cat"] != "rug" and o.get("floor") is not False]); cen = room.poly.centroid
                    if cat in CORNER_LOVERS:   # into a corner, off the door swings, away from other pieces
                        cd = min(Point(px, pz).distance(fp.centroid) for px, pz in room.poly.exterior.coords); score = -cd - 0.5 * max(0.0, 0.5 - min([9] + [fp.distance(o["fp"]) for o in occupied if o["cat"] not in ("rug", "fixture") and o.get("floor") is not False]))
                    else: score = -abs(dist - 0.9) - 0.15 * fp.centroid.distance(cen)
                    if best is None or score > best[0]: best = (score, float(x), float(z))
            if best: commit(it, best[1], best[2], 0.0)
            else: it["unplaced"] = "no open floor"
    out = []
    for it in items:
        o = next((p for p in placed if p is it or p.get("id") == it.get("id") and p.get("x") is not None), None)
        rec = {k: v for k, v in it.items() if k not in ("fp", "front", "cat", "wall", "t")}
        if o is not None: rec.update({"x": o["x"], "z": o["z"], "rot_deg": round((-o["rot_deg"]) % 360, 1)})   # viewer convention: rotation.y = -rot_deg, so the stored value is minus the solver's yaw
        out.append(rec)
    return out, walkable()

if __name__ == "__main__":
    R = json.load(open(sys.argv[1])); items = json.load(open(sys.argv[2])); res, ok = place(R, items)
    print(json.dumps({"walkable": ok, "placed": sum(1 for r in res if "x" in r), "unplaced": [(r["name"], r.get("unplaced")) for r in res if "x" not in r]}))
    for r in res: print(f"  {r['category']:13s} {r['name'][:30]:30s} {r['w_m']}x{r['d_m']} at {r.get('x')},{r.get('z')} rot {r.get('rot_deg')} {r.get('unplaced','')}")
    if len(sys.argv) > 3: json.dump({"room": pathlib.Path(sys.argv[1]).stem, "items": res, "total_usd": round(sum(r.get("price_usd") or 0 for r in res), 2)}, open(sys.argv[3], "w"), indent=1)
