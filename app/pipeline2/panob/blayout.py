"""Manhattan room layout from a panorama via semantic segmentation of perspective views (no extra weights): the
floor-wall boundary per column gives the wall distance from the camera height; a rectangle is fitted in the dominant
axes; the ceiling-wall boundary gives the ceiling height."""
import sys, pathlib, numpy as np, cv2
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent))
import equirect as E

def label_pano(pano, seg_fn, N=640, fov=100):
    """Equirect label map (H, W) from segmenting perspective views; -1 where no view covered. Each pixel takes the label
    from the view in which it is most central (least distortion)."""
    H, W = pano.shape[:2]; lab = np.full((H, W), -1, np.int16); best = np.full((H, W), 9.0, np.float32); D = E.dirs(W, H)
    f = (N / 2) / np.tan(np.radians(fov) / 2)
    for pitch in (-35, 0, 35):
        for yaw in range(0, 360, 60):
            R = E.rot(np.radians(yaw), np.radians(pitch)); rgb, _ = E.render_view(pano, np.ones((H, W), bool), N, fov, R)
            L = seg_fn(rgb).astype(np.float32)
            c = D @ R; z = c[..., 2]; ok = z > 1e-3
            u = np.where(ok, f * c[..., 0] / np.where(ok, z, 1) + N / 2 - 0.5, -1); v = np.where(ok, -f * c[..., 1] / np.where(ok, z, 1) + N / 2 - 0.5, -1)
            m = ok & (u >= 0) & (u <= N - 1) & (v >= 0) & (v <= N - 1)
            s = cv2.remap(L, u.astype(np.float32), v.astype(np.float32), cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=-1)
            cen = np.maximum(np.abs(u - N / 2), np.abs(v - N / 2)) / (N / 2)
            take = m & (cen < best); lab[take] = s[take]; best[take] = cen[take]
    return lab

def boundaries(lab, FLOOR, CEIL, WALL):
    """Per column: latitude (rad, negative) of the floor-wall boundary and latitude of the ceiling-wall boundary."""
    H, W = lab.shape; lat = (0.5 - (np.arange(H) + 0.5) / H) * np.pi; fl = np.full(W, np.nan); ce = np.full(W, np.nan)
    half = H // 2
    for i in range(W):
        col = lab[:, i]
        below = col[half:]; floor_rows = np.where(below == FLOOR)[0]
        if len(floor_rows) > 5:
            # first row from the horizon where floor begins a run of >= 5 pixels
            runs = np.split(floor_rows, np.where(np.diff(floor_rows) > 1)[0] + 1); runs = [r for r in runs if len(r) >= 5]
            if runs: fl[i] = lat[half + runs[0][0]]
        above = col[:half][::-1]; ceil_rows = np.where(above == CEIL)[0]
        if len(ceil_rows) > 5:
            runs = np.split(ceil_rows, np.where(np.diff(ceil_rows) > 1)[0] + 1); runs = [r for r in runs if len(r) >= 5]
            if runs: ce[i] = lat[half - 1 - runs[0][0]]
    def fill(a):
        idx = np.arange(len(a)); ok = ~np.isnan(a)
        if ok.sum() < 10: return a
        a2 = a.copy(); a2[~ok] = np.interp(idx[~ok], np.concatenate([idx[ok] - len(a), idx[ok], idx[ok] + len(a)]), np.concatenate([a[ok]] * 3)); return a2
    return fill(fl), fill(ce)

def rectangle(fl_lat, ce_lat, cam_h=1.5):
    """Floor boundary -> wall distances -> dominant axes -> rectangle (4 corners, metres, camera at origin). Returns dict."""
    W = len(fl_lat); lon = ((np.arange(W) + 0.5) / W * 2 - 1) * np.pi
    ok = ~np.isnan(fl_lat) & (fl_lat < -0.03); r = cam_h / np.tan(-fl_lat[ok]); r = np.clip(r, 0.3, 15)
    x, z = r * np.sin(lon[ok]), r * np.cos(lon[ok]); pts = np.stack([x, z], 1)
    # dominant orientation: angles of consecutive boundary segments, mod 90 deg
    d = np.diff(pts, axis=0); ang = np.arctan2(d[:, 1], d[:, 0]) % (np.pi / 2); L = np.hypot(d[:, 0], d[:, 1])
    hist, edges = np.histogram(ang, bins=90, range=(0, np.pi / 2), weights=L); th = (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]) / 2
    R = np.array([[np.cos(-th), -np.sin(-th)], [np.sin(-th), np.cos(-th)]]); q = pts @ R.T
    # each wall's position = median distance of the boundary points facing it (robust to doorways and rooms seen beyond them)
    ax_x = np.abs(q[:, 0]) >= np.abs(q[:, 1])
    def side(mask, col, sgn):
        v = q[mask, col]; v = v[np.sign(v) == sgn]
        return float(np.median(v)) if len(v) >= 8 else sgn * 2.0
    hi = np.array([side(ax_x, 0, 1), side(~ax_x, 1, 1)]); lo = np.array([side(ax_x, 0, -1), side(~ax_x, 1, -1)])
    corners_q = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]); corners = corners_q @ R
    # ceiling height: for each column, wall distance r and ceiling latitude -> h = cam_h + r tan(lat)
    okc = ~np.isnan(ce_lat) & ok & (ce_lat > 0.03); hc = cam_h + (cam_h / np.tan(-fl_lat[okc])) * np.tan(ce_lat[okc]) if okc.sum() > 10 else np.array([2.6])
    ceil = float(np.clip(np.median(hc), 2.2, 3.6))
    return {"corners": corners.tolist(), "width_m": float(hi[0] - lo[0]), "depth_m": float(hi[1] - lo[1]), "ceiling_m": ceil, "cam_h": cam_h, "axis_deg": float(np.degrees(th)),
            "area_m2": float((hi[0] - lo[0]) * (hi[1] - lo[1])), "n_boundary": int(ok.sum())}

def overlay(pano, fl_lat, ce_lat):
    H, W = pano.shape[:2]; out = pano.copy()
    for i in range(W):
        for a, col in ((fl_lat[i], (255, 80, 40)), (ce_lat[i], (40, 160, 255))):
            if not np.isnan(a):
                j = int(round((0.5 - a / np.pi) * H - 0.5)); cv2.circle(out, (i, j), 2, col, -1)
    return out
