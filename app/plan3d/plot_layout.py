"""2D debug plot of a layout JSON: rooms (tinted, named), walls (grey), openings (window blue, door red), fixtures (orange)."""
import sys, json, pathlib
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt; from matplotlib.patches import Polygon as MP, Rectangle
L = json.load(open(sys.argv[1])); out = sys.argv[2]
fig, ax = plt.subplots(figsize=(9, 7)); cols = plt.cm.Pastel1.colors
for k, r in enumerate(L["rooms"]):
    ax.add_patch(MP(r["polygon"], closed=True, fc=cols[k % len(cols)], ec="none", alpha=0.8)); cx = sum(p[0] for p in r["polygon"]) / len(r["polygon"]); cz = sum(p[1] for p in r["polygon"]) / len(r["polygon"])
    ax.text(cx, cz, f"{r['name']}\n{r['area_m2']} m²", ha="center", va="center", fontsize=7)
for w in L["walls"]:
    ax.plot([w["a"][0], w["b"][0]], [w["a"][1], w["b"][1]], color="0.2", lw=max(1, w["thickness_m"] * 25), solid_capstyle="butt", alpha=0.9)
wid = {w["id"]: w for w in L["walls"]}
for o in L["openings"]:
    w = wid[o["wall"]]; ax_, bx_ = w["a"], w["b"]; L_ = max(((bx_[0] - ax_[0]) ** 2 + (bx_[1] - ax_[1]) ** 2) ** 0.5, 1e-6); ux, uz = (bx_[0] - ax_[0]) / L_, (bx_[1] - ax_[1]) / L_
    p0 = (ax_[0] + ux * o["s0"], ax_[1] + uz * o["s0"]); p1 = (ax_[0] + ux * o["s1"], ax_[1] + uz * o["s1"])
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color={"window": "dodgerblue", "door": "red"}.get(o["type"], "cyan"), lw=4, solid_capstyle="butt")
for f in L["fixtures"]:
    r = f["rect"]; ax.add_patch(Rectangle((r["x"] - r["w"] / 2, r["z"] - r["d"] / 2), r["w"], r["d"], fc="orange", ec="darkorange", alpha=0.7)); ax.text(r["x"], r["z"], f["type"], fontsize=6, ha="center", va="center")
ax.set_aspect("equal"); ax.invert_yaxis(); ax.autoscale(); ax.set_title(f"{L['unit']}  scale {L['scale']['m_per_px']} m/px ({', '.join(L['scale']['from'])})", fontsize=9); ax.grid(alpha=0.2)
plt.tight_layout(); plt.savefig(out, dpi=110); print(out)
