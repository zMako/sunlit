"""Single-photo wall faces: letterbox crop, floor/ceiling boundary lines, corner split, vanishing points, metric positions
along partially seen walls (single-view metrology with the camera intrinsics), and the image->wall homographies."""
import numpy as np, cv2

def letterbox(img, thr=12):
    """Columns/rows at the borders that are flat colour (padding bars) -> crop box (x0, y0, x1, y1)."""
    g = img.astype(np.int16); H, W = g.shape[:2]
    col_std = g.reshape(H, W, -1).std(axis=(0, 2)); row_std = g.reshape(H, W, -1).std(axis=(1, 2))
    x0 = 0
    while x0 < W // 3 and col_std[x0] < thr: x0 += 1
    x1 = W
    while x1 > 2 * W // 3 and col_std[x1 - 1] < thr: x1 -= 1
    y0 = 0
    while y0 < H // 3 and row_std[y0] < thr: y0 += 1
    y1 = H
    while y1 > 2 * H // 3 and row_std[y1 - 1] < thr: y1 -= 1
    return x0, y0, x1, y1

def boundary(mask_a, mask_b, from_top=True, min_frac=0.02):
    """Per column: the y where region a meets region b. For the floor line: a = wall-ish above, b = floor below -> topmost
    floor pixel that has wall-ish pixels above it. For the ceiling line: lowest ceiling pixel with wall-ish below. NaN where absent."""
    H, W = mask_a.shape; ys = np.full(W, np.nan)
    for x in range(W):
        col_b = np.where(mask_b[:, x])[0]
        if len(col_b) < min_frac * H: continue
        if from_top:   # floor: first floor pixel below the wall-ish band
            y = col_b.min()
            above = mask_a[max(0, y - 25):y, x]
            if above.mean() > 0.3: ys[x] = y
        else:          # ceiling: last ceiling pixel above the wall-ish band
            y = col_b.max()
            below = mask_a[y + 1:y + 26, x]
            if below.size and below.mean() > 0.3: ys[x] = y
    # median filter to kill speckle
    v = ~np.isnan(ys)
    if v.sum() > 30:
        ysf = ys.copy(); idx = np.where(v)[0]; vals = ys[idx]
        k = 9; pad = np.pad(vals, (k // 2, k // 2), mode="edge")
        med = np.array([np.median(pad[i:i + k]) for i in range(len(vals))]); ysf[idx] = med; ys = ysf
    return ys

def fit_line(xs, ys):
    A = np.stack([xs, np.ones_like(xs)], 1); m, c = np.linalg.lstsq(A, ys, rcond=None)[0]; return m, c

def piecewise(xs, ys, max_seg=3, min_len=60, min_angle_deg=4.0):
    """Split a polyline y(x) into 1..max_seg straight segments minimising residual; return list of (x_start, x_end, m, c)."""
    order = np.argsort(xs); xs, ys = xs[order], ys[order]; n = len(xs)
    if n < 2 * min_len: m, c = fit_line(xs, ys); return [(xs[0], xs[-1], m, c)]
    best = None
    def seg_err(i, j):
        m, c = fit_line(xs[i:j], ys[i:j]); r = ys[i:j] - (m * xs[i:j] + c); return float((r ** 2).sum()), m, c
    # 1 segment
    e1, m, c = seg_err(0, n); best = (e1 + 0.0, [(xs[0], xs[-1], m, c)])
    cand = list(range(min_len, n - min_len, max(1, n // 80)))
    for i in cand:   # 2 segments
        ea, ma, ca = seg_err(0, i); eb, mb, cb = seg_err(i, n); e = ea + eb
        if e + 0.15 * e1 < best[0]: best = (e, [(xs[0], xs[i], ma, ca), (xs[i], xs[-1], mb, cb)])
    if max_seg >= 3:
        for i in cand:
            for j in cand:
                if j < i + min_len: continue
                ea, ma, ca = seg_err(0, i); eb, mb, cb = seg_err(i, j); ec, mc, cc = seg_err(j, n); e = ea + eb + ec
                if e + 0.25 * e1 < best[0]: best = (e, [(xs[0], xs[i], ma, ca), (xs[i], xs[j], mb, cb), (xs[j], xs[-1], mc, cc)])
    segs = best[1]
    # merge neighbours whose slopes differ by less than min_angle
    out = [segs[0]]
    for s in segs[1:]:
        a0 = np.degrees(np.arctan(out[-1][2])); a1 = np.degrees(np.arctan(s[2]))
        if abs(a0 - a1) < min_angle_deg:
            x0, x1 = out[-1][0], s[1]; sel = (xs >= x0) & (xs <= x1); m, c = fit_line(xs[sel], ys[sel]); out[-1] = (x0, x1, m, c)
        else: out.append(s)
    return out

def intersect(l1, l2):
    """lines as (m, c) y = m x + c -> intersection point or None if parallel."""
    (m1, c1), (m2, c2) = l1, l2
    if abs(m1 - m2) < 1e-6: return None
    x = (c2 - c1) / (m1 - m2); return np.array([x, m1 * x + c1])

def faces_from_masks(lab, WALLISH, FLOOR, CEIL, crop):
    """Returns faces: list of dicts with x0, x1 (image x in cropped coords), floor line (m,c), ceiling line (m,c), partial flags."""
    x0c, y0c, x1c, y1c = crop; L = lab[y0c:y1c, x0c:x1c]
    wall = np.isin(L, WALLISH); floor = L == FLOOR; ceil = L == CEIL
    yf = boundary(wall, floor, True); yc = boundary(wall, ceil, False)
    xs = np.arange(L.shape[1]); vf = ~np.isnan(yf); vc = ~np.isnan(yc)
    if vf.sum() < 40: return [], yf, yc
    fsegs = piecewise(xs[vf].astype(float), yf[vf])
    csegs = piecewise(xs[vc].astype(float), yc[vc]) if vc.sum() >= 40 else []
    # corners from the floor polyline; snap ceiling breakpoints to them when close
    faces = []
    W = L.shape[1]
    for k, (xa, xb, m, c) in enumerate(fsegs):
        f = {"x0": float(xa), "x1": float(xb), "floor": (float(m), float(c)), "ceil": None, "partial_left": k == 0 and xa < 0.03 * W + 2, "partial_right": k == len(fsegs) - 1 and xb > 0.97 * W - 2}
        # ceiling line for this x range: the ceiling segment with the most overlap
        best = None
        for (ca, cb, cm, cc) in csegs:
            ov = min(xb, cb) - max(xa, ca)
            if ov > 0 and (best is None or ov > best[0]): best = (ov, cm, cc)
        if best: f["ceil"] = (float(best[1]), float(best[2]))
        faces.append(f)
    # refine shared corner x: average floor breakpoint with the nearest ceiling breakpoint
    for k in range(len(faces) - 1):
        xc = faces[k]["x1"]
        cands = [cb for (ca, cb, cm, cc) in csegs[:-1]] if len(csegs) > 1 else []
        near = [c_ for c_ in cands if abs(c_ - xc) < 0.06 * W]
        if near: xc = 0.5 * (xc + min(near, key=lambda c_: abs(c_ - xc)))
        faces[k]["x1"] = xc; faces[k + 1]["x0"] = xc
    return faces, yf, yc

def quad(face, default_ceil_y=0.0):
    """Image quad (tl, tr, br, bl) in cropped pixel coords from the face's lines and x range."""
    x0, x1 = face["x0"], face["x1"]; mf, cf = face["floor"]
    if face["ceil"]: mc, cc = face["ceil"]; yt0, yt1 = mc * x0 + cc, mc * x1 + cc
    else: yt0 = yt1 = default_ceil_y
    return np.array([[x0, yt0], [x1, yt1], [x1, mf * x1 + cf], [x0, mf * x0 + cf]], float)

def metric_positions(faces, K, far_idx, far_width_m):
    """Single-view metrology. The far wall (index far_idx) has known width -> fixes scale. For each side face, the metric
    length seen between the shared corner and its outer edge, measured along the floor line, using the camera matrix K
    (3x3, cropped-image pixels). Returns dict face_idx -> seen_len_m (None for the far wall)."""
    Kinv = np.linalg.inv(K)
    def ray(p): v = Kinv @ np.array([p[0], p[1], 1.0]); return v / np.linalg.norm(v)
    far = faces[far_idx]; qf = quad(far)
    p0, p1 = qf[3], qf[2]    # far wall floor corners: left, right (image)
    # direction of the far wall in camera coords from its vanishing point (floor & ceiling line intersection), else from the floor line direction
    vp = intersect(far["floor"], far["ceil"]) if far["ceil"] else None
    if vp is not None and np.all(np.isfinite(vp)) and abs(vp[0]) < 1e5: d_far = ray(vp)
    else: d_far = Kinv @ np.array([1.0, far["floor"][0], 0.0]); d_far = d_far / np.linalg.norm(d_far)
    r0, r1 = ray(p0), ray(p1)
    # X0 = a r0, X1 = b r1, X1 - X0 = far_width * (+-d_far): solve least squares for a, b with sign making a,b > 0
    best = None
    for sgn in (1, -1):
        A = np.stack([-r0, r1], 1); rhs = sgn * far_width_m * d_far
        sol, res, _, _ = np.linalg.lstsq(A, rhs, rcond=None); a, b = sol
        err = np.linalg.norm(A @ sol - rhs)
        if a > 0 and b > 0 and (best is None or err < best[0]): best = (err, a, b)
    if best is None: return {}, None
    _, a, b = best; X0, X1 = a * r0, b * r1; out = {far_idx: None}
    for k, f in enumerate(faces):
        if k == far_idx: continue
        q = quad(f); corner_X = X0 if k < far_idx else X1   # faces left of the far wall share its left corner
        pe = q[3] if k > far_idx else q[2]                   # outer floor point: for a right-side face its right-bottom; left-side face its left-bottom
        if k > far_idx: pe = q[2]
        else: pe = q[3]
        vp = intersect(f["floor"], f["ceil"]) if f["ceil"] else None
        if vp is not None and np.all(np.isfinite(vp)) and abs(vp[0]) < 1e5: d = ray(vp)
        else: d = Kinv @ np.array([1.0, f["floor"][0], 0.0]); d = d / np.linalg.norm(d)
        re_ = ray(pe)
        # Xe = c re, Xe - corner_X = t d  -> solve [re, -d] [c, t]^T = corner_X
        A = np.stack([re_, -d], 1); sol = np.linalg.lstsq(A, corner_X, rcond=None)[0]; c, t = sol
        out[k] = abs(float(t))
    return out, (X0, X1)

def homography(quad_img, wall_rect):
    """quad_img: tl,tr,br,bl pixels; wall_rect: (u0, u1, v_top, v_bottom) in metres along the wall (u from the wall's inside-left end)
    and height (v from the floor). Returns H mapping image -> (u, v) metres."""
    u0, u1, vt, vb = wall_rect
    dst = np.array([[u0, vt], [u1, vt], [u1, vb], [u0, vb]], np.float32)
    return cv2.getPerspectiveTransform(quad_img.astype(np.float32), dst)


def metric_from_corner(faces, K, far_idx, H):
    """Scale from the shared corner's floor-to-ceiling vertical (known height H), for photos where no wall is seen whole.
    Returns per-face seen length along the floor line measured from the shared corner (far wall: from the corner toward its
    frame-cut edge; side faces: from the corner to their outer edge). Camera assumed roughly level (vertical lines vertical)."""
    Kinv = np.linalg.inv(K)
    def ray(p): v = Kinv @ np.array([p[0], p[1], 1.0]); return v / np.linalg.norm(v)
    def wall_dir(f):
        vp = intersect(f["floor"], f["ceil"]) if f["ceil"] else None
        if vp is not None and np.all(np.isfinite(vp)) and abs(vp[0]) < 1e5: return ray(vp)
        d = Kinv @ np.array([1.0, f["floor"][0], 0.0]); return d / np.linalg.norm(d)
    far = faces[far_idx]; qf = quad(far); out = {}
    # pick a corner that is actually a corner (not a frame edge): prefer the far wall's right corner if a face follows, else its left
    if far_idx + 1 < len(faces): corner_floor, corner_ceil, side = qf[2], qf[1], "right"
    elif far_idx > 0: corner_floor, corner_ceil, side = qf[3], qf[0], "left"
    else: return out, None
    rf, rc = ray(corner_floor), ray(corner_ceil); up = np.array([0.0, -1.0, 0.0])
    A = np.stack([-rf, rc], 1); sol = np.linalg.lstsq(A, H * up, rcond=None)[0]; a, c = sol
    if a <= 0 or c <= 0: return out, None
    Xc = a * rf   # corner on the floor, metric
    for k, f in enumerate(faces):
        q = quad(f); d = wall_dir(f)
        if k == far_idx: pe = q[3] if side == "right" else q[2]       # far wall: the end away from the corner
        elif k > far_idx: pe = q[2]                                   # right-side faces: their outer (right) end
        else: pe = q[3]                                               # left-side faces: their outer (left) end
        re_ = ray(pe); A = np.stack([re_, -d], 1); sol = np.linalg.lstsq(A, Xc, rcond=None)[0]; out[k] = abs(float(sol[1]))
    return out, side
