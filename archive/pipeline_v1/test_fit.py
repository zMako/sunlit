"""Phase 3 test: restart stability. Perturb edge offsets (+-0.2 m) and poses, refit, compare final offsets."""
import sys, json, pathlib, numpy as np, torch, recon, geometry, layout, fit as F
d = pathlib.Path(sys.argv[1]); which = sys.argv[2]; ceil_m = float(sys.argv[3]); n_restart = 3
paths = recon.filter_photos(sorted(str(p) for p in d.glob("*.jpg"))); cl = json.load(open(d / "clusters.json"))[int(which)]; sel = [str(d / n) for n in cl["images"]]
P = recon.run(sel); room0 = geometry.clean_room(P, ceil_m=ceil_m); carved = layout.carve(room0); V = layout.rectilinear_polygon(carved["region"], carved["lo"], planes=room0["planes"])
finals = []; errs = []
for r in range(n_restart):
    room = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in room0.items()}; room["cam_basis"] = [dict(c) for c in room0["cam_basis"]]
    rf = F.RoomFit(room, P, V, stride=4); rng = np.random.default_rng(r)
    if r > 0:
        with torch.no_grad(): rf.off += torch.tensor(rng.uniform(-0.2, 0.2, len(rf.off))); rf.dw += torch.tensor(rng.normal(0, 0.01, rf.dw.shape)); rf.dc += torch.tensor(rng.normal(0, 0.03, rf.dc.shape))
    F.fit_two_pass(rf, iters=300); L, info = rf.loss(); finals.append(rf.off.detach().numpy().copy()); errs.append(np.nanmedian(info["depth_med_logerr"]))
    print(f"[test] restart {r}: offsets {np.round(finals[-1], 2).tolist()} depth med log-err {errs[-1]:.3f}")
F_ = np.array(finals); spread = F_.max(0) - F_.min(0)
print(f"[test] offset spread across restarts: {np.round(spread, 2).tolist()} m, max {spread.max():.2f} m; depth errs {np.round(errs, 3).tolist()}")
print("[test] PASS" if spread.max() < 0.15 else "[test] FAIL: unstable edges")
