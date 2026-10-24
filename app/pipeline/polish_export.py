"""Polished shell export: walls with openings cut, reveals, frames, glass, outside-view billboards, floor, ceiling, baseboards."""
import numpy as np, trimesh, json, pathlib
from PIL import Image
from shapely.geometry import Polygon

def quad(v, uv=None, img=None, color=None):
    faces = np.array([[0, 1, 2], [0, 2, 3]]); m = trimesh.Trimesh(vertices=np.asarray(v, float), faces=faces, process=False)
    if img is not None: m.visual = trimesh.visual.TextureVisuals(uv=np.asarray(uv if uv is not None else [[0, 0], [1, 0], [1, 1], [0, 1]], float), image=Image.fromarray(img))
    elif color is not None: m.visual.face_colors = color
    return m

def wall_with_holes(fr, ceil_m, img, holes):
    a, d, L = fr["a"], fr["dir"], fr["len"]; poly = Polygon([(0, 0), (L, 0), (L, ceil_m), (0, ceil_m)])
    for h in holes:
        s0, s1 = max(0.02, h["s0"]), min(L - 0.02, h["s1"]); y0, y1 = max(0.0, h["sill_m"]), min(ceil_m - 0.02, h["sill_m"] + h["height_m"])
        if s1 - s0 > 0.1 and y1 - y0 > 0.1: poly = poly.difference(Polygon([(s0, y0), (s1, y0), (s1, y1), (s0, y1)]))
    vv, ff = trimesh.creation.triangulate_polygon(poly); vv = np.asarray(vv)
    v3 = np.c_[a[0] + d[0] * vv[:, 0], vv[:, 1], a[1] + d[1] * vv[:, 0]]; uv = np.c_[vv[:, 0] / L, vv[:, 1] / ceil_m]
    return trimesh.Trimesh(vertices=v3, faces=np.asarray(ff), visual=trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(img)), process=False)

def opening_parts(fr, o, ceil_m, wall_img, outside_img=None, reveal=0.15, frame=0.05, room_center=None):
    """Reveal box (inward), frame strips, glass pane, and a billboard behind the opening textured with the outside view."""
    a, d, n2 = fr["a"], fr["dir"], fr["n"]; n3 = np.array([n2[0], 0.0, n2[1]]); d3 = np.array([d[0], 0.0, d[1]]); up = np.array([0, 1.0, 0])
    s0, s1, y0, y1 = o["s0"], o["s1"], o["sill_m"], o["sill_m"] + o["height_m"]
    P = lambda s, y, depth: np.array([a[0], 0, a[1]]) + d3 * s + up * y + n3 * depth   # depth > 0 = outward
    parts = []
    # reveal: four inward-facing quads from the wall plane to `reveal` outward (jamb depth); colour = wall median
    wc = tuple(int(v) for v in np.median(wall_img.reshape(-1, 3), 0)) + (255,)
    for (A, B) in (((s0, y0), (s1, y0)), ((s1, y0), (s1, y1)), ((s1, y1), (s0, y1)), ((s0, y1), (s0, y0))):
        parts.append(("reveal", quad([P(*A, 0), P(*B, 0), P(*B, reveal), P(*A, reveal)], color=wc)))
    if o["kind"] == "window":
        # frame: strips at the outer plane around the opening
        fc = (245, 245, 240, 255); f = frame
        for (A, B, C, D) in (((s0, y0), (s1, y0), (s1, y0 + f), (s0, y0 + f)), ((s0, y1 - f), (s1, y1 - f), (s1, y1), (s0, y1)), ((s0, y0), (s0 + f, y0), (s0 + f, y1), (s0, y1)), ((s1 - f, y0), (s1, y0), (s1, y1), (s1 - f, y1))):
            parts.append(("frame", quad([P(*A, reveal), P(*B, reveal), P(*C, reveal), P(*D, reveal)], color=fc)))
        # glass pane (transparent in the viewer)
        parts.append(("glass", quad([P(s0, y0, reveal * 0.6), P(s1, y0, reveal * 0.6), P(s1, y1, reveal * 0.6), P(s0, y1, reveal * 0.6)], color=(180, 210, 230, 70))))

    return parts

def export_polished(room, V, frames, pol, textures, outside, ftex, dst, name):
    ceil_m = room["ceil_m"]; scene = trimesh.Scene(); V = np.asarray(V, float); cen = V.mean(0)
    for fr in frames:
        holes = [o for o in pol["openings"] if o["edge"] == fr["k"]]; img = textures[fr["k"]]
        scene.add_geometry(wall_with_holes(fr, ceil_m, img, holes), node_name=f"pwall_{fr['k']}", geom_name=f"pwall_{fr['k']}")
        for j, o in enumerate(holes):
            for kind, m in opening_parts(fr, o, ceil_m, img, outside.get((fr["k"], j)), room_center=cen):
                scene.add_geometry(m, node_name=f"p{kind}_{fr['k']}_{j}", geom_name=f"p{kind}_{fr['k']}_{j}")
        # baseboard: 10 cm high, 1.5 cm proud, light colour
        a, d = fr["a"], fr["dir"]; n2 = fr["n"]; inward = -np.array([n2[0], 0, n2[1]]) * 0.015; A = np.array([a[0], 0, a[1]]); B = A + np.array([d[0], 0, d[1]]) * fr["len"]
        scene.add_geometry(quad([A + inward, B + inward, B + inward + [0, 0.10, 0], A + inward + [0, 0.10, 0]], color=(240, 238, 232, 255)), node_name=f"pbase_{fr['k']}", geom_name=f"pbase_{fr['k']}")
    # floor and ceiling
    vv, ff = trimesh.creation.triangulate_polygon(Polygon(V)); vv = np.asarray(vv); lo, hi = np.array(ftex["lo"]), np.array(ftex["hi"])
    uv = (vv - lo) / np.maximum(hi - lo, 1e-6); uv[:, 1] = 1 - uv[:, 1]
    scene.add_geometry(trimesh.Trimesh(vertices=np.c_[vv[:, 0], np.zeros(len(vv)), vv[:, 1]], faces=ff, visual=trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(ftex["img"])), process=False), node_name="pfloor", geom_name="pfloor")
    ceil_col = tuple(int(v) for v in room.get("ceil_colour", (236, 236, 232))) + (255,)
    cm = trimesh.Trimesh(vertices=np.c_[vv[:, 0], np.full(len(vv), ceil_m), vv[:, 1]], faces=ff, process=False); cm.visual.face_colors = ceil_col
    scene.add_geometry(cm, node_name="pceiling", geom_name="pceiling")
    scene.export(pathlib.Path(dst) / f"{name}_polished.glb"); return str(pathlib.Path(dst) / f"{name}_polished.glb")
