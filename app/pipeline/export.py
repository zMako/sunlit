"""Export a cleaned room: GLB with per-photo textured meshes in two tiers (exact for photo views, clipped for orbit),
layout planes (walls, floor, ceiling) and a JSON with cameras, planes, labels summary."""
import json, numpy as np, trimesh
from PIL import Image
from scipy.spatial import ConvexHull
from geometry import FLOOR, CEIL, WALL

def photo_mesh(pts, rgb, cam, good, tier, conf=None):
    if tier == 'clip':
        import cv2
        g = (conf > np.quantile(conf, 0.1)).astype(np.uint8) if conf is not None else good.astype(np.uint8)
        g = cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)); g = cv2.morphologyEx(g, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        pts, good = pts[::2, ::2], g.astype(bool)[::2, ::2]
    H, W = pts.shape[:2]; idx = np.arange(H * W).reshape(H, W)
    z = np.linalg.norm(pts - cam, axis=-1)
    a0, a1, a2, a3 = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    z0, z1, z2, z3 = z[:-1, :-1], z[:-1, 1:], z[1:, :-1], z[1:, 1:]
    zmax = np.maximum.reduce([z0, z1, z2, z3]); zmin = np.minimum.reduce([z0, z1, z2, z3])
    if tier == "exact":
        o = (zmax - zmin) < 0.5 * zmin
    else:
        o = good[:-1, :-1] & good[:-1, 1:] & good[1:, :-1] & good[1:, 1:] & ((zmax - zmin) < 0.08 * zmin + 0.03)
    faces = np.concatenate([np.stack([a0, a2, a1], -1)[o], np.stack([a1, a2, a3], -1)[o]])
    if len(faces) < 50: return None
    vs, us = np.mgrid[0:H, 0:W]; uv = np.stack([us / (W - 1), 1 - vs / (H - 1)], -1).reshape(-1, 2)
    m = trimesh.Trimesh(vertices=pts.reshape(-1, 3), faces=faces, visual=trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(rgb)), process=False)
    m.remove_unreferenced_vertices(); return m

def export(room, dst, name, photo_paths, extra=None):
    dst.mkdir(parents=True, exist_ok=True); scene = trimesh.Scene(); S = room["pts"].shape[0]
    for i in range(S):
        for tier in ("exact", "clip"):
            m = photo_mesh(room["pts"][i], room["rgb"][i], room["cams"][i], room["good"][i], tier, conf=room["conf"][i])
            if m is not None: scene.add_geometry(m, node_name=f"photo_{i}_{tier}", geom_name=f"photo_{i}_{tier}")
    ceil_m = room["ceil_m"]
    for k, pl in enumerate(room["planes"] if extra is None else []):
        if pl["kind"] != "wall" or not pl["extent"]: continue
        e = pl["extent"]; A, B = e["a"], e["b"]
        v = np.array([[A[0], 0, A[1]], [B[0], 0, B[1]], [B[0], ceil_m, B[1]], [A[0], ceil_m, A[1]]])
        m = trimesh.Trimesh(vertices=v, faces=[[0, 1, 2], [0, 2, 3]], process=False); scene.add_geometry(m, node_name=f"wall_{k}", geom_name=f"wall_{k}")
    fl = room["pts"][room["labels"] == FLOOR][:, [0, 2]]
    if extra is None and len(fl) > 100:
        fl = fl[np.random.default_rng(0).choice(len(fl), min(len(fl), 20000), replace=False)]
        hh = ConvexHull(fl); ring = fl[hh.vertices]; c = ring.mean(0)
        v = np.r_[[[c[0], 0, c[1]]], np.c_[ring[:, 0], np.zeros(len(ring)), ring[:, 1]]]
        faces = [[0, 1 + j, 1 + (j + 1) % len(ring)] for j in range(len(ring))]
        scene.add_geometry(trimesh.Trimesh(vertices=v, faces=faces, process=False), node_name="floor", geom_name="floor")
    if extra: extra(scene)
    scene.export(dst / f"{name}.glb")
    pts = room["pts"]; good = room["good"]; lo, hi = np.quantile(pts[good], 0.02, 0), np.quantile(pts[good], 0.98, 0)
    meta = {"name": name, "ceiling_m": ceil_m, "cameras": room["cam_basis"], "planes": room["planes"], "stats": room["stats"],
            "bounds": [lo.round(2).tolist(), hi.round(2).tolist()], "photos": [str(p) for p in photo_paths], "windows": []}
    json.dump(meta, open(dst / f"{name}.json", "w"), indent=1)
    return meta
