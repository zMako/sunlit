"""Export a VGGT room as a metric, gravity-aligned PLY point cloud + JSON (cameras, windows) for the three.js viewer."""
import sys, json, pathlib, numpy as np, struct
src = pathlib.Path(sys.argv[1]); dst = pathlib.Path(sys.argv[2]); name = sys.argv[3]; CEIL_M = float(sys.argv[4]) if len(sys.argv) > 4 else 2.6
d = np.load(src / "pred.npz"); a = json.load(open(src / "analysis.json"))
wp, conf, rgb, extr, cams = d["world_points"], d["conf"], d["rgb"], d["extrinsic"], d["cam_centers"]
S = conf.shape[0]
down = extr[:, 1, :3]; down /= np.linalg.norm(down, axis=1, keepdims=True); g = down.mean(0); g /= np.linalg.norm(g); up = -g
ex = np.cross(up, extr[0, 2, :3]); ex /= np.linalg.norm(ex); ez = np.cross(ex, up)
def to_room(p): return np.stack([p @ ex, p @ up, p @ ez], -1)
floor_h, ceil_h = a["floor_h"], a["ceil_h"]; upm = (ceil_h - floor_h) / CEIL_M
def metric(p): q = to_room(np.asarray(p)); q[..., 1] -= floor_h; return q / upm
good = conf > max(np.quantile(conf, 0.4), 1.5)
P = metric(wp)[good]; C = rgb[good]
# drop outliers far from the bulk
lo, hi = np.quantile(P, 0.01, 0), np.quantile(P, 0.99, 0); k = np.all((P > lo - 1) & (P < hi + 1), 1); P, C = P[k], C[k]
if len(P) > 600000:
    s = np.random.default_rng(0).choice(len(P), 600000, replace=False); P, C = P[s], C[s]
# PLY binary little endian: x y z (float32), r g b (uint8)
with open(dst / f"{name}.ply", "wb") as f:
    f.write(f"ply\nformat binary_little_endian 1.0\nelement vertex {len(P)}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n".encode())
    buf = np.zeros(len(P), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    buf["x"], buf["y"], buf["z"] = P[:, 0], P[:, 1], P[:, 2]; buf["r"], buf["g"], buf["b"] = C[:, 0], C[:, 1], C[:, 2]
    f.write(buf.tobytes())
# cameras: position + forward dir in metric room frame
camsm = metric(cams); fwd = np.stack([to_room(extr[i, 2, :3]) for i in range(S)]); fwd /= np.linalg.norm(fwd, axis=1, keepdims=True)
# windows: filter plausible sizes, dedupe by center distance
wins = []
for w in a["windows"]:
    if not (w["width_m"] and w["height_m"]): continue
    if not (0.5 <= w["width_m"] <= 3.5 and 0.5 <= w["height_m"] <= 3.0 and w["normal_horizontality_deg"] >= 75): continue
    c = (np.array(w["center"]) - np.array([0, floor_h, 0])) / upm
    if any(np.linalg.norm(c - np.array(v["center"])) < 0.5 for v in wins): continue
    fa = np.radians(w["facing_deg"]); n = [float(np.cos(fa)), 0.0, float(np.sin(fa))]
    wins.append({"center": c.round(3).tolist(), "normal": n, "width_m": round(w["width_m"], 2), "height_m": round(w["height_m"], 2),
                 "sill_m": round(w["sill_m"], 2) if w["sill_m"] else None, "img": w["img"], "score": round(w["score"], 2)})
json.dump({"name": name, "n_points": len(P), "ceiling_m": CEIL_M, "cameras": [{"pos": camsm[i].round(3).tolist(), "fwd": fwd[i].round(3).tolist()} for i in range(S)],
           "windows": wins, "bounds": [lo.round(2).tolist(), hi.round(2).tolist()]}, open(dst / f"{name}.json", "w"))
print(f"{name}: {len(P)} pts, {S} cams, {len(wins)} windows (of {len(a['windows'])} dets), bounds x {lo[0]:.1f}..{hi[0]:.1f} z {lo[2]:.1f}..{hi[2]:.1f}")
