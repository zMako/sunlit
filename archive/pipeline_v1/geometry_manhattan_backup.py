"""Clean room geometry: gravity frame, bilateral-smoothed depth, normals, floor/ceiling/wall labels,
Manhattan alignment, wall-plane fitting, and ray-snapping of points onto their planes (texture stays aligned)."""
import numpy as np, cv2

OTHER, FLOOR, CEIL, WALL = 0, 1, 2, 3

def gravity_frame(extr):
    down = extr[:, 1, :3]; down = down / np.linalg.norm(down, axis=1, keepdims=True); g = down.mean(0); g /= np.linalg.norm(g); up = -g
    ex = np.cross(up, extr[0, 2, :3]); ex /= np.linalg.norm(ex); ez = np.cross(ex, up)
    return np.stack([ex, up, ez])  # rows: room axes in world coords; room = R @ world

def smoothed_points(P, i):
    """Bilateral-filter camera depth and re-unproject -> world points (H,W,3), kills quantization stripes."""
    wp, extr, intr = P["world_points"][i], P["extrinsic"][i], P["intrinsic"][i]; H, W = wp.shape[:2]
    cam = (extr[:3, :3] @ wp.reshape(-1, 3).T).T + extr[:3, 3]; z = cam[:, 2].reshape(H, W).astype(np.float32)
    zs = cv2.bilateralFilter(z, 9, 0.06 * float(np.median(z)), 7)
    vs, us = np.mgrid[0:H, 0:W]; x = (us - intr[0, 2]) / intr[0, 0] * zs; y = (vs - intr[1, 2]) / intr[1, 1] * zs
    camp = np.stack([x, y, zs], -1).reshape(-1, 3)
    return (extr[:3, :3].T @ (camp - extr[:3, 3]).T).T.reshape(H, W, 3), zs

def normals(pts, cam):
    """Normals from central differences of a point map; oriented toward the camera."""
    dx = np.zeros_like(pts); dy = np.zeros_like(pts)
    dx[:, 1:-1] = pts[:, 2:] - pts[:, :-2]; dy[1:-1] = pts[2:] - pts[:-2]
    n = np.cross(dx, dy); n /= (np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9)
    flip = np.einsum("hwc,hwc->hw", n, cam - pts) < 0; n[flip] *= -1
    return n

def robust_level(h, lo_q, hi_q):
    """Robust plane height: median of the values between two quantiles, trimmed twice."""
    v = h[(h > np.quantile(h, lo_q)) & (h < np.quantile(h, hi_q))]
    for _ in range(2):
        m = np.median(v); v = v[np.abs(v - m) < 0.08 * max(1e-6, np.std(h))]
        if len(v) < 50: break
    return float(np.median(v)) if len(v) else float(np.median(h))

def clean_room(P, ceil_m=2.6, conf_q=0.3):
    S, H, W = P["conf"].shape; R = gravity_frame(P["extrinsic"])
    cams = (R @ P["cam_centers"].T).T
    pts = np.zeros((S, H, W, 3), np.float32); nrm = np.zeros((S, H, W, 3), np.float32); good = np.zeros((S, H, W), bool)
    for i in range(S):
        w, _ = smoothed_points(P, i); pts[i] = (R @ w.reshape(-1, 3).T).T.reshape(H, W, 3); nrm[i] = normals(pts[i], cams[i])
        good[i] = P["conf"][i] > np.quantile(P["conf"][i], conf_q)
    up_dot = nrm[..., 1]
    # floor & ceiling levels from up/down-facing surfaces
    h = pts[..., 1]
    fl_cand = good & (up_dot > 0.85); ce_cand = good & (up_dot < -0.85)
    floor_h = robust_level(h[fl_cand], 0.02, 0.6) if fl_cand.sum() > 500 else np.quantile(h[good], 0.03)
    ceil_h = robust_level(h[ce_cand], 0.4, 0.98) if ce_cand.sum() > 500 else np.quantile(h[good], 0.97)
    scale = ceil_m / (ceil_h - floor_h)
    pts[..., 1] -= floor_h; pts *= scale; cams[:, 1] -= floor_h; cams *= scale; ceil_h_m = (ceil_h - floor_h) * scale
    # Manhattan: dominant wall azimuth mod 90
    wall_cand = good & (np.abs(up_dot) < 0.35)
    az = np.degrees(np.arctan2(nrm[..., 2][wall_cand], nrm[..., 0][wall_cand])) % 90
    hist, edges = np.histogram(az, bins=90, range=(0, 90)); theta = (edges[np.argmax(hist)] + 0.5)
    c, s_ = np.cos(np.radians(-theta)), np.sin(np.radians(-theta))
    Rm = np.array([[c, 0, -s_], [0, 1, 0], [s_, 0, c]])
    pts = pts @ Rm.T; nrm = nrm @ Rm.T; cams = cams @ Rm.T; R = Rm @ R
    # labels
    labels = np.full((S, H, W), OTHER, np.uint8)
    labels[good & (up_dot > 0.85) & (np.abs(pts[..., 1]) < 0.25)] = FLOOR
    labels[good & (up_dot < -0.85) & (np.abs(pts[..., 1] - ceil_h_m) < 0.3)] = CEIL
    labels[good & (np.abs(up_dot) < 0.35)] = WALL
    # wall planes: axis-aligned, offsets by histogram peaks per axis
    planes = [{"kind": "floor", "axis": 1, "offset": 0.0}, {"kind": "ceiling", "axis": 1, "offset": float(ceil_h_m)}]
    plane_id = np.full((S, H, W), -1, np.int16); plane_id[labels == FLOOR] = 0; plane_id[labels == CEIL] = 1
    for axis in (0, 2):
        sel = (labels == WALL) & (np.abs(nrm[..., axis]) > 0.9)
        if sel.sum() < 500: continue
        off = pts[..., axis][sel]; lo, hi = np.quantile(off, 0.01), np.quantile(off, 0.99)
        bins = max(10, int((hi - lo) / 0.05)); hist, edges = np.histogram(off, bins=bins, range=(lo, hi))
        hist_s = np.convolve(hist, [0.25, 0.5, 0.25], "same"); min_support = max(1500, 0.03 * sel.sum())
        peaks = [k for k in range(len(hist_s)) if hist_s[k] >= min_support and hist_s[k] == hist_s[max(0, k - 6):k + 7].max()]
        for k in peaks:
            o = float((edges[k] + edges[k + 1]) / 2)
            planes.append({"kind": "wall", "axis": axis, "offset": o})
        # assign wall pixels to nearest plane within 0.15 m
        wall_offs = np.array([p["offset"] for p in planes if p["kind"] == "wall" and p["axis"] == axis]); wall_ids = np.array([k for k, p in enumerate(planes) if p["kind"] == "wall" and p["axis"] == axis])
        if len(wall_offs):
            d = np.abs(off[:, None] - wall_offs[None, :]); j = d.argmin(1); okd = d[np.arange(len(j)), j] < 0.15
            ids = np.where(okd, wall_ids[j], -1); plane_id[sel] = ids
    # ray-snap: move labelled points along their camera ray onto the plane
    resid_before, resid_after = [], []
    for i in range(S):
        c = cams[i]; d = pts[i] - c
        for k, pl in enumerate(planes):
            m = plane_id[i] == k
            if not m.any(): continue
            a = pl["axis"]; dn = d[..., a][m]; t = (pl["offset"] - c[a]) / np.where(np.abs(dn) < 1e-6, 1e-6, dn)
            okt = (t > 0.7) & (t < 1.3); resid_before.append(np.abs(pts[i][..., a][m] - pl["offset"]))
            idx = np.argwhere(m); sel_idx = idx[okt]
            pts[i][sel_idx[:, 0], sel_idx[:, 1]] = c + t[okt, None] * d[sel_idx[:, 0], sel_idx[:, 1]]
            resid_after.append(np.abs(pts[i][..., a][m] - pl["offset"]))
    # plane extents for drawing
    for k, pl in enumerate(planes):
        m = plane_id == k
        if m.sum() < 10: pl["extent"] = None; continue
        q = pts[m]; pl["extent"] = {"x": [float(np.quantile(q[..., 0], 0.02)), float(np.quantile(q[..., 0], 0.98))],
                                   "z": [float(np.quantile(q[..., 2], 0.02)), float(np.quantile(q[..., 2], 0.98))], "n_px": int(m.sum())}
    stats = {"floor_h_units": float(floor_h), "ceil_h_m": float(ceil_h_m), "scale_units_per_m": float(1 / scale), "manhattan_deg": float(theta),
             "cam_heights_m": cams[:, 1].round(3).tolist(), "label_frac": {n: float((labels == v).mean()) for n, v in (("floor", FLOOR), ("ceil", CEIL), ("wall", WALL), ("other", OTHER))},
             "n_wall_planes": sum(p["kind"] == "wall" for p in planes),
             "wall_resid_m_before": float(np.median(np.concatenate(resid_before))) if resid_before else None,
             "wall_resid_m_after": float(np.median(np.concatenate(resid_after))) if resid_after else None}
    # camera basis in room frame (for exact photo views)
    cam_basis = []
    for i in range(S):
        Rc = P["extrinsic"][i, :3, :3]; right, down, fwd = (R @ Rc[0]), (R @ Rc[1]), (R @ Rc[2])
        K = P["intrinsic"][i]; cam_basis.append({"pos": cams[i].round(4).tolist(), "right": right.round(4).tolist(), "up": (-down).round(4).tolist(), "fwd": fwd.round(4).tolist(),
                                                 "fov_v": float(2 * np.degrees(np.arctan(H / (2 * K[1, 1])))), "fov_h": float(2 * np.degrees(np.arctan(W / (2 * K[0, 0]))))})
    return {"pts": pts, "normals": nrm, "labels": labels, "plane_id": plane_id, "planes": planes, "cams": cams, "cam_basis": cam_basis,
            "good": good, "rgb": P["rgb"], "conf": P["conf"], "stats": stats, "R": R, "ceil_m": float(ceil_h_m)}
