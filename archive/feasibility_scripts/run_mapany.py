"""MapAnything metric test: ceiling height and camera heights in metres."""
import sys, time, pathlib, numpy as np, torch
sys.path.insert(0, str(pathlib.Path(__file__).parent / "map-anything"))
from mapanything.models import MapAnything
from mapanything.utils.image import load_images
img_dir = sys.argv[1]; device = sys.argv[2] if len(sys.argv) > 2 else "mps"
t0 = time.time(); model = MapAnything.from_pretrained("facebook/map-anything").to(device).eval(); print(f"loaded {time.time()-t0:.0f}s")
paths = sorted(str(p) for p in pathlib.Path(img_dir).glob("*.jpg"))
views = load_images(paths)
t1 = time.time()
with torch.no_grad():
    preds = model.infer(views, memory_efficient_inference=False, use_amp=False, apply_mask=True, mask_edges=True)
print(f"inference {time.time()-t1:.1f}s for {len(paths)} images; keys: {list(preds[0].keys())}")
pts, downs, cams, confs = [], [], [], []
for p in preds:
    P = p["pts3d"][0].float().cpu().numpy(); m = p["mask"][0, ..., 0].cpu().numpy().astype(bool) if "mask" in p else np.ones(P.shape[:2], bool)
    pose = p["camera_poses"][0].float().cpu().numpy()  # cam2world 4x4
    downs.append(pose[:3, 1]); cams.append(pose[:3, 3]); pts.append(P[m].reshape(-1, 3))
    if "conf" in p: confs.append(float(p["conf"][0].float().mean()))
g = np.mean(downs, 0); g /= np.linalg.norm(g); up = -g
h = np.concatenate(pts) @ up
hist, edges = np.histogram(h, bins=200, range=(np.quantile(h, 0.005), np.quantile(h, 0.995))); c = (edges[:-1] + edges[1:]) / 2; n = len(hist)
floor, ceil = c[np.argmax(hist[: n // 3])], c[2 * n // 3 + np.argmax(hist[2 * n // 3:])]
print(f"METRIC ceiling height = {ceil - floor:.2f} m ; camera heights = {np.round(np.array(cams) @ up - floor, 2).tolist()} ; mean conf {np.round(confs, 2).tolist()}")
print(f"cam-to-cam distances (m): {np.round([np.linalg.norm(cams[i]-cams[0]) for i in range(1, len(cams))], 2).tolist()}")
