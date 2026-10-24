"""Add Phase-2 layout (textured walls, floor, ceiling, openings) to a scene and a debug plan image."""
import numpy as np, trimesh, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from PIL import Image

def wall_mesh(e, ceil_m, img, holes=None):
    """Wall quad in the (along, height) plane with window/door rectangles cut out; UV = (along/L, height/ceil)."""
    from shapely.geometry import Polygon
    a, b = np.array(e["a"]), np.array(e["b"]); L = float(np.linalg.norm(b - a)); t = (b - a) / max(L, 1e-9)
    poly = Polygon([(0, 0), (L, 0), (L, ceil_m), (0, ceil_m)])
    for h in holes or []:
        s0, s1 = max(0.02, min(h["s0"], h["s1"])), min(L - 0.02, max(h["s0"], h["s1"])); y0, y1 = max(0.02, h["sill_m"]), min(ceil_m - 0.02, h["sill_m"] + h["height_m"])
        if s1 - s0 > 0.1 and y1 - y0 > 0.1: poly = poly.difference(Polygon([(s0, y0), (s1, y0), (s1, y1), (s0, y1)]))
    try: vv, ff = trimesh.creation.triangulate_polygon(poly)
    except Exception: vv, ff = np.array([[0, 0], [L, 0], [L, ceil_m], [0, ceil_m]], float), np.array([[0, 1, 2], [0, 2, 3]])
    vv = np.asarray(vv); v3 = np.c_[a[0] + t[0] * vv[:, 0], vv[:, 1], a[1] + t[1] * vv[:, 0]]
    uv = np.c_[vv[:, 0] / max(L, 1e-9), vv[:, 1] / ceil_m]
    return trimesh.Trimesh(vertices=v3, faces=np.asarray(ff), visual=trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(img)), process=False)

def add_layout(scene, V, edges, ceil_m, wtex, ftex, openings):
    cen = V.mean(0)
    for k, e in enumerate(edges):
        img = wtex[k]["img"]; holes = [o for o in openings if o["edge"] == k]
        scene.add_geometry(wall_mesh(e, ceil_m, img, holes), node_name=f"lwall_{k}", geom_name=f"lwall_{k}")
    # floor as polygon fan (simple, may be non-convex: use earcut via trimesh)
    from shapely.geometry import Polygon
    poly = Polygon(V); 
    try:
        vv, ff = trimesh.creation.triangulate_polygon(poly)
    except Exception:
        vv, ff = V, [[0, i, i + 1] for i in range(1, len(V) - 1)]
    vv = np.asarray(vv); lo, hi = np.array(ftex["lo"]), np.array(ftex["hi"])
    uv = (vv - lo) / np.maximum(hi - lo, 1e-6); uv[:, 1] = 1 - uv[:, 1]
    v3 = np.c_[vv[:, 0], np.zeros(len(vv)), vv[:, 1]]
    scene.add_geometry(trimesh.Trimesh(vertices=v3, faces=ff, visual=trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(ftex["img"])), process=False), node_name="lfloor", geom_name="lfloor")
    v3c = v3.copy(); v3c[:, 1] = ceil_m
    scene.add_geometry(trimesh.Trimesh(vertices=v3c, faces=ff, process=False), node_name="lceiling", geom_name="lceiling")
    # orient opening normals outward
    for o in openings:
        c = np.array(o["center"]); n = np.array(o["normal"]); 
        if n @ np.array([c[0] - cen[0], 0, c[2] - cen[1]]) < 0: n = -n
        o["normal"] = n.round(3).tolist()

def plan_image(carved, V, edges, cams, openings, path):
    lo = carved["lo"]; H, W = carved["region"].shape
    fig, ax = plt.subplots(figsize=(9, 9)); ax.set_facecolor("black")
    ext = [lo[0], lo[0] + W * 0.05, lo[1], lo[1] + H * 0.05]
    ax.imshow(np.log1p(carved["free"]), origin="lower", extent=ext, cmap="Blues", alpha=0.9)
    ax.imshow(np.ma.masked_where(carved["hit"] < 2, carved["hit"]), origin="lower", extent=ext, cmap="Reds", alpha=0.9)
    ax.contour(carved["region"], levels=[0.5], origin="lower", extent=ext, colors="lime", linewidths=1)
    if V is not None:
        P = np.vstack([V, V[:1]]); ax.plot(P[:, 0], P[:, 1], "w-", lw=2.5)
        for k, e in enumerate(edges): mid = (np.array(e["a"]) + np.array(e["b"])) / 2; ax.annotate(str(k), mid, color="yellow", fontsize=9)
    ax.scatter(cams[:, 0], cams[:, 2], c="red", marker="^", s=70, edgecolors="white", zorder=5)
    for o in openings:
        c = o["center"]; ax.scatter(c[0], c[2], c="cyan" if o["kind"] == "window" else "magenta", s=70, marker="s", zorder=6)
    ax.set_aspect("equal"); ax.set_title("free-space carve (blue), wall hits (red), region (green), polygon (white)")
    plt.tight_layout(); plt.savefig(path, dpi=80); plt.close()
