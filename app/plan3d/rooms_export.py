"""Layout JSON -> one room JSON per room in app/rooms/<unit>__<roomId>.json, the shape app/furnish/place.py and plan.py read
(polygon CCW, edges with outward normals, windows/doors with edge+s0+s1, ceiling_m, bounds). Usage: rooms_export.py <unit>"""
import sys, json, math, pathlib
import numpy as np
from shapely.geometry import Polygon, LineString, Point
HERE = pathlib.Path(__file__).resolve().parent; ROOMS = HERE.parent / "rooms"

def export(unit):
    L = json.load(open(HERE / "layouts" / f"{unit}.json")); out = []
    wid = {w["id"]: w for w in L["walls"]}
    for r in L["rooms"]:
        P = Polygon(r["polygon"]).simplify(0.02)
        if not P.is_valid or P.area < 0.5: continue
        pts = list(P.exterior.coords)[:-1]
        if not P.exterior.is_ccw: pts = pts[::-1]
        edges = []
        for i in range(len(pts)):
            a, b = np.array(pts[i]), np.array(pts[(i + 1) % len(pts)]); d = b - a; Ln = float(np.linalg.norm(d)); d = d / max(Ln, 1e-9); n = np.array([d[1], -d[0]])
            if P.contains(Point(*((a + b) / 2 + n * 0.05))): n = -n   # outward
            edges.append({"a": a.tolist(), "b": b.tolist(), "dir": d.tolist(), "n": n.tolist(), "offset": float(n @ a), "len": Ln, "inferred": False, "axis": 0 if abs(d[0]) > abs(d[1]) else 1})
        windows, doors = [], []
        for o in L["openings"]:
            w = wid.get(o["wall"]); 
            if not w: continue
            wa, wb = np.array(w["a"]), np.array(w["b"]); wl = float(np.linalg.norm(wb - wa)); u = (wb - wa) / max(wl, 1e-9)
            p0, p1 = wa + u * o["s0"], wa + u * o["s1"]; mid = (p0 + p1) / 2
            # which room edge carries it: nearest edge within half a wall thickness + 10 cm, with the opening projected inside the edge span
            best = None
            for k, e in enumerate(edges):
                seg = LineString([e["a"], e["b"]]); dist = seg.distance(Point(*mid))
                if dist <= (w["thickness_m"] / 2 + 0.12) and (best is None or dist < best[0]): best = (dist, k)
            if best is None: continue
            k = best[1]; e = edges[k]; ea = np.array(e["a"]); ed = np.array(e["dir"]); s0 = float((p0 - ea) @ ed); s1 = float((p1 - ea) @ ed); s0, s1 = sorted((s0, s1))
            s0, s1 = max(0.0, s0), min(e["len"], s1)
            if s1 - s0 < 0.2: continue
            c3 = [float(mid[0]), float((o.get("sill_m", 0) or 0) + (o.get("height_m", 2.0) or 2.0) / 2), float(mid[1])]; nn = [-e["n"][0], 0.0, -e["n"][1]]
            rec = {"kind": o["type"] if o["type"] in ("window", "door") else "door", "edge": k, "s0": round(s0, 3), "s1": round(s1, 3), "sill_m": o.get("sill_m", 0.9 if o["type"] == "window" else 0.0), "height_m": o.get("height_m", 1.3 if o["type"] == "window" else 2.03), "width_m": round(s1 - s0, 3), "center": c3, "normal": nn, "score": 1.0, "n_views": 0, "px": 0}
            (windows if o["type"] == "window" else doors).append(rec)
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        R = {"name": f"{unit}__{r['id']}", "unit": unit, "room_id": r["id"], "label": r["name"], "type": r["type"], "ceiling_m": L.get("ceiling_m", 2.6), "polygon": [list(map(float, p)) for p in pts], "edges": edges, "windows": windows, "doors": doors,
             "area_m2": round(P.area, 2), "bounds": [[min(xs), 0.0, min(zs)], [max(xs), L.get("ceiling_m", 2.6), max(zs)]], "cameras": [], "photos": [], "source": "plan3d", "inferred_edges": [],
             "fixtures": [f for f in L["fixtures"] if f.get("room") == r["id"]], "vlm": {}}
        json.dump(R, open(ROOMS / f"{R['name']}.json", "w"), indent=1); out.append((R["name"], r["type"], R["area_m2"], len(windows), len(doors)))
    return out

if __name__ == "__main__":
    for u in sys.argv[1:]: print(json.dumps(export(u)))
