"""Run VGGT on a folder of images; save point cloud, cameras, and diagnostic renders."""
import sys, time, json, pathlib, numpy as np, torch
sys.path.insert(0, str(pathlib.Path(__file__).parent / "vggt"))
from vggt.models.vggt import VGGT
from vggt.utils.load_fn import load_and_preprocess_images
from vggt.utils.pose_enc import pose_encoding_to_extri_intri
from vggt.utils.geometry import unproject_depth_map_to_point_map, closed_form_inverse_se3
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

img_dir = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
device = sys.argv[3] if len(sys.argv) > 3 else ("mps" if torch.backends.mps.is_available() else "cpu")
paths = sorted([str(p) for p in img_dir.glob("*.jpg")] + [str(p) for p in img_dir.glob("*.png")] + [str(p) for p in img_dir.glob("*.JPG")])
from PIL import Image
from collections import Counter
ar=[round(Image.open(q).size[0]/Image.open(q).size[1],2) for q in paths]
maj=Counter(ar).most_common(1)[0][0]
dropped=[q.split("/")[-1] for q,a in zip(paths,ar) if abs(a-maj)>0.05]
paths=[q for q,a in zip(paths,ar) if abs(a-maj)<=0.05]
print(f"{len(paths)} images (dropped {dropped} for aspect != {maj}), device={device}")

t0 = time.time()
model = VGGT()
model.load_state_dict(torch.load(pathlib.Path(__file__).parent / "weights/model.pt", map_location="cpu"))
model = model.to(device).eval()
print(f"model loaded {time.time()-t0:.1f}s")

images = load_and_preprocess_images(paths).to(device)
t1 = time.time()
with torch.no_grad():
    pred = model(images)
if device == "mps": torch.mps.synchronize()
t_inf = time.time() - t1
print(f"inference {t_inf:.1f}s for {len(paths)} images at {tuple(images.shape[-2:])}")

extr, intr = pose_encoding_to_extri_intri(pred["pose_enc"], images.shape[-2:])
P = {k: v.float().cpu().numpy().squeeze(0) for k, v in pred.items() if isinstance(v, torch.Tensor)}
extr = extr.float().cpu().numpy().squeeze(0); intr = intr.float().cpu().numpy().squeeze(0)
depth = P["depth"]; dconf = P["depth_conf"]
wp = unproject_depth_map_to_point_map(depth, extr, intr)  # S,H,W,3
rgb = np.transpose(images.cpu().numpy(), (0, 2, 3, 1))
S, H, W = dconf.shape

# camera centers in world
cams = closed_form_inverse_se3(np.concatenate([extr, np.tile([[[0, 0, 0, 1]]], (S, 1, 1))], 1))[:, :3, 3]
stats = {"n_images": S, "inference_s": round(t_inf, 1), "hw": [int(H), int(W)],
         "per_image_mean_conf": [float(x) for x in dconf.reshape(S, -1).mean(1)],
         "per_image_frac_conf_gt3": [float(x) for x in (dconf.reshape(S, -1) > 3).mean(1)],
         "cam_centers": cams.round(3).tolist()}
np.savez_compressed(out / "pred.npz", world_points=wp.astype(np.float32), conf=dconf.astype(np.float32),
                    rgb=(rgb * 255).astype(np.uint8), extrinsic=extr, intrinsic=intr, cam_centers=cams)

# --- renders ---
thr = np.quantile(dconf, 0.4)
mask = dconf > max(thr, 1.5)
pts = wp[mask]; cols = rgb[mask]; img_id = np.broadcast_to(np.arange(S)[:, None, None], dconf.shape)[mask]
sub = np.random.default_rng(0).choice(len(pts), min(len(pts), 300000), replace=False)
pts, cols, img_id = pts[sub], cols[sub], img_id[sub]
# robust bounds
lo, hi = np.quantile(pts, 0.02, 0), np.quantile(pts, 0.98, 0)
keep = np.all((pts > lo) & (pts < hi), 1); pts, cols, img_id = pts[keep], cols[keep], img_id[keep]

def scatter(ax, a, b, c, title, cam_a=None, cam_b=None):
    ax.scatter(a, b, s=0.3, c=c, marker=","); ax.set_aspect("equal"); ax.set_title(title); ax.set_facecolor("black")
    if cam_a is not None:
        ax.scatter(cam_a, cam_b, s=60, c="red", marker="^", edgecolors="white", zorder=5)
        for i, (x, y) in enumerate(zip(cam_a, cam_b)): ax.annotate(str(i), (x, y), color="yellow", fontsize=9)

fig, axs = plt.subplots(2, 2, figsize=(18, 18))
# VGGT world = first camera frame (OpenCV: x right, y down, z forward). Top-down = x vs z, with y as height.
scatter(axs[0, 0], pts[:, 0], pts[:, 2], cols, "top-down (x,z) RGB + cameras", cams[:, 0], cams[:, 2])
cmap = plt.get_cmap("tab20")(img_id % 20)
scatter(axs[0, 1], pts[:, 0], pts[:, 2], cmap, "top-down colored by source image", cams[:, 0], cams[:, 2])
scatter(axs[1, 0], pts[:, 0], -pts[:, 1], cols, "front (x, up)", cams[:, 0], -cams[:, 1])
scatter(axs[1, 1], pts[:, 2], -pts[:, 1], cols, "side (z, up)", cams[:, 2], -cams[:, 1])
plt.tight_layout(); plt.savefig(out / "views.png", dpi=70); plt.close()

# contact sheet of inputs + confidence
cols_n = min(S, 6); rows_n = int(np.ceil(S / cols_n))
fig, axs = plt.subplots(rows_n * 2, cols_n, figsize=(3 * cols_n, 2.4 * rows_n * 2), squeeze=False)
for i in range(rows_n * cols_n):
    r, c = divmod(i, cols_n)
    for ax in (axs[2 * r, c], axs[2 * r + 1, c]): ax.axis("off")
    if i < S:
        axs[2 * r, c].imshow(rgb[i]); axs[2 * r, c].set_title(f"{i} conf={stats['per_image_mean_conf'][i]:.1f}", fontsize=8)
        axs[2 * r + 1, c].imshow(np.log1p(dconf[i]), cmap="viridis", vmin=0, vmax=3)
plt.tight_layout(); plt.savefig(out / "inputs_conf.png", dpi=70); plt.close()

# per-pixel height for planarity (floor/ceiling) check: y extent of confident points
y = -wp[..., 1][mask]
stats["height_p02_p98"] = [float(np.quantile(y, 0.02)), float(np.quantile(y, 0.98))]
(out / "stats.json").write_text(json.dumps(stats, indent=1))
print(json.dumps({k: stats[k] for k in ("n_images", "inference_s", "height_p02_p98")}))
print("mean conf per image:", np.round(stats["per_image_mean_conf"], 1).tolist())
print("RUN_DONE")
