"""VGGT reconstruction + cross-view consistency + room clustering. No file side effects except what callers save."""
import sys, pathlib, time, numpy as np, torch
FEAS = pathlib.Path(__file__).resolve().parents[2] / "feasibility"
sys.path.insert(0, str(FEAS / "vggt"))
from vggt.models.vggt import VGGT
from vggt.utils.load_fn import load_and_preprocess_images
from vggt.utils.pose_enc import pose_encoding_to_extri_intri
from vggt.utils.geometry import unproject_depth_map_to_point_map, closed_form_inverse_se3
from PIL import Image
from collections import Counter

_model = None
def model(device="mps"):
    global _model
    if _model is None:
        t = time.time(); m = VGGT(); m.load_state_dict(torch.load(FEAS / "weights/model.pt", map_location="cpu")); _model = m.to(device).eval()
        print(f"[recon] VGGT loaded in {time.time()-t:.1f}s on {device}")
    return _model

def filter_photos(paths):
    """Drop images whose aspect differs from the majority (floor plans, logos, maps)."""
    ar = [round(Image.open(p).size[0] / Image.open(p).size[1], 2) for p in paths]
    maj = Counter(ar).most_common(1)[0][0]
    return [p for p, a in zip(paths, ar) if abs(a - maj) <= 0.05]

def run(paths, device="mps"):
    """Returns dict: world_points (S,H,W,3), conf, rgb uint8 (S,H,W,3), extrinsic (S,3,4), intrinsic (S,3,3), cam_centers (S,3), paths."""
    images = load_and_preprocess_images(list(paths)).to(device)
    t = time.time()
    with torch.no_grad(): pred = model(device)(images)
    if device == "mps": torch.mps.synchronize()
    extr, intr = pose_encoding_to_extri_intri(pred["pose_enc"], images.shape[-2:])
    depth = pred["depth"].float().cpu().numpy().squeeze(0); conf = pred["depth_conf"].float().cpu().numpy().squeeze(0)
    extr = extr.float().cpu().numpy().squeeze(0); intr = intr.float().cpu().numpy().squeeze(0)
    wp = unproject_depth_map_to_point_map(depth, extr, intr)
    rgb = (np.transpose(images.cpu().numpy(), (0, 2, 3, 1)) * 255).astype(np.uint8)
    S = conf.shape[0]
    cams = closed_form_inverse_se3(np.concatenate([extr, np.tile([[[0, 0, 0, 1]]], (S, 1, 1))], 1))[:, :3, 3]
    print(f"[recon] {S} images in {time.time()-t:.1f}s")
    return {"world_points": wp.astype(np.float32), "depth": depth.astype(np.float32), "conf": conf.astype(np.float32), "rgb": rgb,
            "extrinsic": extr, "intrinsic": intr, "cam_centers": cams, "paths": [str(p) for p in paths]}

def consistency(P, min_pts=2000):
    """M[i,j] = fraction of image i's confident points that, projected into j, agree with j's depth within 10%. N[i,j] = points in view."""
    wp, conf, extr, intr = P["world_points"], P["conf"], P["extrinsic"], P["intrinsic"]; S, H, W = conf.shape
    M = np.zeros((S, S)); N = np.zeros((S, S), int); rng = np.random.default_rng(0)
    for i in range(S):
        m = conf[i] > max(np.quantile(conf[i], 0.5), 1.5); Pi = wp[i][m]
        Pi = Pi[rng.choice(len(Pi), min(len(Pi), 20000), replace=False)]; Ph = np.c_[Pi, np.ones(len(Pi))]
        for j in range(S):
            if i == j: continue
            C = (extr[j] @ Ph.T).T; z = C[:, 2]; ok = z > 1e-3
            uv = (intr[j] @ C[ok].T).T; u = uv[:, 0] / uv[:, 2]; v = uv[:, 1] / uv[:, 2]
            inb = (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1)
            if inb.sum() < min_pts: continue
            ui, vi = u[inb].astype(int), v[inb].astype(int)
            zj = (extr[j] @ np.c_[wp[j][vi, ui], np.ones(inb.sum())].T).T[:, 2]
            rel = (z[ok][inb] - zj) / np.maximum(zj, 1e-6); N[i, j] = inb.sum(); M[i, j] = float(np.mean(np.abs(rel) < 0.1))
    return M, N

def cluster(M, N, thr=0.5, min_pts=2000):
    """Connected components over mutually consistent pairs (either direction >= thr). Returns list of index lists, largest first."""
    S = len(M); adj = {i: set() for i in range(S)}
    for i in range(S):
        for j in range(S):
            if i != j and N[i, j] >= min_pts and N[j, i] >= min_pts and min(M[i, j], M[j, i]) >= thr: adj[i].add(j); adj[j].add(i)
    seen, comps = set(), []
    for i in range(S):
        if i in seen: continue
        stack, comp = [i], []
        while stack:
            k = stack.pop()
            if k in seen: continue
            seen.add(k); comp.append(k); stack.extend(adj[k] - seen)
        comps.append(sorted(comp))
    return sorted(comps, key=len, reverse=True)
