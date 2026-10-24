"""Step 3: register a room polygon to the building footprint. Search yaw (around the facade bearing), slide along the
facade, and depth; score = room inside the lot + exterior walls lying on the footprint boundary (bays match bumps)."""
import numpy as np, math
from shapely.geometry import Polygon, LineString, Point

def transform_fn(yaw_deg, shift):
    r = math.radians(yaw_deg)
    def T(p):  # room (x, z) -> ENU (e, n)
        x, z = p; e, n = x, -z
        return np.array([e * math.cos(r) + n * math.sin(r), -e * math.sin(r) + n * math.cos(r)]) + shift
    return T

def exterior_edges(meta, ww):
    """Edges likely on the building envelope: the window wall, its plane-backed neighbours, any edge with a window."""
    E = meta["edges"]; n = len(E); ext = set(w["edge"] for w in meta["windows"] if w["edge"] >= 0)
    if ww and ww["edge"] >= 0:
        k = ww["edge"]; ext.add(k)
        for d in (-1, 1):
            j = (k + d) % n
            if not E[j]["inferred"] and E[j]["len"] < 2.5: ext.add(j)   # short returns next to the window wall (bay sides)
    return sorted(ext)

def register(meta, site, ww, facade, yaw0, d_yaw=8, step_yaw=2, slide_step=0.15, depth_steps=(-0.25, 0.0, 0.25)):
    V = np.array(meta["polygon"]); E = meta["edges"]; ring = np.array(site["building"]["ring"]); lot = Polygon(ring); boundary = LineString(ring)
    a, b = np.array(facade["a"]), np.array(facade["b"]); fdir = (b - a) / max(np.linalg.norm(b - a), 1e-9); L = np.linalg.norm(b - a)
    nb = math.radians(facade["bearing"]); fnorm = np.array([math.sin(nb), math.cos(nb)])
    ext = exterior_edges(meta, ww)
    samples = []
    for k in ext:
        p, q = np.array(E[k]["a"]), np.array(E[k]["b"]); m = max(2, int(E[k]["len"] / 0.1)); samples += [p + (q - p) * t for t in np.linspace(0, 1, m)]
    samples = np.array(samples) if samples else np.zeros((0, 2))
    room_area = Polygon(V).area; mid_room = np.array(ww["mid"])
    best = None
    for dy in np.arange(-d_yaw, d_yaw + 1e-6, step_yaw):
        yaw = yaw0 + dy; T0 = transform_fn(yaw, np.zeros(2)); mw = T0(mid_room)
        for s in np.arange(0.5, max(L - 0.5, 0.6), slide_step):
            for dd in depth_steps:
                target = a + fdir * s - fnorm * dd; shift = target - mw; T = transform_fn(yaw, shift)
                PV = np.array([T(p) for p in V])
                try: inside = Polygon(PV).intersection(lot).area / max(room_area, 1e-6)
                except Exception: continue
                if len(samples):
                    SP = np.array([T(p) for p in samples]); near = np.mean([boundary.distance(Point(p)) < 0.3 for p in SP])
                else: near = 0.0
                score = 3.0 * inside + 1.5 * near - 0.02 * abs(dy)
                if best is None or score > best["score"]: best = {"score": score, "yaw": float(yaw), "shift": shift, "inside": float(inside), "on_boundary": float(near), "slide_m": float(s), "depth_m": float(dd)}
    return best
