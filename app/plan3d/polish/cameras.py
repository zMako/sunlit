"""Camera for each (listing photo, plan room) pair from single-view metrology, then placed in the plan room.
Photo side (geom.faces_from_masks on the NN.seg.npz labels, VGGT hfov from work/intrinsics.json):
  pitch  : 1-D search (roll assumed 0) for the tilt at which the floor and ceiling boundary lines of each wall face are
           parallel in the rectified top view and adjacent faces meet at 90 deg (the horizon / vanishing-point condition);
  height : the far wall's floor line (unit camera height) and ceiling line (unit height above the camera) must be the same
           vertical plane -> h = H d_c / (d_f + d_c), H = the photo's ceiling height (photo_facts);
  yaw    : angle between the optical axis and the far wall's normal in the rectified top view;
  offset : camera position relative to the far wall's corner (metres along the wall, distance from it).
Plan side: far wall = the given side (N/E/S/W) of the room's bounding box, corner = its end on the side where the photo
shows the adjacent wall; camera = corner + offset, clamped inside the room (0.35 m margin), eye height = measured h if
1.2..1.7 m else 1.5 m. Writes polish/cameras.json [{unit, room, photo, pos, yaw, pitch, fov, ...diagnostics}].
yaw: degrees, three.js walk convention (0 looks +z = south, 90 looks +x = east, 180 north); pitch: degrees, + looks up;
fov: HORIZONTAL degrees of the photo crop; aspect = crop w/h."""
import sys, json, math, pathlib, numpy as np
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[2]
for p in ("app/pipeline2", "app/pipeline2/wallwrap"): sys.path.insert(0, str(ROOT / p))
sys.path.insert(0, str(HERE))
import geom
from common import pad_crop, LIST
WALLISH = [3, 4, 5, 6, 7]; FLOOR, CEIL = 1, 2
PAIRS = [  # (listing, photo, unit, room, far wall side of the plan room)
    ("gs-22612", "03", "gs-22612_plan_03", "r0", "N"),
    ("gs-22612", "04", "gs-22612_plan_03", "r2", "N"),
    ("gs-22612", "05", "gs-22612_plan_03", "r2", "W"),
    ("gs-20665", "11", "gs-20665_plan_00", "r1", "N"),
    ("gs-20665", "13", "gs-20665_plan_00", "r1", "N"),
    ("gs-20665", "17", "gs-20665_plan_00", "r0", "S"),
    # ("gs-20665", "18", "gs-20665_plan_00", "r0", "W"),  dropped: the plan room's west window is out of any matching view
]
INTR = json.load(open(HERE / "work/intrinsics.json"))
# Face x-ranges (fractions of the cropped photo width) marked by hand where geom's automatic corner split is wrong (open doors,
# pillars, chimney breasts and glass confuse the piecewise floor-line fit); the floor/ceiling lines are still fitted to
# geom.boundary() of the segmentation within each range. (ranges, index of the far face)
FACES = {
    "gs-22612/03": ([(0.02, 0.43), (0.55, 0.80)], 1),
    "gs-22612/04": ([(0.16, 0.62), (0.68, 0.99)], 0),
    "gs-22612/05": ([(0.04, 0.64), (0.69, 0.99)], 0),
    "gs-20665/11": ([(0.01, 0.14), (0.165, 0.40), (0.42, 0.48)], 1),
    "gs-20665/13": ([(0.03, 0.19), (0.21, 0.50)], 1),
    "gs-20665/17": ([(0.21, 0.60), (0.74, 0.99)], 0),
    "gs-20665/18": ([(0.25, 0.56), (0.60, 0.99)], 1),
}
def robust_line(xs, ys, it=4):
    ok = np.isfinite(ys); xs, ys = xs[ok], ys[ok]
    if len(xs) < 10: return None
    keep = np.ones(len(xs), bool)
    for _ in range(it):
        m, c = geom.fit_line(xs[keep], ys[keep]); r = np.abs(ys - (m * xs + c)); thr = max(2.0, np.percentile(r[keep], 70) * 1.5); keep = r < thr
        if keep.sum() < 10: break
    return float(m), float(c)

def level(rays, p):
    """camera rays (N,3: x right, y down, z fwd) -> level frame (X right, U up, Z fwd) for a camera pitched up by p rad."""
    cx, cy, cz = rays[:, 0], rays[:, 1], rays[:, 2]
    return np.stack([cx, -cy * math.cos(p) + cz * math.sin(p), cz * math.cos(p) + cy * math.sin(p)], 1)

def top(rays_l, sign):
    """level rays -> top-view points (X, Z) on the plane 1 unit below (sign=-1, floor) or above (sign=+1, ceiling)."""
    U = rays_l[:, 1] * sign; ok = U > 1e-4; s = 1.0 / U[ok]; return np.stack([rays_l[ok, 0] * s, rays_l[ok, 2] * s], 1)

def fit2(P):
    """2-D total-least-squares line -> (point on line, unit direction)."""
    c = P.mean(0); u, s, vt = np.linalg.svd(P - c); return c, vt[0]

def dist_origin(c, d):
    n = np.array([-d[1], d[0]]); return abs(float(c @ n))

def line_pts(face, key, n=40):
    m, c = face[key]; xs = np.linspace(face["x0"] + 2, face["x1"] - 2, n); return np.stack([xs, m * xs + c], 1)

def estimate(lid, n, H):
    info = INTR[f"{lid}/{n}"]; w, h = info["size"]; img = np.asarray(Image.open(LIST / f"{lid}/{n}.jpg").convert("RGB"))
    lab = np.load(LIST / f"{lid}/{n}.seg.npz")["labels"].astype(np.uint8)
    if lab.shape != img.shape[:2]: lab = np.asarray(Image.fromarray(lab).resize((img.shape[1], img.shape[0]), Image.NEAREST))
    crop = tuple(info["crop"]); faces, yf, yc = geom.faces_from_masks(lab, WALLISH, FLOOR, CEIL, crop); manual = FACES.get(f"{lid}/{n}")
    if manual:
        xs = np.arange(w, dtype=float); faces = []
        for (a, b) in manual[0]:
            sel = (xs >= a * w) & (xs <= b * w); fl = robust_line(xs[sel], yf[sel]); cl = robust_line(xs[sel], yc[sel])
            faces.append({"x0": a * w, "x1": b * w, "floor": fl, "ceil": cl})
    f = (w / 2) / math.tan(math.radians(info["hfov_deg"]) / 2); Kinv = np.linalg.inv(np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]]))
    def rays(px): return (Kinv @ np.c_[px, np.ones(len(px))].T).T
    if manual: far = manual[1]
    else:
      faces = [fc for fc in faces if fc["x1"] - fc["x0"] > 0.06 * w]
      far = int(np.argmax([(fc["x1"] - fc["x0"]) * (1.0 / (1 + 4 * abs(math.atan(fc["floor"][0])))) for fc in faces]))
    def cost(p):
        e = 0.0; dirs = []
        for k, fc in enumerate(faces):
            if not fc["floor"]: continue
            Pf = top(level(rays(line_pts(fc, "floor")), p), -1)
            if len(Pf) < 5: return 1e9
            _, df = fit2(Pf); dirs.append(df)
            if fc["ceil"]:
                Pc = top(level(rays(line_pts(fc, "ceil")), p), +1)
                if len(Pc) >= 5: _, dc = fit2(Pc); e += (1 - abs(df @ dc)) * 4
        for a, b in zip(dirs, dirs[1:]): e += abs(a @ b) ** 2   # adjacent faces perpendicular
        return e
    ps = np.radians(np.arange(-20, 20.01, 0.1)); cs = [cost(p) for p in ps]; p = float(ps[int(np.argmin(cs))])
    F = faces[far]; Pf = top(level(rays(line_pts(F, "floor")), p), -1); cf, df = fit2(Pf); d_f = dist_origin(cf, df)
    hcam, hsrc = None, "default 1.5"
    for fc in [F] + [x for x in faces if x is not F]:
        if not fc["ceil"] or not fc["floor"]: continue
        Pa = top(level(rays(line_pts(fc, "floor")), p), -1); Pb = top(level(rays(line_pts(fc, "ceil")), p), +1)
        if len(Pa) < 5 or len(Pb) < 5: continue
        a, da = fit2(Pa); b, db = fit2(Pb); df_, dc_ = dist_origin(a, da), dist_origin(b, db); hcam = H * dc_ / (df_ + dc_); hsrc = "floor/ceiling cross-ratio" + ("" if fc is F else " (side face)"); break
    hm = hcam if hcam else 1.5
    # wall frame: t along the far wall pointing image-right, nrm from the wall toward the camera
    t = df if df[0] > 0 else -df; nrm = np.array([-t[1], t[0]])
    if (cf @ nrm) > 0: nrm = -nrm   # the camera (origin) must be on the +nrm side: (0 - cf) . nrm > 0
    D = d_f * hm
    fwd = np.array([0.0, 1.0]); yaw_rel = math.degrees(math.atan2(fwd @ t, fwd @ (-nrm)))   # + = turned toward image-right along the wall
    side = "right" if far + 1 < len(faces) else ("left" if far > 0 else None)
    def floor_top(x): y = F["floor"][0] * x + F["floor"][1]; q = top(level(rays(np.array([[x, y]])), p), -1); return q[0] * hm if len(q) else None
    cx = F["x1"] if side == "right" else F["x0"]
    adj = faces[far + 1] if side == "right" else (faces[far - 1] if side == "left" else None)
    if adj is not None and adj["floor"]:
        q = geom.intersect(F["floor"], adj["floor"])
        if q is not None and -0.1 * w < q[0] < 1.1 * w: cx = float(q[0])
    corner = floor_top(cx) if side else floor_top(w / 2)
    along = float(-(corner @ t)) if corner is not None else 0.0     # camera's position along the wall relative to the corner (+ = right of it)
    left_end, right_end = floor_top(max(F["x0"], 1)), floor_top(min(F["x1"], w - 1))
    vis = float(np.linalg.norm(right_end - left_end)) if left_end is not None and right_end is not None else None
    return {"pitch": math.degrees(p), "h": hm, "h_measured": hcam, "h_source": hsrc, "D": D, "yaw_rel": yaw_rel, "side": side, "along": along,
            "far_visible_m": vis, "n_faces": len(faces), "far_face": far, "far_x": [F["x0"] / w, F["x1"] / w], "corner_x": cx / w, "hfov": info["hfov_deg"], "aspect": w / h}

# hand adjustments after looking at the first renders (recorded in cameras.json as "adjusted")
ADJUST = {"gs-20665/11.jpg": {"pos_xz": [2.6, 7.4], "why": "metrology put the camera 0.35 m from the plan room's east wall (the photo room is wider), so the render was a wall; moved 1 m toward the room centre, yaw/pitch/fov unchanged"}}
SIDES = {"N": ((0, -1), (1, 0)), "E": ((1, 0), (0, 1)), "S": ((0, 1), (-1, 0)), "W": ((-1, 0), (0, -1))}   # (into the wall, image-right along it)
def place(unit, rid, wall, est):
    L = json.load(open(ROOT / f"app/plan3d/layouts/{unit}.json")); room = next(r for r in L["rooms"] if r["id"] == rid)
    P = np.array(room["polygon"]); x0, z0 = P.min(0); x1, z1 = P.max(0); into, right = map(np.array, SIDES[wall])
    # far wall line and its ends (image-left end and image-right end as seen facing it)
    ends = {"N": ((x0, z0), (x1, z0)), "E": ((x1, z0), (x1, z1)), "S": ((x1, z1), (x0, z1)), "W": ((x0, z1), (x0, z0))}[wall]
    lend, rend = map(np.array, ends); width = float(np.linalg.norm(rend - lend)); depth = (z1 - z0) if wall in "NS" else (x1 - x0)
    if est["side"] == "right": base = rend
    elif est["side"] == "left": base = lend
    else: base = (lend + rend) / 2
    along, D = est["along"], est["D"]
    pos = base + along * right - D * into
    m = 0.35; pc = np.array([np.clip(pos[0], x0 + m, x1 - m), np.clip(pos[1], z0 + m, z1 - m)])
    yaw_wall = math.degrees(math.atan2(into[0], into[1]))   # walk yaw facing straight into the wall
    yaw = (yaw_wall - est["yaw_rel"]) % 360   # three.js yaw grows toward +x; turning image-right while facing N (+x) = yaw decreasing from 180
    # check the sign: facing N (yaw 180), right is +x; direction (sin y, cos y): y=180-a -> (sin a, -cos a) -> +x for a>0. ok
    eye = est["h"] if 1.2 <= est["h"] <= 1.7 else 1.5
    return {"pos": [round(float(pc[0]), 3), round(eye, 3), round(float(pc[1]), 3)], "yaw": round(yaw, 2), "pitch": round(est["pitch"], 2), "fov": round(est["hfov"], 2),
            "aspect": round(est["aspect"], 4), "pos_unclamped": [round(float(pos[0]), 3), round(float(pos[1]), 3)], "clamped": bool(np.linalg.norm(pos - pc) > 0.02),
            "room_wall_m": round(width, 2), "room_depth_m": round(float(depth), 2)}

if __name__ == "__main__":
    out = []
    for lid, n, unit, rid, wall in PAIRS:
        pf = json.load(open(LIST / f"{lid}/photo_facts.json")); H = next((x.get("ceiling_m") for x in pf["photos"] if x["index"] == int(n)), None) or 2.6
        est = estimate(lid, n, H); cam = place(unit, rid, wall, est)
        adj = ADJUST.get(f"{lid}/{n}.jpg")
        if adj: cam["pos_metrology"] = list(cam["pos"]); cam["pos"] = [adj["pos_xz"][0], cam["pos"][1], adj["pos_xz"][1]]; cam["adjusted"] = adj["why"]
        rec = {"unit": unit, "room": rid, "photo": f"{lid}/{n}.jpg", "wall": wall, **cam, "photo_metrology": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in est.items()}, "photo_ceiling_m": H}
        out.append(rec); print(json.dumps(rec))
    json.dump(out, open(HERE / "cameras.json", "w"), indent=1)
