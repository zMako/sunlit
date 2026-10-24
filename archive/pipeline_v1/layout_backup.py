"""Phase 2: floor plan from free space. Camera-to-surface rays carve a top-down occupancy grid; the free region
around the cameras becomes a rectilinear polygon; wall pixels snap onto polygon edges; openings are lifted onto walls;
photo pixels are splatted into per-wall and floor textures."""
import numpy as np, cv2
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
    k = int(0.6 / CELL); F = cv2.morphologyEx(F, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    nlab, cc = cv2.connectedComponents(F)
    camcells = cell(cams[:, [0, 2]]); r = int(1.0 / CELL); votes = {}
    for x, z in camcells:
        win = cc[max(z - r, 0):z + r + 1, max(x - r, 0):x + r + 1]; ids, cnt = np.unique(win[win > 0], return_counts=True)
        for i_, c_ in zip(ids, cnt): votes[int(i_)] = votes.get(int(i_), 0) + int(c_)
    if not votes: raise RuntimeError("no free region near any camera")
    region = (cc == max(votes, key=votes.get)).astype(np.uint8)
    return {"free": free, "hit": hit, "region": region, "lo": lo, "W": W, "H": H}

def rectilinear_polygon(region, lo, eps_m=0.25, min_edge_m=0.6, planes=None, snap_tol=0.5):
    """Contour -> axis-aligned edge list (orientation + offset) -> merge runs -> drop short edges by merging their
    neighbours (which share orientation) -> vertices from consecutive-edge intersections. Always even vertex count."""
    cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnt = max(cnts, key=cv2.contourArea); approx = cv2.approxPolyDP(cnt, eps_m / CELL, True)[:, 0, :].astype(float)
    P = approx * CELL + lo
    n = len(P); E = []  # (orientation, offset, weight)
    for k in range(n):
        a, b = P[k], P[(k + 1) % n]; dx, dz = b - a
        if abs(dx) >= abs(dz): E.append(["z", (a[1] + b[1]) / 2, abs(dx)])
        else: E.append(["x", (a[0] + b[0]) / 2, abs(dz)])
    def merge_runs(E):
        out = []
        for e in E:
            if out and out[-1][0] == e[0]:
                w = out[-1][2] + e[2]; out[-1] = [e[0], (out[-1][1] * out[-1][2] + e[1] * e[2]) / max(w, 1e-9), w]
            else: out.append(list(e))
        if len(out) > 1 and out[0][0] == out[-1][0]:
            w = out[0][2] + out[-1][2]; out[0] = [out[0][0], (out[0][1] * out[0][2] + out[-1][1] * out[-1][2]) / max(w, 1e-9), w]; out.pop()
        return out
    E = merge_runs(E)
    def vertices(E):
        V = []
        for k in range(len(E)):
            e1, e2 = E[k], E[(k + 1) % len(E)]
            V.append([e1[1] if e1[0] == "x" else e2[1], e1[1] if e1[0] == "z" else e2[1]])
        return np.array(V)
    while len(E) > 4:
        V = vertices(E); L = [np.linalg.norm(V[(k + 1) % len(V)] - V[k]) for k in range(len(V))]
        # edge k runs from V[k] to V[k+1]; E index: V[k] is intersection of E[k], E[k+1]; so edge between V[k] and V[k+1] is E[k+1]
        k = int(np.argmin(L))
        if L[k] >= min_edge_m: break
        ek = (k + 1) % len(E); E.pop(ek); E = merge_runs(E)
    if len(E) < 4 or len(E) % 2: return None
    # snap edges to Phase-1 fitted wall planes (real walls seen head-on) when close
    if planes:
        for e in E:
            axis = 0 if e[0] == "x" else 2
            cands = [pl["offset"] for pl in planes if pl["kind"] == "wall" and pl["axis"] == axis and abs(pl["offset"] - e[1]) < snap_tol]
            if cands: e[1] = min(cands, key=lambda o: abs(o - e[1]))
    return vertices(E)

def poly_area(V): x, z = V[:, 0], V[:, 1]; return 0.5 * abs(np.dot(x, np.roll(z, 1)) - np.dot(z, np.roll(x, 1)))

def edges_of(V):
    out = []
    for k in range(len(V)):
        a, b = V[k], V[(k + 1) % len(V)]
        axis = 0 if abs(a[0] - b[0]) < 1e-6 else 2   # x const -> plane axis 0
        out.append({"a": a.tolist(), "b": b.tolist(), "axis": axis, "offset": float(a[0] if axis == 0 else a[1]), "len": float(np.linalg.norm(b - a))})
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
        c = cams[i]; d3 = pts[i][idx[:, 0], idx[:, 1]] - c
        for k in np.unique(ids):
            sel = ids == k; e = edges[k]; a = e["axis"]; dn = d3[sel][:, a]
            t = (e["offset"] - c[a]) / np.where(np.abs(dn) < 1e-6, 1e-6, dn); okt = (t > 0.6) & (t < 1.4)
            ii = idx[sel][okt]; pts[i][ii[:, 0], ii[:, 1]] = c + t[okt, None] * d3[sel][okt]; edge_id[i][ii[:, 0], ii[:, 1]] = k; moved += int(okt.sum())
    room["edge_id"] = edge_id; return moved

def wall_textures(room, edges, res=0.04):
    """Splat snapped wall pixels into a per-edge texture (along x height). Unseen cells get the wall's median colour."""
    pts, rgb, eid = room["pts"], room["rgb"], room["edge_id"]; ceil_m = room["ceil_m"]; tex = []
    for k, e in enumerate(edges):
        a, b = np.array(e["a"]), np.array(e["b"]); L = e["len"]; nx, ny = max(2, int(L / res)), max(2, int(ceil_m / res))
        acc = np.zeros((ny, nx, 3), np.float64); cnt = np.zeros((ny, nx), np.float64)
        m = eid == k
        if m.any():
            q = pts[m]; col = rgb[m].astype(np.float64)
            t = ((q[:, [0, 2]] - a) @ (b - a)) / max(1e-9, L * L); u = np.clip((t * nx).astype(int), 0, nx - 1); v = np.clip(((1 - q[:, 1] / ceil_m) * ny).astype(int), 0, ny - 1)
            np.add.at(acc, (v, u), col); np.add.at(cnt, (v, u), 1)
        seen = cnt > 0; img = np.zeros((ny, nx, 3), np.uint8)
        if seen.any():
            img[seen] = (acc[seen] / cnt[seen][:, None]).astype(np.uint8); med = np.median(img[seen], 0).astype(np.uint8)
            img[~seen] = med
            # fill small holes with nearby colour
            img = cv2.inpaint(img, (~seen).astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA) if seen.mean() > 0.2 else img
        else: img[:] = 200
        tex.append({"img": img, "seen_frac": float(seen.mean())})
    return tex

def floor_texture(room, V, res=0.04):
    pts, rgb, labels = room["pts"], room["rgb"], room["labels"]; lo = V.min(0); hi = V.max(0)
    nx, nz = max(2, int((hi[0] - lo[0]) / res)), max(2, int((hi[1] - lo[1]) / res))
    acc = np.zeros((nz, nx, 3), np.float64); cnt = np.zeros((nz, nx), np.float64); m = labels == FLOOR
    q = pts[m]; col = rgb[m].astype(np.float64)
    u = np.clip(((q[:, 0] - lo[0]) / (hi[0] - lo[0]) * nx).astype(int), 0, nx - 1); v = np.clip(((q[:, 2] - lo[1]) / (hi[1] - lo[1]) * nz).astype(int), 0, nz - 1)
    np.add.at(acc, (v, u), col); np.add.at(cnt, (v, u), 1); seen = cnt > 0; img = np.zeros((nz, nx, 3), np.uint8)
    if seen.any(): img[seen] = (acc[seen] / cnt[seen][:, None]).astype(np.uint8); img[~seen] = np.median(img[seen], 0).astype(np.uint8)
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
                ex_ = pl["extent"]; a_ = pl["axis"]
                if a_ == 0: A, B = [pl["offset"], ex_["z"][0]], [pl["offset"], ex_["z"][1]]
                else: A, B = [ex_["x"][0], pl["offset"]], [ex_["x"][1], pl["offset"]]
                e = {"a": A, "b": B, "axis": a_, "offset": pl["offset"], "len": float(np.hypot(B[0] - A[0], B[1] - A[1]))}; k = -1
            # lift box corners by intersecting the pixel rays with the edge plane
            c = room["cams"][i]; K_right = np.array(room["cam_basis"][i]["right"]); K_up = np.array(room["cam_basis"][i]["up"]); K_fwd = np.array(room["cam_basis"][i]["fwd"])
            fx = W / (2 * np.tan(np.radians(room["cam_basis"][i]["fov_h"] / 2))); fy = H / (2 * np.tan(np.radians(room["cam_basis"][i]["fov_v"] / 2)))
            corners = []
            for (u, v) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                d = K_fwd + (u - W / 2) / fx * K_right - (v - H / 2) / fy * K_up; a = e["axis"]
                t = (e["offset"] - c[a]) / (d[a] if abs(d[a]) > 1e-6 else 1e-6)
                if t <= 0: break
                corners.append(c + t * d)
            if len(corners) < 4: continue
            C = np.array(corners); along = np.array(e["b"]) - np.array(e["a"]); along /= np.linalg.norm(along); along3 = np.array([along[0], 0, along[1]])
            s_along = (C - np.array([e["a"][0], 0, e["a"][1]])) @ along3
            width = float(s_along.max() - s_along.min()); bottom = float(C[:, 1].min()); top = float(C[:, 1].max())
            if width < 0.3 or width > 4 or top - bottom < 0.3: continue
            kind = ["window", "door"][int(l)]
            if kind == "door" and not (bottom < 0.35 and 1.6 < top - bottom < 2.6 and width < 1.6): continue
            if kind == "window" and (bottom > 1.8 or top - bottom < 0.4): continue
            center = np.array([e["a"][0], 0, e["a"][1]]) + along3 * float(s_along.mean()); center[1] = (top + bottom) / 2
            out.append({"kind": kind, "score": round(float(s), 2), "img": i, "edge": k, "box": [int(x0), int(y0), int(x1), int(y1)], "center": center.round(3).tolist(),
                        "normal": [1.0 if e["axis"] == 0 else 0.0, 0.0, 1.0 if e["axis"] == 2 else 0.0], "width_m": round(width, 2), "height_m": round(top - bottom, 2), "sill_m": round(bottom, 2), "s0": float(s_along.min()), "s1": float(s_along.max())})
    # dedupe per edge: merge boxes overlapping along the wall
    final = []
    for o in sorted(out, key=lambda o: -o["score"]):
        if any(f["edge"] == o["edge"] and f["kind"] == o["kind"] and min(f["s1"], o["s1"]) - max(f["s0"], o["s0"]) > 0.3 * min(f["width_m"], o["width_m"]) for f in final): continue
        final.append(o)
    # orient normals outward (away from polygon interior) later in export; here keep axis sign from edge midpoint vs polygon centroid
    return final
