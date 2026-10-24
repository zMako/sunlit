"""Export a room as (a) per-photo textured depth meshes and (b) a fitted layout (floor, ceiling, wall planes) as GLB for three.js."""
import sys, json, pathlib, numpy as np, trimesh, cv2
from PIL import Image
src = pathlib.Path(sys.argv[1]); dst = pathlib.Path(sys.argv[2]); name = sys.argv[3]; CEIL_M = float(sys.argv[4]) if len(sys.argv) > 4 else 2.6
d = np.load(src / "pred.npz"); a = json.load(open(src / "analysis.json"))
wp, conf, rgb, extr, intr = d["world_points"], d["conf"], d["rgb"], d["extrinsic"], d["intrinsic"]
S, H, W = conf.shape
down = extr[:, 1, :3]; down /= np.linalg.norm(down, axis=1, keepdims=True); g = down.mean(0); g /= np.linalg.norm(g); up = -g
ex = np.cross(up, extr[0, 2, :3]); ex /= np.linalg.norm(ex); ez = np.cross(ex, up)
floor_h, ceil_h = a["floor_h"], a["ceil_h"]; upm = (ceil_h - floor_h) / CEIL_M
def metric(p): q = np.stack([p @ ex, p @ up, p @ ez], -1); q[..., 1] -= floor_h; return q / upm
scene = trimesh.Scene()
# ---- (a) textured depth meshes, one per photo ----
step = 1
for i in range(S):
    # smooth depth (in camera z) with a bilateral filter to kill quantization stripes
    cam = (extr[i, :3, :3] @ wp[i].reshape(-1, 3).T).T + extr[i, :3, 3]; z = cam[:, 2].reshape(H, W).astype(np.float32)
    zs = cv2.bilateralFilter(z, 9, 0.08 * float(np.median(z)), 7)
    # re-unproject with smoothed z
    vs, us = np.mgrid[0:H, 0:W]; K = intr[i]; x = (us - K[0, 2]) / K[0, 0] * zs; y = (vs - K[1, 2]) / K[1, 1] * zs
    camp = np.stack([x, y, zs], -1).reshape(-1, 3); R = extr[i, :3, :3]; world = (R.T @ (camp - extr[i, :3, 3]).T).T.reshape(H, W, 3)
    P = metric(world)[::step, ::step]; C = conf[i][::step, ::step]; Z = zs[::step, ::step]; h, w = P.shape[:2]
    ok = np.ones_like(C, bool)
    idx = np.arange(h * w).reshape(h, w)
    # faces: two triangles per cell, keep if all corners ok and depth jump small
    a0, a1, a2, a3 = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    z0, z1, z2, z3 = Z[:-1, :-1], Z[:-1, 1:], Z[1:, :-1], Z[1:, 1:]
    o = ok[:-1, :-1] & ok[:-1, 1:] & ok[1:, :-1] & ok[1:, 1:]
    zmax = np.maximum.reduce([z0, z1, z2, z3]); zmin = np.minimum.reduce([z0, z1, z2, z3]); o &= (zmax - zmin) < 0.5 * zmin
    f1 = np.stack([a0, a2, a1], -1)[o]; f2 = np.stack([a1, a2, a3], -1)[o]
    faces = np.concatenate([f1, f2]); 
    if len(faces) < 50: continue
    uv = np.stack([us[::step, ::step] / (W - 1), 1 - vs[::step, ::step] / (H - 1)], -1).reshape(-1, 2)
    tex = Image.fromarray(rgb[i])
    m = trimesh.Trimesh(vertices=P.reshape(-1, 3), faces=faces, visual=trimesh.visual.TextureVisuals(uv=uv, image=tex), process=False)
    m.remove_unreferenced_vertices()
    scene.add_geometry(m, node_name=f"photo_{i}", geom_name=f"photo_{i}")
# ---- (b) layout: wall planes from a top-down RANSAC on wall-band points ----
good = conf > max(np.quantile(conf, 0.4), 1.5); P = metric(wp)[good]
band = P[(P[:, 1] > 0.25 * CEIL_M) & (P[:, 1] < 0.9 * CEIL_M)]; xz = band[:, [0, 2]]
if len(xz) > 20000: xz = xz[np.random.default_rng(0).choice(len(xz), 20000, replace=False)]
walls = []; rem = xz.copy(); rng = np.random.default_rng(1)
for _ in range(8):
    if len(rem) < 400: break
    best = None
    for _ in range(400):
        p, q = rem[rng.choice(len(rem), 2, replace=False)]; dvec = q - p; L = np.linalg.norm(dvec)
        if L < 0.3: continue
        n = np.array([-dvec[1], dvec[0]]) / L; dist = np.abs((rem - p) @ n); inl = dist < 0.06
        if best is None or inl.sum() > best[0]: best = (inl.sum(), p, dvec / L, n, inl)
    if best is None or best[0] < max(300, 0.04 * len(xz)): break
    cnt, p, t, n, inl = best; pts = rem[inl]
    # refine by PCA on inliers
    c = pts.mean(0); u, s, vt = np.linalg.svd(pts - c, full_matrices=False); t = vt[0]; n = np.array([-t[1], t[0]])
    proj = (pts - c) @ t; lo, hi = np.quantile(proj, 0.02), np.quantile(proj, 0.98)
    if hi - lo < 0.8: rem = rem[~inl]; continue
    walls.append({"a": (c + t * lo).round(3).tolist(), "b": (c + t * hi).round(3).tolist(), "n_pts": int(cnt)})
    rem = rem[~inl]
# wall quads floor->ceiling
for k, wl in enumerate(walls):
    (ax, az), (bx, bz) = wl["a"], wl["b"]
    v = np.array([[ax, 0, az], [bx, 0, bz], [bx, CEIL_M, bz], [ax, CEIL_M, az]], float)
    m = trimesh.Trimesh(vertices=v, faces=[[0, 1, 2], [0, 2, 3]], process=False); m.visual.face_colors = [235, 238, 245, 110]
    scene.add_geometry(m, node_name=f"wall_{k}", geom_name=f"wall_{k}")
# floor: convex hull of floor-band points
fl = P[(P[:, 1] > -0.15) & (P[:, 1] < 0.15)][:, [0, 2]]
if len(fl) > 50:
    hull = trimesh.points.PointCloud(np.c_[fl[:, 0], np.zeros(len(fl)), fl[:, 1]]).convex_hull if False else None
    from scipy.spatial import ConvexHull
    hh = ConvexHull(fl); ring = fl[hh.vertices]; c = ring.mean(0)
    v = np.r_[[[c[0], 0, c[1]]], np.c_[ring[:, 0], np.zeros(len(ring)), ring[:, 1]]]
    faces = [[0, 1 + j, 1 + (j + 1) % len(ring)] for j in range(len(ring))]
    m = trimesh.Trimesh(vertices=v, faces=faces, process=False); m.visual.face_colors = [160, 130, 95, 140]
    scene.add_geometry(m, node_name="floor", geom_name="floor")
cams_out = []
for i in range(S):
    R = extr[i, :3, :3]; t = extr[i, :3, 3]; pos = metric(-R.T @ t)
    right = np.array([R[0] @ ex, R[0] @ up, R[0] @ ez]); dn = np.array([R[1] @ ex, R[1] @ up, R[1] @ ez]); fwd = np.array([R[2] @ ex, R[2] @ up, R[2] @ ez])
    fov_v = float(2 * np.degrees(np.arctan(H / (2 * intr[i][1, 1])))); fov_h = float(2 * np.degrees(np.arctan(W / (2 * intr[i][0, 0]))))
    cams_out.append({"pos": pos.round(4).tolist(), "right": right.round(4).tolist(), "up": (-dn).round(4).tolist(), "fwd": fwd.round(4).tolist(), "fov_v": round(fov_v, 2), "fov_h": round(fov_h, 2), "aspect": W / H})
scene.export(dst / f"{name}.glb")
json.dump({"walls": walls, "ceiling_m": CEIL_M, "cameras": cams_out}, open(dst / f"{name}_layout.json", "w"))
print(f"{name}: {S} photo meshes, {len(walls)} walls, glb {(dst / f'{name}.glb').stat().st_size/1e6:.1f} MB")
