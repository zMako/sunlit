"""Guided mode: the box comes from the photo (walls it sees, via the floor boundary) plus the VLM/plan dimensions for
the walls it does not see; the outpainting is steered by the box's depth (ControlNet) so generated walls land where the
box says. Camera at the origin, floor at y = 0, camera height cam_h."""
import sys, pathlib, numpy as np, cv2
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import equirect as E, blayout as LY

def box_from_photo(lab, known, cam_h, vlm_w, vlm_d, FLOOR, CEIL, WALL, min_cols=40):
    """lab: equirect labels of the placed photo (-1 outside). Returns layout dict with corners (camera at origin)."""
    fl, ce = LY.boundaries(np.where(known, lab, -1), FLOOR, CEIL, WALL)
    W = len(fl); lon = ((np.arange(W) + 0.5) / W * 2 - 1) * np.pi
    kcol = known.any(0)   # columns the photo covers
    ok = kcol & ~np.isnan(fl) & (fl < -0.03); meas = {}
    if ok.sum() >= min_cols:
        r = np.clip(cam_h / np.tan(-fl[ok]), 0.3, 15); pts = np.stack([r * np.sin(lon[ok]), r * np.cos(lon[ok])], 1)
        d = np.diff(pts, axis=0); L = np.hypot(d[:, 0], d[:, 1]); ang = np.arctan2(d[:, 1], d[:, 0]) % (np.pi / 2)
        hist, edges = np.histogram(ang, bins=90, range=(0, np.pi / 2), weights=L); th = (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]) / 2
        R = np.array([[np.cos(-th), -np.sin(-th)], [np.sin(-th), np.cos(-th)]]); q = pts @ R.T; ax_x = np.abs(q[:, 0]) >= np.abs(q[:, 1])
        for col, mask in ((0, ax_x), (1, ~ax_x)):
            for sgn in (1, -1):
                v = q[mask, col]; v = v[np.sign(v) == sgn]
                if len(v) >= min_cols // 2: meas[(col, sgn)] = float(np.median(v))
    else: th = 0.0; R = np.eye(2)
    dims = {0: vlm_w or 3.5, 1: vlm_d or 3.5}; lo = {}; hi = {}
    for col in (0, 1):
        D = float(np.clip(dims[col], 1.8, 9.0)); p, n = meas.get((col, 1)), meas.get((col, -1))
        if p is not None and n is not None: hi[col], lo[col] = p, n          # both walls seen: trust the photo
        elif p is not None: hi[col] = p; lo[col] = min(p - D, -0.5)
        elif n is not None: lo[col] = n; hi[col] = max(n + D, 0.5)
        else: hi[col], lo[col] = D * 0.5, -D * 0.5                           # nothing seen on this axis: camera centred
    cq = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]); corners = cq @ R
    okc = ok & ~np.isnan(ce) & (ce > 0.03)
    ceil = float(np.clip(np.median(cam_h + (cam_h / np.tan(-fl[okc])) * np.tan(ce[okc])), 2.2, 3.6)) if okc.sum() >= min_cols // 2 else 2.6
    return {"corners": corners.tolist(), "width_m": float(hi[0] - lo[0]), "depth_m": float(hi[1] - lo[1]), "ceiling_m": ceil, "cam_h": cam_h, "axis_deg": float(np.degrees(th)),
            "area_m2": float((hi[0] - lo[0]) * (hi[1] - lo[1])), "measured_sides": [f"{'xz'[c]}{'+' if s > 0 else '-'}" for (c, s) in meas], "n_boundary_cols": int(ok.sum())}

def depth_fn_for(lay):
    import pano as PANO
    V = np.array(lay["corners"], float); c = np.array([0.0, lay["cam_h"], 0.0]); ceil = lay["ceiling_m"]
    def fn(N, fov, R):
        d = E.view_rays(N, fov, R).reshape(-1, 3).astype(float); t, sid = PANO.shell_hit(c, d, V, ceil)
        t = np.where(np.isfinite(t), t, np.nanmax(t[np.isfinite(t)]) if np.isfinite(t).any() else 5.0)
        inv = 1.0 / np.clip(t, 0.3, 20); inv = (inv - inv.min()) / max(inv.max() - inv.min(), 1e-6)
        return (inv.reshape(N, N) * 255).astype(np.uint8)
    return fn
