"""Contact sheet of models (front view x-y, vertices) to eyeball orientation/scale: contact.py out.png id1 id2 ... (ids from models/)"""
import sys, pathlib, trimesh, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
H = pathlib.Path(__file__).resolve().parent
out, ids = sys.argv[1], sys.argv[2:]
n = len(ids); c = min(n, 6); r = (n + c - 1) // c
fig, ax = plt.subplots(r, c, figsize=(3 * c, 3 * r), squeeze=False)
for a in ax.flat: a.axis("off")
for k, i in enumerate(ids):
    a = ax.flat[k]
    try:
        sc = trimesh.load(str(H / "models" / f"{i}.glb"), force="scene"); v = np.vstack([g.vertices for g in sc.geometry.values()]) if False else sc.dump(concatenate=True).vertices
        v = v[np.random.RandomState(0).choice(len(v), min(len(v), 6000), replace=False)]
        a.scatter(v[:, 0], v[:, 1], s=0.3, c="k"); a.plot([-1, 1], [0, 0], "r-", lw=.5); a.set_xlim(-1.2, 1.2); a.set_ylim(-0.1, 2.3); a.set_aspect("equal")
        a.set_title(i.replace("dsg-", "")[:28] + f"\n{sc.extents[0]:.2f}x{sc.extents[2]:.2f}x{sc.extents[1]:.2f}", fontsize=6)
    except Exception as e: a.set_title(str(e)[:30], fontsize=6)
plt.tight_layout(); plt.savefig(out, dpi=80)
