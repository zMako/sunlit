"""Phase 2: floor plan from free space. Camera-to-surface rays carve a top-down occupancy grid; the free region
around the cameras becomes a rectilinear polygon; wall pixels snap onto polygon edges; openings are lifted onto walls;
photo pixels are splatted into per-wall and floor textures."""
import numpy as np, cv2
from shapely.geometry import Polygon
from geometry import FLOOR, CEIL, WALL, OTHER

CELL = 0.05

def carve(room, band=(1.0, 2.1), max_ray=9.0, step=2):
    pts, labels, good, cams = room["pts"], room["labels"], room["good"], room["cams"]; S = pts.shape[0]
    allp = pts[good]; lo = np.minimum(allp[:, [0, 2]].min(0), cams[:, [0, 2]].min(0)) - 1.0; hi = np.maximum(allp[:, [0, 2]].max(0), cams[:, [0, 2]].max(0)) + 1.0
    lo = np.floor(lo / CELL) * CELL; n = np.ceil((hi - lo) / CELL).astype(int) + 1; W, H = int(n[0]), int(n[1])
    free = np.zeros((H, W), np.float32); hit = np.zeros((H, W), np.float32)
    def cell(xz): return ((xz - lo) / CELL).astype(int)
    for i in range(S):
        P = pts[i][::step, ::step]; L = labels[i][::step, ::step]; G = good[i][::step, ::step]
        y = P[..., 1]; m = G & (y > band[0]) & (y < band[1])
        Q = P[m][:, [0, 2]]; lab = L[m]; c = cams[i][[0, 2]]
        d = Q - c; dist = np.linalg.norm(d, axis=1); keep = dist < max_ray; Q, lab, d, dist = Q[keep], lab[keep], d[keep], dist[keep]
        if len(Q) > 12000: s = np.random.default_rng(i).choice(len(Q), 12000, replace=False); Q, lab, d, dist = Q[s], lab[s], d[s], dist[s]
        c0 = cell(c)
        for q, lb, dd in zip(Q, lab, dist):
            q0 = cell(q); nseg = int(dd / CELL) + 1
            xs = np.linspace(c0[0], q0[0], nseg).astype(int); zs = np.linspace(c0[1], q0[1], nseg).astype(int)
            # free along the ray except the last 2 cells
            k = max(1, nseg - 2); free[zs[:k], xs[:k]] += 1
            if lb == WALL: hit[q0[1], q0[0]] += 1
    # free region: enough rays through, not an obstacle
    thr = 3 if S == 1 else 5
    F = (free >= thr) & (free > 2 * hit)
    F = cv2.morphologyEx(F.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    # fill interior holes (islands, furniture): everything not reachable from the border is room
    inv = (1 - F).astype(np.uint8); nl, lab = cv2.connectedComponents(inv); border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    F[np.isin(lab, [k for k in range(1, nl) if k not in border])] = 1
    # remove narrow leaks through doorways: opening with a 0.6 m kernel
    k = int(0.85 / CELL); F = cv2.morphologyEx(F, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    nlab, cc = cv2.connectedComponents(F)
    camcells = cell(cams[:, [0, 2]]); r = int(1.0 / CELL); votes = {}
    for x, z in camcells:
        win = cc[max(z - r, 0):z + r + 1, max(x - r, 0):x + r + 1]; ids, cnt = np.unique(win[win > 0], return_counts=True)
        for i_, c_ in zip(ids, cnt): votes[int(i_)] = votes.get(int(i_), 0) + int(c_)
    if not votes: raise RuntimeError("no free region near any camera")
    region = (cc == max(votes, key=votes.get)).astype(np.uint8)
    return {"free": free, "hit": hit, "region": region, "lo": lo, "W": W, "H": H}

def general_polygon(region, lo, planes, eps_m=0.25, min_edge_m=0.5, snap_dist=0.45, snap_ang=15.0):
    """Contour -> edges; each contour edge snaps to a fitted wall plane line (direction within snap_ang, distance within
    snap_dist) else keeps its own line (FOV boundary, marked inferred). Consecutive near-collinear edges merge; short edges
    are removed by intersecting their neighbours. Returns vertices (N,2) and per-edge info; None if degenerate."""
    from shapely.geometry import Polygon
    cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnt = max(cnts, key=cv2.contourArea); approx = cv2.approxPolyDP(cnt, eps_m / CELL, True)[:, 0, :].astype(float)
    P = approx * CELL + lo
    if Polygon(P).exterior.is_ccw is False: P = P[::-1]
    walls = [(np.array([p["n"][0], p["n"][2]]), p["offset"]) for p in planes if p["kind"] == "wall"]
    cen = P.mean(0)
    def line_of(a, b):
        d = b - a; L = np.linalg.norm(d); d = d / max(L, 1e-9); n = np.array([d[1], -d[0]])   # CCW polygon: right-hand normal points outward
        return n, float(n @ (a + b) / 2), L
    E = []
    for k in range(len(P)):
        a, b = P[k], P[(k + 1) % len(P)]; n, o, L = line_of(a, b); inferred = True
        best = None
        for wn, wo in walls:
            ang = np.degrees(np.arccos(np.clip(abs(wn @ n), 0, 1)))
            if ang > snap_ang: continue
            wn2, wo2 = (wn, wo) if wn @ n > 0 else (-wn, -wo)
            dist = abs(wo2 - n @ (a + b) / 2)
            if dist < snap_dist and (best is None or dist < best[0]): best = (dist, wn2, wo2)
        if best: n, o, inferred = best[1], best[2], False
        else:
            # no plane under this contour edge: regularize its direction to the nearest fitted wall direction (within 20 deg)
            cand = None
            for wn, _ in walls:
                for sgn in (1, -1):
                    ang = np.degrees(np.arccos(np.clip((sgn * wn) @ n, -1, 1)))
                    if ang < 20 and (cand is None or ang < cand[0]): cand = (ang, sgn * wn)
            if cand: n = cand[1]; o = float(n @ (a + b) / 2)
        E.append({"n": n, "o": o, "w": L, "inferred": inferred})
    def merge(E):
        out = []
        for e in E:
            if out and np.degrees(np.arccos(np.clip(out[-1]["n"] @ e["n"], -1, 1))) < 8 and abs(out[-1]["o"] - e["o"]) < 0.25:
                w = out[-1]["w"] + e["w"]; n = out[-1]["n"] * out[-1]["w"] + e["n"] * e["w"]; n /= np.linalg.norm(n)
                out[-1] = {"n": n, "o": (out[-1]["o"] * out[-1]["w"] + e["o"] * e["w"]) / w, "w": w, "inferred": out[-1]["inferred"] and e["inferred"]}
            else: out.append(dict(e))
        if len(out) > 1 and np.degrees(np.arccos(np.clip(out[0]["n"] @ out[-1]["n"], -1, 1))) < 8 and abs(out[0]["o"] - out[-1]["o"]) < 0.25:
            w = out[0]["w"] + out[-1]["w"]; n = out[0]["n"] * out[0]["w"] + out[-1]["n"] * out[-1]["w"]; n /= np.linalg.norm(n)
            out[0] = {"n": n, "o": (out[0]["o"] * out[0]["w"] + out[-1]["o"] * out[-1]["w"]) / w, "w": w, "inferred": out[0]["inferred"] and out[-1]["inferred"]}; out.pop()
        return out
    def vertices(E):
        V = []
        for k in range(len(E)):
            e1, e2 = E[k], E[(k + 1) % len(E)]; A = np.array([e1["n"], e2["n"]]); det = np.linalg.det(A)
            if abs(det) < 0.15: return None
            V.append(np.linalg.solve(A, np.array([e1["o"], e2["o"]])))
        return np.array(V)
    E0 = [dict(e) for e in E]; E = merge(E)
    for _ in range(40):
        if len(E) < 3: break
        V = vertices(E)
        if V is None:
            # nearly parallel consecutive lines: drop the shorter of the pair
            k = min(range(len(E)), key=lambda k: E[k]["w"]); E.pop(k); E = merge(E); continue
        L = [np.linalg.norm(V[k] - V[k - 1]) for k in range(len(V))]   # edge k runs V[k-1] -> V[k]
        k = int(np.argmin(L))
        if L[k] >= min_edge_m or len(E) <= 3: break
        E.pop(k); E = merge(E)
    V = vertices(E) if len(E) >= 3 else None
    def ok(V):
        try: return V is not None and len(V) >= 3 and Polygon(V).is_valid and Polygon(V).area >= 2.0
        except Exception: return False
    if ok(V): return V, E
    # fallback 1: merged edges only (no short-edge removal)
    E1 = merge(E0); V1 = vertices(E1)
    if ok(V1): return V1, E1
    # fallback 2: the simplified contour itself, each edge marked inferred unless a plane sits under it
    P2 = approx * CELL + lo
    if Polygon(P2).exterior.is_ccw is False: P2 = P2[::-1]
    E2 = []
    for k in range(len(P2)):
        n_, o_, w_ = line_of(P2[k], P2[(k + 1) % len(P2)]); mid = (P2[k] + P2[(k + 1) % len(P2)]) / 2
        near = any(np.degrees(np.arccos(np.clip(abs(wn @ n_), 0, 1))) < snap_ang and abs((wo if wn @ n_ > 0 else -wo) - n_ @ mid) < snap_dist for wn, wo in walls)
        E2.append({"n": n_, "o": o_, "w": w_, "inferred": not near})
    # E[k] must describe the edge ending at V[k] (vertex k = intersection of E[k], E[k+1]) to match edges_of()
    E2 = [E2[(k - 1) % len(E2)] for k in range(len(E2))]
    return (P2, E2) if ok(P2) else (None, None)

def single_photo_rectangle(room, planes, carved):
    """One photo cannot bound a room. Plausible rectangle: side and far walls from fitted planes (or the carve extent),
    closed 1.5 m behind the camera. Edges that no plane supports are marked inferred."""
    cam = room["cams"][0]; fwd = np.array(room["cam_basis"][0]["fwd"]); fx, fz = fwd[0], fwd[2]
    # room frame is Manhattan-aligned: pick the axis the camera looks along
    along = 2 if abs(fz) >= abs(fx) else 0; across = 0 if along == 2 else 2; sgn = np.sign(fwd[along]) or 1.0
    walls = [p for p in planes if p["kind"] == "wall" and p.get("extent")]
    def offs(axis, want_sign):
        n_idx = 0 if axis == 0 else 2
        return [p["offset"] * (1 if p["n"][n_idx] > 0 else -1) for p in walls if abs(p["n"][n_idx]) > 0.9 and np.sign(p["n"][n_idx] * (p["offset"] * (1 if p["n"][n_idx] > 0 else -1) - cam[axis])) == want_sign]
    reg = carved["region"]; lo = carved["lo"]; ys, xs = np.nonzero(reg); ext = {0: (lo[0] + xs.min() * CELL, lo[0] + xs.max() * CELL), 2: (lo[1] + ys.min() * CELL, lo[1] + ys.max() * CELL)}
    far_c = [p["offset"] * (1 if p["n"][2 if along == 2 else 0] > 0 else -1) for p in walls if abs(p["n"][2 if along == 2 else 0]) > 0.9]
    far_c = [o for o in far_c if (o - cam[along]) * sgn > 0.5]; far = (min(far_c, key=lambda o: abs(o - cam[along])) if far_c else (ext[along][1] if sgn > 0 else ext[along][0]))
    near = cam[along] - sgn * 1.5
    side_c = [p["offset"] * (1 if p["n"][2 if across == 2 else 0] > 0 else -1) for p in walls if abs(p["n"][2 if across == 2 else 0]) > 0.9]
    left = [o for o in side_c if o < cam[across] - 0.3]; right = [o for o in side_c if o > cam[across] + 0.3]
    s0 = max(left) if left else ext[across][0]; s1 = min(right) if right else ext[across][1]
    if s1 - s0 < 2.0: s0, s1 = cam[across] - 2.0, cam[across] + 2.0
    a0, a1 = (near, far) if sgn > 0 else (far, near)
    pts = [[s0, a0], [s1, a0], [s1, a1], [s0, a1]] if along == 2 else [[a0, s0], [a1, s0], [a1, s1], [a0, s1]]
    V = np.array(pts, float)
    if Polygon(V).exterior.is_ccw is False: V = V[::-1]
    E = [{"n": None, "o": None, "w": 1.0, "inferred": True} for _ in range(4)]
    return V, E

def close_behind_camera(V, E, room, planes, back=1.5):
    """Single photo: keep the carved polygon (bay panes included) but close it 1.5 m behind the camera instead of at the
    field-of-view wedge. Edges with a fitted wall plane under them are real; the rest are marked inferred."""
    from shapely.geometry import Polygon as _P
    cam = room["cams"][0]; fwd = np.array(room["cam_basis"][0]["fwd"]); f2 = np.array([fwd[0], fwd[2]]); f2 = f2 / (np.linalg.norm(f2) + 1e-9)
    cam2 = np.array([cam[0], cam[2]]); c0 = cam2 - f2 * back; t = np.array([-f2[1], f2[0]]); big = 60.0
    rect = _P([c0 + t * big, c0 - t * big, c0 - t * big + f2 * big, c0 + t * big + f2 * big])
    P = _P(V).intersection(rect)
    if P.is_empty or P.geom_type != "Polygon": return V, E
    P = P.simplify(0.03); V2 = np.array(P.exterior.coords[:-1])
    if not _P(V2).exterior.is_ccw: V2 = V2[::-1]
    walls = [(np.array([p["n"][0], p["n"][2]]), p["offset"]) for p in planes if p["kind"] == "wall"]; n = len(V2); E2 = [None] * n
    for k in range(n):
        a, b = V2[k], V2[(k + 1) % n]; d = b - a; L = float(np.linalg.norm(d)); d = d / max(L, 1e-9); nn = np.array([d[1], -d[0]]); mid = (a + b) / 2
        inf = not any(abs(wn @ nn) > np.cos(np.radians(15)) and abs(abs(wo) - abs(wn @ mid)) < 0.3 for wn, wo in walls)
        E2[(k + 1) % n] = {"n": nn, "o": float(nn @ mid), "w": L, "inferred": inf}
    return V2, E2

def poly_area(V): x, z = V[:, 0], V[:, 1]; return 0.5 * abs(np.dot(x, np.roll(z, 1)) - np.dot(z, np.roll(x, 1)))

def edges_of(V, E=None):
    """Edge k runs V[k] -> V[k+1]; outward unit normal n (xz), offset o = n . point, direction along the wall."""
    V = np.asarray(V, float); cen = V.mean(0); out = []
    for k in range(len(V)):
        a, b = V[k], V[(k + 1) % len(V)]; d = b - a; L = float(np.linalg.norm(d)); d = d / max(L, 1e-9); n = np.array([d[1], -d[0]])
        if n @ ((a + b) / 2 - cen) < 0: n = -n
        inferred = bool(E[(k + 1) % len(E)]["inferred"]) if E is not None and len(E) == len(V) else False
        out.append({"a": a.tolist(), "b": b.tolist(), "n": n.tolist(), "offset": float(n @ a), "dir": d.tolist(), "len": L, "inferred": inferred,
                    "axis": 0 if abs(n[0]) > abs(n[1]) else 2})   # axis kept for legacy readers; approximate
    return out

def snap_to_edges(room, edges, tol=0.3):
    """Ray-snap wall pixels onto the nearest polygon edge plane; returns per-pixel edge id (-1 none)."""
    pts, labels, cams = room["pts"], room["labels"], room["cams"]; S = pts.shape[0]
    edge_id = np.full(labels.shape, -1, np.int16); moved = 0
    for i in range(S):
        m = labels[i] == WALL
        if not m.any(): continue
        q = pts[i][m]; best_d = np.full(len(q), np.inf); best = np.full(len(q), -1)
        for k, e in enumerate(edges):
            a, b = np.array(e["a"]), np.array(e["b"]); t = np.clip(((q[:, [0, 2]] - a) @ (b - a)) / max(1e-9, (b - a) @ (b - a)), 0, 1)
            proj = a + t[:, None] * (b - a); d = np.linalg.norm(q[:, [0, 2]] - proj, axis=1)
            better = d < best_d; best_d[better] = d[better]; best[better] = k
        okk = best_d < tol; idx = np.argwhere(m)[okk]; ids = best[okk]
        c = cams[i]; d3 = pts[i][idx[:, 0], idx[:, 1]] - c; nrm_i = room["normals"][i][idx[:, 0], idx[:, 1]]
        for k in np.unique(ids):
            sel = ids == k; e = edges[k]; n3 = np.array([e["n"][0], 0.0, e["n"][1]])
            agree = np.abs(nrm_i[sel] @ n3) > np.cos(np.radians(20)); resid = np.abs(pts[i][idx[sel][:, 0], idx[sel][:, 1]] @ n3 - e["offset"]) < 0.10
            dn = d3[sel] @ n3; t = (e["offset"] - c @ n3) / np.where(np.abs(dn) < 1e-6, 1e-6, dn); okt = (t > 0.8) & (t < 1.2) & agree & resid
            ii = idx[sel][okt]; pts[i][ii[:, 0], ii[:, 1]] = c + t[okt, None] * d3[sel][okt]; edge_id[i][ii[:, 0], ii[:, 1]] = k; moved += int(okt.sum())
            # pixels near the edge but not snapped still belong to it for texturing
            ii2 = idx[sel][~okt & (best_d[okk][sel] < 0.15)]; edge_id[i][ii2[:, 0], ii2[:, 1]] = k
    room["edge_id"] = edge_id; return moved

def wall_textures(room, edges, res=0.025):
    """Splat snapped wall pixels into a per-edge texture (along x height). Unseen cells: LaMa inpainting when the wall is
    partly seen, the room's median wall colour when it is unseen. Returns images + seen masks (provenance)."""
    import lama
    pts, rgb, eid = room["pts"], room["rgb"], room["edge_id"]; ceil_m = room["ceil_m"]; raw = []; gen = room.get("generated")
    for k, e in enumerate(edges):
        a, b = np.array(e["a"]), np.array(e["b"]); L = e["len"]; nx, ny = max(8, int(L / res)), max(8, int(ceil_m / res))
        acc = np.zeros((ny, nx, 3), np.float64); cnt = np.zeros((ny, nx), np.float64); m = eid == k
        if m.any():
            q = pts[m]; col = rgb[m].astype(np.float64)
            t = ((q[:, [0, 2]] - a) @ (b - a)) / max(1e-9, L * L); u = np.clip((t * nx).astype(int), 0, nx - 1); v = np.clip(((1 - q[:, 1] / ceil_m) * ny).astype(int), 0, ny - 1)
            np.add.at(acc, (v, u), col); np.add.at(cnt, (v, u), 1)
        seen = cnt > 0; img = np.zeros((ny, nx, 3), np.uint8)
        if seen.any(): img[seen] = (acc[seen] / cnt[seen][:, None]).astype(np.uint8)
        gfrac = 0.0
        if gen is not None and m.any():
            gcnt = np.zeros((ny, nx), np.float64); np.add.at(gcnt, (v, u), gen[m].astype(np.float64)); gfrac = float((gcnt > 0.5 * np.maximum(cnt, 1))[seen].mean()) if seen.any() else 0.0
        raw.append((img, seen, gfrac))
    allseen = np.concatenate([im[sn] for im, sn, _ in raw if sn.any()]) if any(sn.any() for _, sn, _ in raw) else np.array([[200, 196, 190]])
    wall_col = np.median(allseen, 0).astype(np.uint8); tex = []
    for k, (img, seen, gfrac) in enumerate(raw):
        frac = float(seen.mean())
        if frac >= 0.995: out = img
        elif frac > 0.04:
            # close pinholes first, then LaMa for the real gaps
            img2 = img.copy(); img2[~seen] = wall_col
            out = lama.inpaint(img2, ~seen)
        else: out = np.tile(wall_col, (img.shape[0], img.shape[1], 1))
        tex.append({"img": out, "seen": seen, "seen_frac": frac, "inpainted_frac": float(1 - frac) if frac > 0.04 else 1.0, "generated_frac": gfrac})
    return tex

def floor_texture(room, V, res=0.025):
    pts, rgb, labels = room["pts"], room["rgb"], room["labels"]; lo = V.min(0); hi = V.max(0)
    nx, nz = max(2, int((hi[0] - lo[0]) / res)), max(2, int((hi[1] - lo[1]) / res))
    acc = np.zeros((nz, nx, 3), np.float64); cnt = np.zeros((nz, nx), np.float64); m = labels == FLOOR
    q = pts[m]; col = rgb[m].astype(np.float64)
    u = np.clip(((q[:, 0] - lo[0]) / (hi[0] - lo[0]) * nx).astype(int), 0, nx - 1); v = np.clip(((q[:, 2] - lo[1]) / (hi[1] - lo[1]) * nz).astype(int), 0, nz - 1)
    np.add.at(acc, (v, u), col); np.add.at(cnt, (v, u), 1); seen = cnt > 0; img = np.zeros((nz, nx, 3), np.uint8)
    if seen.any():
        img[seen] = (acc[seen] / cnt[seen][:, None]).astype(np.uint8)
        dense = cv2.morphologyEx(seen.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)).astype(bool); holes = dense & ~seen
        if holes.any(): img = cv2.inpaint(img, holes.astype(np.uint8) * 255, 2, cv2.INPAINT_TELEA); seen = dense
        med = np.median(img[seen], 0).astype(np.uint8); img[~seen] = med
        # only inpaint inside the room polygon; outside stays median
        from shapely.geometry import Polygon, Point
        poly = Polygon(V); ys, xs = np.mgrid[0:nz, 0:nx]; px = lo[0] + (xs + 0.5) / nx * (hi[0] - lo[0]); pz = lo[1] + (ys + 0.5) / nz * (hi[1] - lo[1])
        inside = np.array([poly.contains(Point(x_, z_)) for x_, z_ in zip(px.ravel(), pz.ravel())]).reshape(nz, nx)
        fill = (~seen) & inside
        if 0.04 < seen[inside].mean() < 0.995 and fill.any():
            import lama; img = lama.inpaint(img, fill)
    return {"img": img, "lo": lo.tolist(), "hi": hi.tolist(), "seen_frac": float(seen.mean())}

def detect_openings(room, edges, thr=0.15):
    """OWLv2 windows/doors per photo, lifted to 3D via snapped wall pixels around the box, projected onto the wall edge."""
    import torch
    from transformers import Owlv2Processor, Owlv2ForObjectDetection
    from PIL import Image
    proc = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble"); det = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").eval()
    pts, rgb, eid, labels = room["pts"], room["rgb"], room["edge_id"], room["labels"]; S, H, W = labels.shape; out = []
    queries = [["a window", "a door"]]
    for i in range(S):
        im = Image.fromarray(rgb[i]); inp = proc(text=queries, images=im, return_tensors="pt")
        with torch.no_grad(): o = det(**inp)
        r = proc.post_process_grounded_object_detection(o, threshold=thr, target_sizes=torch.tensor([[max(im.size)] * 2]), text_labels=queries)[0]
        for b, s, l in zip(r["boxes"], r["scores"], r["labels"]):
            x0, y0, x1, y1 = [int(v) for v in b]; x0, x1 = np.clip([x0, x1], 0, W - 1); y0, y1 = np.clip([y0, y1], 0, H - 1)
            if x1 - x0 < 12 or y1 - y0 < 12: continue
            # ring of wall pixels around the box that snapped to an edge
            ring = np.zeros((H, W), bool); X0, Y0, X1, Y1 = max(x0 - 14, 0), max(y0 - 14, 0), min(x1 + 14, W - 1), min(y1 + 14, H - 1)
            ring[Y0:Y1 + 1, X0:X1 + 1] = True; ring[max(y0 - 4, 0):min(y1 + 4, H - 1) + 1, max(x0 - 4, 0):min(x1 + 4, W - 1) + 1] = False
            ring_e = ring & (eid[i] >= 0)
            if ring_e.sum() >= 40:
                ks, cnts = np.unique(eid[i][ring_e], return_counts=True); k = int(ks[np.argmax(cnts)]); e = edges[k]
            else:
                # fallback: a Phase-1 fitted wall plane under the box (single-photo rooms where the carve has no edge there)
                pid = room["plane_id"][i]; ring_p = ring & (pid >= 2)
                if ring_p.sum() < 40: continue
                ks, cnts = np.unique(pid[ring_p], return_counts=True); pk = int(ks[np.argmax(cnts)]); pl = room["planes"][pk]
                if pl["kind"] != "wall" or not pl.get("extent"): continue
                ex_ = pl["extent"]; A, B = ex_["a"], ex_["b"]
                e = {"a": A, "b": B, "n": [pl["n"][0], pl["n"][2]], "offset": pl["offset"], "len": ex_["len"], "axis": 0 if abs(pl["n"][0]) > abs(pl["n"][2]) else 2}; k = -1
            # lift box corners by intersecting the pixel rays with the edge plane
            c = room["cams"][i]; K_right = np.array(room["cam_basis"][i]["right"]); K_up = np.array(room["cam_basis"][i]["up"]); K_fwd = np.array(room["cam_basis"][i]["fwd"])
            fx = W / (2 * np.tan(np.radians(room["cam_basis"][i]["fov_h"] / 2))); fy = H / (2 * np.tan(np.radians(room["cam_basis"][i]["fov_v"] / 2)))
            corners = []
            n3 = np.array([e["n"][0], 0.0, e["n"][1]])
            for (u, v) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                d = K_fwd + (u - W / 2) / fx * K_right - (v - H / 2) / fy * K_up; dn = d @ n3
                t = (e["offset"] - c @ n3) / (dn if abs(dn) > 1e-6 else 1e-6)
                if t <= 0: break
                corners.append(c + t * d)
            if len(corners) < 4: continue
            C = np.array(corners); along = np.array(e["b"]) - np.array(e["a"]); along /= np.linalg.norm(along); along3 = np.array([along[0], 0, along[1]])
            s_along = (C - np.array([e["a"][0], 0, e["a"][1]])) @ along3
            width = float(s_along.max() - s_along.min()); bottom = float(C[:, 1].min()); top = float(C[:, 1].max())
            if width < 0.3 or width > 4 or top - bottom < 0.3: continue
            kind = ["window", "door"][int(l)]
            if kind == "door" and not (bottom < 0.35 and 1.6 < top - bottom < 2.6 and width < 1.6): continue
            if kind == "window" and (bottom > 1.8 or top - bottom < 0.4 or width > 2.6 or top - bottom > 2.6): continue
            center = np.array([e["a"][0], 0, e["a"][1]]) + along3 * float(s_along.mean()); center[1] = (top + bottom) / 2
            out.append({"kind": kind, "score": round(float(s), 2), "img": i, "edge": k, "box": [int(x0), int(y0), int(x1), int(y1)], "center": center.round(3).tolist(),
                        "normal": [float(e["n"][0]), 0.0, float(e["n"][1])], "width_m": round(width, 2), "height_m": round(top - bottom, 2), "sill_m": round(bottom, 2), "s0": float(s_along.min()), "s1": float(s_along.max())})
    # dedupe per edge: merge boxes overlapping along the wall
    final = []
    for o in sorted(out, key=lambda o: -o["score"]):
        if any(f["edge"] == o["edge"] and f["kind"] == o["kind"] and min(f["s1"], o["s1"]) - max(f["s0"], o["s0"]) > 0.3 * min(f["width_m"], o["width_m"]) for f in final): continue
        final.append(o)
    # orient normals outward (away from polygon interior) later in export; here keep axis sign from edge midpoint vs polygon centroid
    return final
