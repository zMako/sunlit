"""Score a VGGT reconstruction: gravity, floor/ceiling scale, windows & doors lifted to 3D."""
import sys, json, pathlib, numpy as np, torch
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from PIL import Image

out = pathlib.Path(sys.argv[1]); CEIL_M = 2.6; DOOR_M = 2.03
d = np.load(out / "pred.npz")
wp, conf, rgb, extr, cams = d["world_points"], d["conf"], d["rgb"], d["extrinsic"], d["cam_centers"]
S, H, W = conf.shape

# --- gravity: average of camera "down" axes (row 1 of R, in world coords) ---
down = extr[:, 1, :3]; down = down / np.linalg.norm(down, axis=1, keepdims=True)
g = down.mean(0); g /= np.linalg.norm(g)
tilt = np.degrees(np.arccos(np.clip(down @ g, -1, 1)))
up = -g
# horizontal basis
ex = np.cross(up, extr[0, 2, :3]); ex /= np.linalg.norm(ex); ez = np.cross(ex, up)
def to_room(p):  # p (...,3) -> (x, height, z)
    return np.stack([p @ ex, p @ up, p @ ez], -1)

good = conf > max(np.quantile(conf, 0.4), 1.5)
R = to_room(wp)
h = R[..., 1][good]
# floor / ceiling peaks
hist, edges = np.histogram(h, bins=200, range=(np.quantile(h, 0.005), np.quantile(h, 0.995)))
centers = (edges[:-1] + edges[1:]) / 2
n = len(hist); lo_i = np.argmax(hist[: n // 3]); hi_i = 2 * n // 3 + np.argmax(hist[2 * n // 3:])
floor_h, ceil_h = centers[lo_i], centers[hi_i]
unit_per_m = (ceil_h - floor_h) / CEIL_M
cam_h_m = (to_room(cams)[:, 1] - floor_h) / unit_per_m
res = {"tilt_deg_per_cam": tilt.round(1).tolist(), "floor_h": float(floor_h), "ceil_h": float(ceil_h),
       "scale_from_ceiling_units_per_m": float(unit_per_m), "camera_heights_m_if_ceiling_2.6": cam_h_m.round(2).tolist()}

# --- OWLv2 detection of windows/doors on each image ---
from transformers import Owlv2Processor, Owlv2ForObjectDetection
proc = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
det = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").eval()
queries = [["a window", "a door", "a glass door"]]
THR = 0.12
dets = []
for i in range(S):
    im = Image.fromarray(rgb[i])
    inp = proc(text=queries, images=im, return_tensors="pt")
    with torch.no_grad():
        o = det(**inp)
    m = max(im.size)
    r = proc.post_process_grounded_object_detection(o, threshold=THR, target_sizes=torch.tensor([[m, m]]), text_labels=queries)[0]
    for b, s, l in zip(r["boxes"], r["scores"], r["labels"]):
        x0, y0, x1, y1 = [float(v) for v in b]
        x0, x1 = np.clip([x0, x1], 0, W - 1); y0, y1 = np.clip([y0, y1], 0, H - 1)
        if (x1 - x0) < 15 or (y1 - y0) < 15: continue
        dets.append({"img": i, "label": ["window", "door", "glass door"][int(l)], "score": float(s), "box": [x0, y0, x1, y1]})

def ring_pts(i, box, margin=6, width=8):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    m = np.zeros((H, W), bool)
    X0, Y0, X1, Y1 = max(x0 - margin - width, 0), max(y0 - margin - width, 0), min(x1 + margin + width, W - 1), min(y1 + margin + width, H - 1)
    m[Y0:Y1 + 1, X0:X1 + 1] = True
    m[max(y0 - margin, 0):min(y1 + margin, H - 1) + 1, max(x0 - margin, 0):min(x1 + margin, W - 1) + 1] = False
    m &= conf[i] > 1.5
    return R[i][m], m

objs = []
for dd in dets:
    i, box = dd["img"], dd["box"]
    P, m = ring_pts(i, box)
    if len(P) < 50: continue
    c = np.median(P, 0)
    Q = P - c; _, _, vt = np.linalg.svd(Q[np.random.default_rng(0).choice(len(Q), min(len(Q), 2000), replace=False)], full_matrices=False)
    nrm = vt[2]
    camr = to_room(cams[i])
    if nrm @ (c - camr) < 0: nrm = -nrm  # outward = away from camera
    # size: unproject box edges using ring depth -> use the span of ring points along wall axes
    horiz = np.cross(nrm, [0, 1, 0]); horiz /= (np.linalg.norm(horiz) + 1e-9)
    # pixels on left/right/top/bottom rings
    x0, y0, x1, y1 = box
    ys, xs = np.nonzero(m)
    left = R[i][ys[xs < x0], xs[xs < x0]]; right = R[i][ys[xs > x1], xs[xs > x1]]
    top = R[i][ys[ys < y0], xs[ys < y0]]; bot = R[i][ys[ys > y1], xs[ys > y1]]
    def med(a, axis): return np.median(a @ axis) if len(a) > 5 else np.nan
    w_units = med(right, horiz) - med(left, horiz); h_units = med(top, np.array([0, 1, 0])) - med(bot, np.array([0, 1, 0]))
    verticality = float(np.degrees(np.arccos(abs(nrm[1]))))  # 90 = wall normal horizontal (vertical surface)
    objs.append({**dd, "center": c.round(3).tolist(), "normal": nrm.round(3).tolist(),
                 "facing_deg": float(np.degrees(np.arctan2(nrm[2], nrm[0])) % 360), "normal_horizontality_deg": round(verticality, 1),
                 "width_m": float(abs(w_units) / unit_per_m) if np.isfinite(w_units) else None,
                 "height_m": float(abs(h_units) / unit_per_m) if np.isfinite(h_units) else None,
                 "sill_m": float((med(bot, np.array([0, 1, 0])) - floor_h) / unit_per_m) if len(bot) > 5 else None})

doors = [o for o in objs if o["label"] == "door" and o["height_m"]]
res["door_heights_m_if_ceiling_2.6"] = [round(o["height_m"], 2) for o in doors]
res["windows"] = [{k: o[k] for k in ("img", "score", "center", "facing_deg", "normal_horizontality_deg", "width_m", "height_m", "sill_m")} for o in objs if o["label"] != "door"]
res["n_window_dets"] = len(res["windows"]); res["n_door_dets"] = len(doors)
(out / "analysis.json").write_text(json.dumps(res, indent=1))

# --- renders: gravity-aligned top-down with windows; detections on images ---
pts = R[good]; cols = rgb[good] / 255.0
sub = np.random.default_rng(0).choice(len(pts), min(len(pts), 300000), replace=False); pts, cols = pts[sub], cols[sub]
lo, hi = np.quantile(pts, 0.02, 0), np.quantile(pts, 0.98, 0); k = np.all((pts > lo) & (pts < hi), 1); pts, cols = pts[k], cols[k]
fig, axs = plt.subplots(1, 2, figsize=(20, 10))
for ax, sel, title in ((axs[0], slice(None), "top-down, gravity aligned (all)"),
                       (axs[1], (pts[:, 1] > floor_h + 0.3 * (ceil_h - floor_h)) & (pts[:, 1] < floor_h + 0.9 * (ceil_h - floor_h)), "top-down, wall band 30-90% height")):
    ax.scatter(pts[sel, 0], pts[sel, 2], s=0.3, c=cols[sel], marker=","); ax.set_facecolor("black"); ax.set_aspect("equal"); ax.set_title(title)
    cr = to_room(cams); ax.scatter(cr[:, 0], cr[:, 2], s=70, c="red", marker="^", edgecolors="white", zorder=5)
    for i, (x, _, z) in enumerate(cr): ax.annotate(str(i), (x, z), color="yellow", fontsize=10)
    for o in objs:
        c = np.array(o["center"]); nn = np.array(o["normal"]); colr = "cyan" if o["label"] != "door" else "magenta"
        ax.scatter(c[0], c[2], s=80, c=colr, marker="s", zorder=6)
        ax.arrow(c[0], c[2], nn[0] * 0.3, nn[2] * 0.3, color=colr, width=0.01, zorder=6)
    # 1 m scale bar
    ax.plot([lo[0], lo[0] + unit_per_m], [lo[2], lo[2]], c="white", lw=3); ax.annotate("1 m (ceiling=2.6 m)", (lo[0], lo[2]), color="white")
plt.tight_layout(); plt.savefig(out / "topdown.png", dpi=70); plt.close()

cols_n = min(S, 6); rows_n = int(np.ceil(S / cols_n))
fig, axs = plt.subplots(rows_n, cols_n, figsize=(3.4 * cols_n, 2.7 * rows_n), squeeze=False)
for i in range(rows_n * cols_n):
    ax = axs[divmod(i, cols_n)]; ax.axis("off")
    if i < S:
        ax.imshow(rgb[i]); ax.set_title(f"{i} cam_h={cam_h_m[i]:.2f}m", fontsize=8)
        for o in objs:
            if o["img"] != i: continue
            x0, y0, x1, y1 = o["box"]; colr = "cyan" if o["label"] != "door" else "magenta"
            ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, color=colr, lw=1.5))
            lab = f"{o['label'][0]} {o['score']:.2f} {o['width_m'] or 0:.1f}x{o['height_m'] or 0:.1f}m {o['facing_deg']:.0f}°"
            ax.text(x0, y0 - 2, lab, color=colr, fontsize=6)
plt.tight_layout(); plt.savefig(out / "detections.png", dpi=80); plt.close()
print(json.dumps({k: res[k] for k in ("tilt_deg_per_cam", "camera_heights_m_if_ceiling_2.6", "door_heights_m_if_ceiling_2.6", "n_window_dets")}))
print("windows:", [(w["img"], round(w["facing_deg"]), w["normal_horizontality_deg"], w["width_m"] and round(w["width_m"], 2), w["height_m"] and round(w["height_m"], 2)) for w in res["windows"]])
print("ANALYZE_DONE")
