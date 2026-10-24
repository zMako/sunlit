"""Cross-view consistency: project confident points of image i into camera j, compare to j's predicted depth."""
import sys, json, pathlib, numpy as np
out = pathlib.Path(sys.argv[1]); d = np.load(out / "pred.npz")
wp, conf, extr, intr = d["world_points"], d["conf"], d["extrinsic"], d["intrinsic"]
S, H, W = conf.shape
depth_j = np.linalg.norm(wp - 0, axis=-1)  # placeholder, replaced below per camera
M = np.full((S, S), np.nan); N = np.zeros((S, S), int)
for i in range(S):
    m = conf[i] > max(np.quantile(conf[i], 0.5), 1.5)
    P = wp[i][m]; P = P[np.random.default_rng(0).choice(len(P), min(len(P), 20000), replace=False)]
    Ph = np.c_[P, np.ones(len(P))]
    for j in range(S):
        if i == j: continue
        C = (extr[j] @ Ph.T).T  # cam coords
        z = C[:, 2]; ok = z > 1e-3
        uv = (intr[j] @ C[ok].T).T; u = uv[:, 0] / uv[:, 2]; v = uv[:, 1] / uv[:, 2]
        inb = (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1)
        if inb.sum() < 200: continue
        ui, vi = u[inb].astype(int), v[inb].astype(int)
        # depth of j at those pixels (z in cam j)
        Pj = np.c_[wp[j][vi, ui], np.ones(inb.sum())]; zj = (extr[j] @ Pj.T).T[:, 2]
        rel = (z[ok][inb] - zj) / np.maximum(zj, 1e-6)
        N[i, j] = inb.sum(); M[i, j] = float(np.mean(np.abs(rel) < 0.1))
pairs = [(i, j, int(N[i, j]), round(M[i, j], 2)) for i in range(S) for j in range(S) if N[i, j] >= 2000]
good_pairs = [p for p in pairs if p[3] >= 0.5]
print(f"{out.name}: {len(pairs)} overlapping pairs (>=2000 pts in view), {len(good_pairs)} consistent (>=50% within 10%); "
      f"median consistency {np.nanmedian([p[3] for p in pairs]) if pairs else float('nan'):.2f}")
# per-image: best consistency with any other image
best = [max([M[i, j] for j in range(S) if N[i, j] >= 2000] or [0]) for i in range(S)]
print("per-image best pairwise consistency:", np.round(best, 2).tolist())
json.dump({"pairs": pairs, "best": best}, open(out / "regcheck.json", "w"))
