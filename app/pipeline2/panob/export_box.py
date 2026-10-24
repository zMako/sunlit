"""Textured box GLB from a panorama + rectangle layout (camera at origin, floor at y=0 after lifting by cam_h)."""
import numpy as np, trimesh
from PIL import Image
import equirect as E

def face_mesh(corners3, tex, name):
    """corners3: 4 points (3,) in order a,b,c,d (quad), tex: uint8 (h, w, 3) mapped a->(0,0) b->(1,0) c->(1,1) d->(0,1)."""
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    m = trimesh.Trimesh(vertices=np.asarray(corners3, np.float32), faces=[[0, 1, 2], [0, 2, 3]], visual=trimesh.visual.TextureVisuals(uv=uv, image=Image.fromarray(tex)), process=False)
    m.metadata["name"] = name; return m

def bake(pano, a, b, d, cam, res_px_m=90):
    """Texture for the parallelogram a + s(b-a) + t(d-a), s,t in [0,1], by equirect lookup from the camera."""
    w = max(8, int(np.linalg.norm(b - a) * res_px_m)); h = max(8, int(np.linalg.norm(d - a) * res_px_m))
    s, t = np.meshgrid((np.arange(w) + 0.5) / w, (np.arange(h) + 0.5) / h)
    p = a[None, None] + s[..., None] * (b - a)[None, None] + t[..., None] * (d - a)[None, None]
    dvec = p - cam; dvec /= np.linalg.norm(dvec, axis=-1, keepdims=True)
    return E.sample(pano, dvec.astype(np.float32))

def export(pano, lay, out_glb, ceil_rgb=None):
    C = np.array(lay["corners"], np.float32); H = lay["ceiling_m"]; ch = lay["cam_h"]
    cam = np.array([0, ch, 0], np.float32)           # panorama centre, floor at y = 0
    fl = [np.array([c[0], 0.0, c[1]], np.float32) for c in C]; ce = [np.array([c[0], H, c[1]], np.float32) for c in C]
    scene = trimesh.Scene()
    for k in range(4):
        a, b = fl[k], fl[(k + 1) % 4]; d, c2 = ce[k], ce[(k + 1) % 4]
        tex = bake(pano, a, b, d, cam)
        # texture axes: s along a->b (u), t along a->d (v); uv (0,0) at a maps to tex row 0 -> flip rows so v grows upward
        scene.add_geometry(face_mesh([a, b, c2, d], tex[::-1].copy(), f"wall_{k}"), node_name=f"wall_{k}", geom_name=f"wall_{k}")
    a, b, c2, d = fl[0], fl[1], fl[2], fl[3]
    scene.add_geometry(face_mesh([a, b, c2, d], bake(pano, a, b, d, cam)[::-1].copy(), "floor"), node_name="floor", geom_name="floor")
    a, b, c2, d = ce[0], ce[3], ce[2], ce[1]   # reversed winding so the normal points down
    ctex = bake(pano, a, b, d, cam)[::-1].copy()
    if ceil_rgb is not None: ctex[:] = np.asarray(ceil_rgb, np.uint8)   # the generator invents beams and planks on ceilings; a flat measured colour looks right
    scene.add_geometry(face_mesh([a, b, c2, d], ctex, "ceiling"), node_name="ceiling", geom_name="ceiling")
    scene.export(out_glb); return out_glb
