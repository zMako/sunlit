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

WALL_BACKED = {"bed": 1, "sofa": 1, "wardrobe": 2, "dresser": 2, "bookcase": 2, "desk": 2, "tv_bench": 2, "nightstand": 3}   # dining tables stand free, chairs go around them
RELATIONAL = {"coffee_table": ("sofa", "front", 0.45), "rug": ("sofa|bed|dining_table", "under", 0.0), "desk_chair": ("desk", "front", 0.10), "floor_lamp": ("sofa|armchair|bed|desk", "side", 0.10),
              "armchair": ("sofa", "corner", 0.30), "dining_chair": ("dining_table", "around", 0.05)}
LOW_UNDER_WINDOW = {"bed", "sofa", "desk", "dining_table", "coffee_table", "rug", "nightstand", "tv_bench", "dining_chair", "desk_chair", "armchair"}
PATH_W = 0.75

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
        if cat in LOW_UNDER_WINDOW and h_m <= 1.1: return False
        for s0, s1, sill in self.win_spans.get(wall["i"], []):
            if h_m > sill and (t + w_m / 2 > s0 and t - w_m / 2 < s1): return True
        return False

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
    def feasible(fp, cat, h_m):
        if not room.poly.buffer(0.03).contains(fp): return False
        for s in room.swings:
            if fp.intersects(s) and cat != "rug": return False
        for o in occupied:
            if o["cat"] == "rug" or cat == "rug": continue
            if fp.intersects(o["fp"]): return False
        return True
    def walkable(extra=None):
        # 10 cm grid BFS from each door; every item's front cell must be reachable
        fps = [o["fp"] for o in occupied if o["cat"] != "rug"] + ([extra] if extra is not None else [])
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
            if o["cat"] in ("rug", "fixture") or o["front"] is None: continue
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
    order = sorted([it for it in items if not it.get("pinned")], key=lambda it: (WALL_BACKED.get(it["category"], 5 if it["category"] in RELATIONAL else 4), -it["w_m"] * it["d_m"]))
    for it in order:
        cat = it["category"]; w_m, d_m, h_m = it["w_m"], it["d_m"], it["h_m"]
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
                if cat == "desk": score += 1.0 * bool(room.win_spans.get(wall["i"]))                # desks like windows
                if cat == "dining_table": score += 0.5 * (h_m <= 0.8)
                if best is None or score > best[0]: best = (score, x, z, yaw, wall, t)
            if best:
                _, x, z, yaw, wall, t = best; o = commit(it, x, z, yaw, wall, t)
                if not walkable(): occupied.remove(o); placed.remove(o); it["unplaced"] = "blocks the walking path"
            else: it["unplaced"] = "no wall position fits"
        elif cat in RELATIONAL:
            anchor_cats, mode, gap = RELATIONAL[cat]; anchor = next((o for o in placed if o["cat"] in anchor_cats.split("|")), None)
            if anchor is None: it["unplaced"] = f"needs a {anchor_cats}"; continue
            yaw = anchor["rot_deg"]; fwd = np.array([math.sin(math.radians(yaw)), math.cos(math.radians(yaw))]); side = np.array([fwd[1], -fwd[0]]); c = np.array([anchor["x"], anchor["z"]])
            cands = []
            if mode == "front":
                if cat in ("coffee_table", "tv_bench") and d_m > w_m: it["w_m"], it["d_m"] = d_m, w_m; w_m, d_m = d_m, w_m   # long side parallel to the anchor
                cands = [(c + fwd * (anchor["d_m"] / 2 + gap + d_m / 2), yaw + 180 if cat == "desk_chair" else yaw)]
            elif mode == "under":   # rug: long side along the anchor, starting under its front third (sofa) or its foot half (bed)
                along, across = max(w_m, d_m), min(w_m, d_m); it["w_m"], it["d_m"] = along, across; w_m, d_m = along, across
                start = anchor["d_m"] / 2 - (0.3 if anchor["cat"] != "bed" else 0.9)
                cands = [(c + fwd * (start + across / 2), yaw), (c + fwd * (start + across / 2 - 0.3), yaw)]
            elif mode == "side": cands = [(c + side * s * (anchor["w_m"] / 2 + gap + w_m / 2), yaw) for s in (1, -1)]
            elif mode == "corner": cands = [(c + side * s * (anchor["w_m"] / 2 + gap + w_m / 2) + fwd * (anchor["d_m"] / 2 + 0.2), yaw + s * 60) for s in (1, -1)]
            elif mode == "around":   # chairs: the two long sides first (split when the table is long), then the two ends; every free spot is tried
                off = anchor["d_m"] / 2 + gap + d_m / 2; offw = anchor["w_m"] / 2 + gap + d_m / 2
                if anchor["w_m"] > 1.4: spots = [(c + fwd * off + side * anchor["w_m"] / 4, yaw + 180), (c - fwd * off + side * anchor["w_m"] / 4, yaw), (c + fwd * off - side * anchor["w_m"] / 4, yaw + 180), (c - fwd * off - side * anchor["w_m"] / 4, yaw)]
                else: spots = [(c + fwd * off, yaw + 180), (c - fwd * off, yaw)]
                spots += [(c + side * offw, yaw + 90), (c - side * offw, yaw - 90)]
                cands = spots
            done = False
            for p, y in cands:
                fp = footprint(p[0], p[1], w_m, d_m, y)
                if feasible(fp, cat, h_m): commit(it, float(p[0]), float(p[1]), y); done = True; break
            if not done: it["unplaced"] = "no room next to its anchor"
        else:   # free-standing: best open spot by distance to walls/items (coarse grid)
            best = None; minx, minz, maxx, maxz = room.poly.bounds
            for x in np.arange(minx + w_m / 2, maxx - w_m / 2, 0.2):
                for z in np.arange(minz + d_m / 2, maxz - d_m / 2, 0.2):
                    fp = footprint(x, z, w_m, d_m, 0)
                    if not feasible(fp, cat, h_m): continue
                    dist = min([room.poly.exterior.distance(fp)] + [fp.distance(o["fp"]) for o in occupied if o["cat"] != "rug"]); cen = room.poly.centroid; score = -abs(dist - 0.9) - 0.15 * fp.centroid.distance(cen)
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
