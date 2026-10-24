"""Pipeline 2, stage 4: layout from segmentation-labelled geometry. Floor footprint from floor pixels; polygon from wall
lines around it; openings from window/door masks projected onto their wall plane. Reuses general_polygon, edges_of,
snap_to_edges and the fit from pipeline 1."""
import sys, pathlib, numpy as np, cv2
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pipeline"))
import geometry, layout, seg as S
from shapely.geometry import Polygon, Point

CELL = layout.CELL

def strong_planes(room, min_frac=0.06, min_len=0.7, merge_dist=0.4):
    """Rectilinear prior. Keep wall planes in the two dominant directions; an off-axis plane survives only with strong
    photographed support (>= min_frac of wall pixels, segment >= min_len) and only if it has an adjacent window
    (SF bays). Parallel planes within merge_dist of a stronger one are the same wall (door reveals, trim): merged."""
    walls = [p for p in room["planes"] if p["kind"] == "wall" and p.get("extent")]
    if not walls: return []
    total = sum(p["extent"]["n_px"] for p in walls); az = {}
    for p in walls: az[round(p["az_deg"] / 90) * 90 % 180] = az.get(round(p["az_deg"] / 90) * 90 % 180, 0) + p["extent"]["n_px"]
    # dominant pair: the direction with most support and its perpendicular (any angle, from the strongest plane)
    best = max(walls, key=lambda p: p["extent"]["n_px"]); a0 = best["az_deg"] % 180
    def off_axis(p): d = abs((p["az_deg"] - a0 + 90) % 180 - 90); return min(d, abs(90 - d)) > 15
    keep = []
    for p in sorted(walls, key=lambda p: -p["extent"]["n_px"]):
        if off_axis(p) and not (p["extent"]["n_px"] >= min_frac * total and p["extent"]["len"] >= min_len): continue
        n = np.array([p["n"][0], p["n"][2]])
        if any(abs(abs(n @ np.array([q["n"][0], q["n"][2]])) - 1) < 0.03 and abs(abs(q["offset"]) - abs(p["offset"])) < merge_dist and q["extent"]["n_px"] > p["extent"]["n_px"] for q in keep): continue
        keep.append(p)
    return keep

def floor_footprint(room, segl, margin=1.0, closure=0.35):
    """Room cell from seen walls: start from a box around everything seen, carve away the space behind every fitted wall
    segment (within its lateral extent, so bays survive), close the unseen sides at the extent of seen floor/walls/cameras
    plus a margin (those edges become 'inferred'). Compatible with layout.general_polygon."""
    pts, good, labels = room["pts"], room["good"], room["labels"]; cams = room["cams"][:, [0, 2]]
    wl = pts[good & (labels == geometry.WALL)][:, [0, 2]]
    segs = []; room["strong_planes"] = strong_planes(room)
    for pl in room["strong_planes"]:
        if pl["kind"] != "wall" or not pl.get("extent"): continue
        a = np.array(pl["extent"]["a"]); b = np.array(pl["extent"]["b"]); n = np.array([pl["n"][0], pl["n"][2]]); n = n / (np.linalg.norm(n) + 1e-9)
        if n @ (cams.mean(0) - (a + b) / 2) > 0: n = -n   # outward = away from the cameras
        segs.append((a, b, n, pl["extent"]["n_px"]))
    # per camera: floor evidence is capped at the first seen wall the camera faces (floor seen through a doorway is the next room)
    fl_parts = []
    for i in range(pts.shape[0]):
        fwd = np.array(room["cam_basis"][i]["fwd"]); f2 = np.array([fwd[0], fwd[2]]); f2 = f2 / (np.linalg.norm(f2) + 1e-9); c2 = cams[i]
        cap = np.inf
        for a, b, n, _ in segs:
            d = b - a; L = np.linalg.norm(d); d = d / max(L, 1e-9); den = f2[0] * d[1] - f2[1] * d[0]
            if abs(den) < 1e-6: continue
            t = ((a[0] - c2[0]) * d[1] - (a[1] - c2[1]) * d[0]) / den; u = ((a[0] - c2[0]) * f2[1] - (a[1] - c2[1]) * f2[0]) / den
            if t > 0.3 and -0.3 <= u <= L + 0.3 and (n @ f2) > 0.3: cap = min(cap, t)
        fi = pts[i][good[i] & (labels[i] == geometry.FLOOR)][:, [0, 2]]
        if len(fi): along = (fi - c2) @ f2; fl_parts.append(fi[along < cap + 0.3])
    fl = np.vstack(fl_parts) if fl_parts else np.zeros((0, 2))
    seen = np.vstack([q for q in (fl, wl, cams, np.array([s_[0] for s_ in segs] + [s_[1] for s_ in segs]).reshape(-1, 2) if segs else np.zeros((0, 2))) if len(q)])
    lo = np.floor((seen.min(0) - margin - closure) / CELL) * CELL; hi = seen.max(0) + margin + closure
    n_ = np.ceil((hi - lo) / CELL).astype(int) + 1; W, H = int(n_[0]), int(n_[1])
    gx, gz = np.meshgrid(lo[0] + np.arange(W) * CELL, lo[1] + np.arange(H) * CELL); Pc = np.stack([gx, gz], -1)
    F = np.ones((H, W), np.uint8)
    for a, b, n, npx in segs:
        d = b - a; L = np.linalg.norm(d); d = d / max(L, 1e-9); rel = Pc - a; along = rel @ d; out = rel @ n
        F[(out > 0.0) & (along > -1.0) & (along < L + 1.0)] = 0   # a wall continues across its doors: carve a door-width past its seen extent
    # closure box: seen FLOOR plus a 1 m box around each camera, with a small margin. Wall pixels are excluded on purpose:
    # walls seen through a doorway belong to the next room and would stretch the cell.
    core = np.vstack([q for q in (fl, cams - 1.0, cams + 1.0) if len(q)]); clo = core.min(0) - closure; chi = core.max(0) + closure
    F[(gx < clo[0]) | (gx > chi[0]) | (gz < clo[1]) | (gz > chi[1])] = 0
    k = int(0.25 / CELL) | 1; F = cv2.morphologyEx(F, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    nl, cc = cv2.connectedComponents(F); ids = [cc[int((c[1] - lo[1]) / CELL), int((c[0] - lo[0]) / CELL)] for c in cams]; ids = [i for i in ids if i > 0]
    region = (cc == max(set(ids), key=ids.count)).astype(np.uint8) if ids else F
    occ = np.zeros((H, W), np.int32)
    if len(fl): np.add.at(occ, (np.clip(((fl[:, 1] - lo[1]) / CELL).astype(int), 0, H - 1), np.clip(((fl[:, 0] - lo[0]) / CELL).astype(int), 0, W - 1)), 1)
    return {"region": region, "free": (occ >= 1).astype(np.float32), "hit": np.zeros_like(region, np.float32), "lo": lo, "W": W, "H": H, "floor_cells": int((occ >= 1).sum()), "n_wall_segments": len(segs)}

def rect_room(room, segl, max_side=8.0, margin=0.35, vlm=None, strict_vlm=False):
    """Rectangle-first layout. Dominant axes from the strongest wall plane. Each of the four sides is the best-supported
    plane facing outward on that side (measured), or the extent of seen floor and cameras plus a margin (inferred).
    Returns V (4,2), E (edge records with 'inferred'), and the axes."""
    planes = room.get("strong_planes") or strong_planes(room)
    walls = [p for p in planes if p["kind"] == "wall" and p.get("extent")]
    cams = room["cams"][:, [0, 2]]; pts, good, labels = room["pts"], room["good"], room["labels"]
    fl = pts[good & (labels == geometry.FLOOR)][:, [0, 2]]
    if walls:
        best = max(walls, key=lambda p: p["extent"]["n_px"]); u = np.array([best["n"][0], best["n"][2]]); u = u / (np.linalg.norm(u) + 1e-9)
    else: u = np.array([1.0, 0.0])
    v = np.array([-u[1], u[0]]); A = np.stack([u, v])          # rows: axis directions; coords = A @ p
    cu = cams @ A.T; fu = fl @ A.T if len(fl) else cu; cm = cu.mean(0)
    sides = {}
    for ax, sgn in ((0, 1), (0, -1), (1, 1), (1, -1)):
        dirv = A[ax] * sgn; cand = []
        for p in walls:
            n = np.array([p["n"][0], p["n"][2]]); n = n / (np.linalg.norm(n) + 1e-9)
            if n @ dirv < np.cos(np.radians(15)) and (-n) @ dirv < np.cos(np.radians(15)): continue
            off = p["offset"] * (1 if n @ dirv > 0 else -1)   # signed distance along dirv
            dist = off - cm @ dirv
            if 0.4 < dist < max_side: cand.append((p["extent"]["n_px"], off))
        if cand: sides[(ax, sgn)] = (max(cand)[1], False)
        else:
            ext = max(np.max(fu @ dirv) if len(fu) else -1e9, np.max(cu @ dirv) + 1.0) + margin
            sides[(ax, sgn)] = (float(ext), True)
    # VLM prior for unmeasured sides: the dimension along an axis = measured side + VLM width/depth. Which VLM dimension
    # belongs to which axis: VLM 'width' runs along the window wall; the window wall is the measured side carrying windows.
    vlm_used = []; dbg = {}
    if vlm and vlm.get("width_m") and vlm.get("depth_m"):
        win_axis = None
        for pl in walls:
            pass
        # axis of the window wall = axis perpendicular to the wall that most window pixels project onto (simple: use the side with the largest window-count later; here: strongest measured plane that faces a window-labelled region)
        wn = pts[good & (segl == 4)][:, [0, 2]] if (segl == 4).any() else None
        if wn is not None and len(wn) > 200:
            wc = (wn @ A.T).mean(0); dists = {ax: abs(abs(wc[ax] - cm[ax])) for ax in (0, 1)}; win_axis = max(dists, key=dists.get)   # window wall is far along its axis
        along = 1 - win_axis if win_axis is not None else 1; across = win_axis if win_axis is not None else 0   # 'width' runs along the window wall = across-axis extent? no: width is the extent ALONG the wall, i.e. along the other axis
        if vlm.get("width_along_u") is not None: along, across = (0, 1) if vlm["width_along_u"] else (1, 0)   # plan matcher already decided the orientation
        dim_for = {along: float(vlm["width_m"]), across: float(vlm["depth_m"])}
        def support0(ax, sgn):
            if sides[(ax, sgn)][1]: return -1
            dirv = A[ax] * sgn; best_px = 0
            for p in walls:
                n = np.array([p["n"][0], p["n"][2]]); n = n / (np.linalg.norm(n) + 1e-9)
                if abs(n @ dirv) < np.cos(np.radians(15)): continue
                if abs(p["offset"] * (1 if n @ dirv > 0 else -1) - sides[(ax, sgn)][0]) < 0.1: best_px = max(best_px, p["extent"]["n_px"])
            return best_px
        if strict_vlm:
            # Path A: the VLM / plan dimension IS the room size. A measured pair of walls is kept only when it agrees with it;
            # otherwise the box is anchored on the window wall (else the better-supported wall) and the other wall sits one
            # dimension away. The box slides, never grows, to keep the cameras inside; it grows only if the cameras need more.
            src = vlm.get("source"); tolk = 0.10 if src == "floor_plan" else 0.15
            win_side = {}
            if wn is not None and len(wn) > 200: win_side = {ax: (1 if wc[ax] > cm[ax] else -1) for ax in (0, 1)}
            dbg = {"strict": True, "dim_for": [dim_for[0], dim_for[1]], "cam_spread": [float(np.ptp(cu[:, 0])), float(np.ptp(cu[:, 1]))], "axes": [],
                   "span0": [float(sides[(0, 1)][0] + sides[(0, -1)][0]), float(sides[(1, 1)][0] + sides[(1, -1)][0])], "pair_measured": [not sides[(0, 1)][1] and not sides[(0, -1)][1], not sides[(1, 1)][1] and not sides[(1, -1)][1]]}
            for ax in (0, 1):
                D = min(max(dim_for[ax], 1.8), 9.0); m_pos, m_neg = not sides[(ax, 1)][1], not sides[(ax, -1)][1]
                cmin, cmax = float(cu[:, ax].min()) - 0.5, float(cu[:, ax].max()) + 0.5; grown = False
                if cmax - cmin > D: D = cmax - cmin + 0.3; grown = True
                hi0, lo0 = sides[(ax, 1)][0], -sides[(ax, -1)][0]; span0 = hi0 - lo0; action = "keep"
                if m_pos and m_neg and abs(span0 / D - 1) <= tolk: dbg["axes"].append((ax, "measured pair kept", round(span0, 2), round(D, 2))); continue
                if m_pos or m_neg:
                    keep = (win_side.get(ax) if (m_pos and m_neg and win_side.get(ax) is not None) else (1 if (m_pos and m_neg and support0(ax, 1) >= support0(ax, -1)) else (1 if m_pos and not m_neg else (-1 if m_neg and not m_pos else 1))))
                    lo, hi = (hi0 - D, hi0) if keep == 1 else (lo0, lo0 + D); action = f"anchor {'+' if keep == 1 else '-'}"
                else:
                    c0 = (max(np.max(fu[:, ax]) if len(fu) else cm[ax], cm[ax]) + min(np.min(fu[:, ax]) if len(fu) else cm[ax], cm[ax])) / 2
                    lo, hi = c0 - D / 2, c0 + D / 2; action = "centre"
                if lo > cmin: hi -= lo - cmin; lo = cmin; action += " slid"
                if hi < cmax: lo += cmax - hi; hi = cmax; action += " slid"
                # a wall that stayed where it was measured is still 'measured'; anything that moved is inferred
                sides[(ax, 1)] = (float(hi), not (m_pos and abs(hi - hi0) < 0.02)); sides[(ax, -1)] = (float(-lo), not (m_neg and abs(lo - lo0) < 0.02))
                vlm_used += [(ax, 1), (ax, -1)]; dbg["axes"].append((ax, action + (" grown" if grown else ""), round(span0, 2), round(hi - lo, 2), round(D, 2)))
        for ax in ((0, 1) if not strict_vlm else ()):
            m_pos, m_neg = not sides[(ax, 1)][1], not sides[(ax, -1)][1]; D = min(max(dim_for[ax], 1.8), 9.0)
            if m_pos and not m_neg: sides[(ax, -1)] = (-(sides[(ax, 1)][0] - D), True); vlm_used.append((ax, -1))
            elif m_neg and not m_pos: sides[(ax, 1)] = (-sides[(ax, -1)][0] + D, True); vlm_used.append((ax, 1))
            elif not m_pos and not m_neg:   # nothing measured on this axis: centre the VLM dimension on the seen floor, then slide it (not grow it) to keep the cameras inside
                c0 = (max(np.max(fu[:, ax]) if len(fu) else cm[ax], cm[ax]) + min(np.min(fu[:, ax]) if len(fu) else cm[ax], cm[ax])) / 2
                lo, hi = c0 - D / 2, c0 + D / 2; cmin, cmax = float(cu[:, ax].min()) - 0.5, float(cu[:, ax].max()) + 0.5
                if lo > cmin: hi -= lo - cmin; lo = cmin
                if hi < cmax: lo += cmax - hi; hi = cmax
                sides[(ax, 1)] = (hi, True); sides[(ax, -1)] = (-lo, True); vlm_used += [(ax, 1), (ax, -1)]
        # cap: geometry over-measures depth (VGGT stretches far walls), the VLM is reliable to ~10% on room dimensions.
        # A span more than 25% beyond the VLM dimension is pulled in on its weaker side (inferred first, else less support).
        # cameras must sit inside: extend an inferred side that falls short (a measured one too; the sanity below would anyway)
        for ax in ((0, 1) if not strict_vlm else ()):
            for sgn in (1, -1):
                need = float((cu[:, ax] * sgn).max()) + 0.5
                if sides[(ax, sgn)][0] < need: sides[(ax, sgn)] = (need, sides[(ax, sgn)][1])
        if not strict_vlm: dbg = {"before_cap": [float(sides[(0, 1)][0] + sides[(0, -1)][0]), float(sides[(1, 1)][0] + sides[(1, -1)][0])], "dim_for": [dim_for[0], dim_for[1]], "cam_spread": [float(np.ptp(cu[:, 0])), float(np.ptp(cu[:, 1]))], "capped": []}
        # cap: geometry over-measures depth (VGGT stretches far walls); the VLM is reliable to ~10% on room dimensions and a
        # printed plan dimension to a few percent. A span beyond the tolerance is pulled in on its weaker side (inferred first,
        # else less plane support) as far as the cameras allow; if that side cannot move, the other side is pulled instead.
        if not strict_vlm and float(vlm.get("size_confidence", 0)) >= 0.3:
            src = vlm.get("source"); tol = {"floor_plan": 1.08, "floor_plan_candidate": 1.15}.get(src, 1.25); goal = {"floor_plan": 1.0, "floor_plan_candidate": 1.05}.get(src, 1.1)
            def support(ax, sgn):
                if sides[(ax, sgn)][1]: return -1   # inferred: weakest
                dirv = A[ax] * sgn; best_px = 0
                for p in walls:
                    n = np.array([p["n"][0], p["n"][2]]); n = n / (np.linalg.norm(n) + 1e-9)
                    if abs(n @ dirv) < np.cos(np.radians(15)): continue
                    if abs(p["offset"] * (1 if n @ dirv > 0 else -1) - sides[(ax, sgn)][0]) < 0.1: best_px = max(best_px, p["extent"]["n_px"])
                return best_px
            for ax in (0, 1):
                D = min(max(dim_for[ax], 1.8), 9.0); span = sides[(ax, 1)][0] + sides[(ax, -1)][0]
                if span <= tol * D: continue
                for sgn in sorted((1, -1), key=lambda g: support(ax, g)):
                    target = max(goal * D - sides[(ax, -sgn)][0], float((cu[:, ax] * sgn).max()) + 0.5)
                    if target < sides[(ax, sgn)][0] - 0.05:
                        dbg["capped"].append((ax, sgn, round(float(sides[(ax, sgn)][0]), 2), round(float(target), 2), "measured" if not sides[(ax, sgn)][1] else "inferred"))
                        sides[(ax, sgn)] = (float(target), True); vlm_used.append((ax, sgn)); break
    lo_u, hi_u = -sides[(0, -1)][0], sides[(0, 1)][0]; lo_v, hi_v = -sides[(1, -1)][0], sides[(1, 1)][0]
    # sanity: keep cameras inside and sizes plausible
    lo_u = min(lo_u, cu[:, 0].min() - 0.5); hi_u = max(hi_u, cu[:, 0].max() + 0.5); lo_v = min(lo_v, cu[:, 1].min() - 0.5); hi_v = max(hi_v, cu[:, 1].max() + 0.5)
    corners_uv = np.array([[lo_u, lo_v], [hi_u, lo_v], [hi_u, hi_v], [lo_u, hi_v]]); V = corners_uv @ A    # back to xz (A orthonormal)
    if not Polygon(V).exterior.is_ccw: V = V[::-1]
    # edges: V[k] -> V[k+1]; mark inferred by matching each edge's outward normal to the side it came from
    cen = V.mean(0); n = len(V); E = [None] * n
    for k in range(n):
        a, b = V[k], V[(k + 1) % n]; d = b - a; L = np.linalg.norm(d); d = d / max(L, 1e-9); nn = np.array([d[1], -d[0]])
        if nn @ ((a + b) / 2 - cen) < 0: nn = -nn
        ax = 0 if abs(nn @ A[0]) > abs(nn @ A[1]) else 1; sgn = 1 if nn @ A[ax] > 0 else -1
        E[(k + 1) % n] = {"n": nn, "o": float(nn @ a), "w": float(L), "inferred": sides[(ax, sgn)][1]}
    return V, E, {"u": u.tolist(), "v": v.tolist(), "measured_sides": sum(1 for s_ in sides.values() if not s_[1]), "vlm_sides": len(vlm_used),
                  "spans": [float(hi_u - lo_u), float(hi_v - lo_v)], "dbg": dbg, "dim_for": ([dim_for[0], dim_for[1]] if (vlm and vlm.get("width_m") and vlm.get("depth_m")) else None), "axis_measured": [not sides[(0, 1)][1] and not sides[(0, -1)][1], not sides[(1, 1)][1] and not sides[(1, -1)][1]]}

def polygon_from_cell(fp, planes, eps_m=0.2, snap_dist=0.3, snap_ang=12.0, min_edge_m=0.3):
    """Contour of the wall cell -> simplified polygon -> each edge snaps to a fitted wall line when one is close (then the
    edge is 'real'), otherwise keeps its own line ('inferred'). Vertices are moved to the intersection of their two edge
    lines only when that intersection is near the original vertex; so the polygon stays valid by construction."""
    cnts, _ = cv2.findContours(fp["region"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE); cnt = max(cnts, key=cv2.contourArea)
    approx = cv2.approxPolyDP(cnt, eps_m / CELL, True)[:, 0, :].astype(float); P0 = approx * CELL + fp["lo"]
    if not Polygon(P0).exterior.is_ccw: P0 = P0[::-1]
    planes = [pl for pl in planes if pl["kind"] == "wall" and pl.get("extent")]
    walls = [(np.array([pl["n"][0], pl["n"][2]]), float(pl["offset"])) for pl in planes]
    best = max(planes, key=lambda p: p["extent"]["n_px"]) if planes else None
    dom = []
    if best is not None:
        n0 = np.array([best["n"][0], best["n"][2]]); n0 = n0 / (np.linalg.norm(n0) + 1e-9); dom = [n0, np.array([-n0[1], n0[0]])]
    n = len(P0); lines = []
    for k in range(n):
        a, b = P0[k], P0[(k + 1) % n]; d = b - a; L = np.linalg.norm(d); d = d / max(L, 1e-9); nn = np.array([d[1], -d[0]]); mid = (a + b) / 2; best = None
        for wn, wo in walls:
            ang = np.degrees(np.arccos(np.clip(abs(wn @ nn), 0, 1)))
            if ang > snap_ang: continue
            wn2, wo2 = (wn, wo) if wn @ nn > 0 else (-wn, -wo); dist = abs(wo2 - nn @ mid)
            if dist < snap_dist and (best is None or dist < best[0]): best = (dist, wn2, wo2)
        if best is None and dom:   # closure edges are never angled: take the nearest dominant direction
            cand = max(dom + [-d for d in dom], key=lambda v: v @ nn); nn = cand
        lines.append({"n": best[1] if best else nn, "o": best[2] if best else float(nn @ mid), "inferred": best is None, "len": float(L)})
    # merge consecutive edges on the same line (both snapped to one plane, or nearly collinear)
    changed = True
    while changed and len(P0) > 3:
        changed = False
        for k in range(len(P0)):
            e1, e2 = lines[(k - 1) % len(P0)], lines[k]
            if np.degrees(np.arccos(np.clip(e1["n"] @ e2["n"], -1, 1))) < 6 and abs(e1["o"] - e2["o"]) < 0.12:
                w = e1["len"] + e2["len"]; lines[(k - 1) % len(P0)] = {"n": e1["n"], "o": (e1["o"] * e1["len"] + e2["o"] * e2["len"]) / max(w, 1e-9), "inferred": e1["inferred"] and e2["inferred"], "len": w}
                P0 = np.delete(P0, k, 0); lines.pop(k); changed = True; break
    n = len(P0); V = P0.copy()
    for k in range(n):   # vertex k is the start of edge k and the end of edge k-1
        e1, e2 = lines[(k - 1) % n], lines[k]; A = np.array([e1["n"], e2["n"]]); det = np.linalg.det(A)
        if abs(det) > 0.2:
            x = np.linalg.solve(A, np.array([e1["o"], e2["o"]]))
            if np.linalg.norm(x - P0[k]) < 0.6: V[k] = x; continue
        for e in (e1, e2):   # nearly parallel or far intersection: project the vertex onto a snapped line
            if not e["inferred"]: V[k] = P0[k] - (e["n"] @ P0[k] - e["o"]) * e["n"]; break
    # drop edges shorter than min_edge_m by removing their end vertex
    keep = [k for k in range(n) if np.linalg.norm(V[(k + 1) % n] - V[k]) >= min_edge_m or n <= 4]
    if len(keep) >= 3: V = V[keep]; lines = [lines[k] for k in keep]
    n = len(V)
    if not Polygon(V).is_valid: V = P0[keep] if len(keep) >= 3 else P0
    E = [None] * n
    for k in range(n): E[(k + 1) % n] = {"n": lines[k]["n"], "o": lines[k]["o"], "w": lines[k]["len"], "inferred": lines[k]["inferred"]}
    return V, E

def openings_from_masks(room, segl, edges, P, min_area_px=300):
    """Window/door mask components per photo -> rectangle on the wall plane they sit on (pixel rays intersected with the
    plane: no depth needed). Merged across photos per wall by overlap."""
    from fuse import cam_matrices
    Sn, H, W = segl.shape; out = []
    for i in range(Sn):
        R, c, K = cam_matrices(room, P, i)
        for cls, kind in ((S.WINDOW, "window"), (S.DOOR, "door")):
            m = (segl[i] == cls).astype(np.uint8)
            if m.sum() < min_area_px: continue
            n, lab, st, _ = cv2.connectedComponentsWithStats(m)
            for j in range(1, n):
                if st[j, cv2.CC_STAT_AREA] < min_area_px: continue
                comp = lab == j; ys, xs = np.nonzero(comp)
                # which wall: majority edge id of wall pixels in a ring around the component
                ring = cv2.dilate(comp.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool) & ~comp & (room["edge_id"][i] >= 0)
                if ring.sum() < 30: continue
                ks, cnts = np.unique(room["edge_id"][i][ring], return_counts=True); order = [int(k_) for k_ in ks[np.argsort(-cnts)] if cnts[list(ks).index(k_)] >= 0.15 * cnts.sum()]
                sub = np.random.default_rng(0).choice(len(xs), min(len(xs), 4000), replace=False); u, v = xs[sub].astype(float), ys[sub].astype(float)
                x = (u - K[0, 2]) / K[0, 0]; y = (v - K[1, 2]) / K[1, 1]; d = np.stack([x, -y, np.ones_like(x)], -1) @ R
                found = None
                for k in order:   # the right wall is the one the mask's rays actually land on, inside its extent
                    e = edges[k]; n3 = np.array([e["n"][0], 0.0, e["n"][1]]); a3 = np.array([e["a"][0], 0.0, e["a"][1]]); d3 = np.array([e["dir"][0], 0.0, e["dir"][1]])
                    dn = d @ n3; ok = np.abs(dn) > 1e-3; t = (e["offset"] - c @ n3) / np.where(ok, dn, 1); ok &= t > 0.1
                    if ok.sum() < 50: continue
                    h = c + t[ok, None] * d[ok]; s_ = (h - a3) @ d3; yy = h[:, 1]; inside = (s_ > -0.05) & (s_ < e["len"] + 0.05) & (yy > -0.05) & (yy < room["ceil_m"] + 0.05)
                    if inside.mean() < 0.6: continue
                    s_, yy = s_[inside], yy[inside]; found = (k, e, s_, yy); break
                if found is None: continue
                k, e, s_, yy = found
                s0, s1 = np.quantile(s_, [0.03, 0.97]); y0, y1 = np.quantile(yy, [0.03, 0.97])
                s0, s1 = max(0.0, s0), min(e["len"], s1); y0, y1 = max(0.0, y0), min(room["ceil_m"], y1)
                if s1 - s0 < 0.25 or y1 - y0 < 0.3: continue
                out.append({"kind": kind, "edge": k, "img": i, "s0": float(s0), "s1": float(s1), "sill_m": float(y0), "height_m": float(y1 - y0), "width_m": float(s1 - s0), "px": int(comp.sum())})
    # merge per edge/kind by overlap along the wall
    merged = []
    for o in sorted(out, key=lambda o: -o["px"]):
        hit = None
        for mg in merged:
            if mg["edge"] == o["edge"] and mg["kind"] == o["kind"] and min(mg["s1"], o["s1"]) - max(mg["s0"], o["s0"]) > 0.3 * min(mg["width_m"], o["width_m"]): hit = mg; break
        if hit: hit["n_views"] += 1   # keep the largest view's rectangle
        else: merged.append({**o, "n_views": 1})
    for o in merged:
        e = edges[o["edge"]]; a = np.array(e["a"]); d = np.array(e["dir"]); cxz = a + d * (o["s0"] + o["s1"]) / 2
        o["center"] = [round(float(cxz[0]), 3), round(float(o["sill_m"] + o["height_m"] / 2), 3), round(float(cxz[1]), 3)]; o["normal"] = [float(e["n"][0]), 0.0, float(e["n"][1])]; o["score"] = 1.0
        for k_ in ("s0", "s1", "sill_m", "height_m", "width_m"): o[k_] = round(o[k_], 3)
    return merged


def openings_by_rays(room, segl, V, edges, P, min_area_px=300):
    """Path A openings: each window/door mask component is ray-cast from its camera onto the BOX (pano.shell_hit), so a wall
    needs no measured plane under it. Majority wall wins; extents from the hit points' quantiles."""
    from fuse import cam_matrices; import pano
    Sn, H, W = segl.shape; ceil_m = float(room["ceil_m"]); V = np.asarray(V, float); out = []; rng = np.random.default_rng(0)
    for i in range(Sn):
        R, c, K = cam_matrices(room, P, i)
        for cls, kind in ((S.WINDOW, "window"), (S.DOOR, "door")):
            m = (segl[i] == cls).astype(np.uint8)
            if m.sum() < min_area_px: continue
            n, lab, st, _ = cv2.connectedComponentsWithStats(m)
            for j in range(1, n):
                if st[j, cv2.CC_STAT_AREA] < min_area_px: continue
                ys, xs = np.nonzero(lab == j); sub = rng.choice(len(xs), min(len(xs), 4000), replace=False); u, v = xs[sub].astype(float), ys[sub].astype(float)
                x = (u - K[0, 2]) / K[0, 0]; y = (v - K[1, 2]) / K[1, 1]; d = np.stack([x, -y, np.ones_like(x)], -1) @ R; d /= np.linalg.norm(d, axis=1, keepdims=True)
                t, sid = pano.shell_hit(c, d, V, ceil_m); walls = sid >= 0
                if walls.mean() < 0.5: continue
                ks, cnts = np.unique(sid[walls], return_counts=True); k = int(ks[np.argmax(cnts)])
                if cnts.max() < 0.6 * walls.sum(): continue
                selk = sid == k; h = c + t[selk, None] * d[selk]; e = edges[k]; a3 = np.array([e["a"][0], 0.0, e["a"][1]]); d3 = np.array([e["dir"][0], 0.0, e["dir"][1]])
                s_ = (h - a3) @ d3; yy = h[:, 1]
                s0, s1 = np.quantile(s_, [0.03, 0.97]); y0, y1 = np.quantile(yy, [0.03, 0.97])
                s0, s1 = max(0.0, s0), min(e["len"], s1); y0, y1 = max(0.0, y0), min(ceil_m, y1)
                if s1 - s0 < 0.25 or y1 - y0 < 0.3: continue
                out.append({"kind": kind, "edge": k, "img": i, "s0": float(s0), "s1": float(s1), "sill_m": float(y0), "height_m": float(y1 - y0), "width_m": float(s1 - s0), "px": int(st[j, cv2.CC_STAT_AREA])})
    merged = []
    for o in sorted(out, key=lambda o: -o["px"]):
        hit = None
        for mg in merged:
            if mg["edge"] == o["edge"] and mg["kind"] == o["kind"] and min(mg["s1"], o["s1"]) - max(mg["s0"], o["s0"]) > 0.3 * min(mg["width_m"], o["width_m"]): hit = mg; break
        if hit: hit["n_views"] += 1
        else: merged.append({**o, "n_views": 1})
    for o in merged:
        e = edges[o["edge"]]; a = np.array(e["a"]); dd = np.array(e["dir"]); cxz = a + dd * (o["s0"] + o["s1"]) / 2
        o["center"] = [round(float(cxz[0]), 3), round(float(o["sill_m"] + o["height_m"] / 2), 3), round(float(cxz[1]), 3)]; o["normal"] = [float(e["n"][0]), 0.0, float(e["n"][1])]; o["score"] = 1.0
        for k_ in ("s0", "s1", "sill_m", "height_m", "width_m"): o[k_] = round(o[k_], 3)
    return merged
