"""Phase 3, general walls: analysis-by-synthesis room fit. Parameters: per-edge line (normal angle phi, offset o), per-camera
pose deltas. Vertices are consecutive-line intersections, so the polygon stays closed by construction.
Render = closed-form ray/plane depth for floor, ceiling and wall segments; first hit = min over candidates."""
import numpy as np, torch
from geometry import FLOOR, CEIL, WALL

def so3_exp(w):
    th = torch.linalg.norm(w, dim=-1, keepdim=True).clamp_min(1e-9); k = w / th
    K = torch.zeros(w.shape[0], 3, 3, dtype=w.dtype); K[:, 0, 1], K[:, 0, 2], K[:, 1, 0], K[:, 1, 2], K[:, 2, 0], K[:, 2, 1] = -k[:, 2], k[:, 1], k[:, 2], -k[:, 0], -k[:, 1], k[:, 0]
    th = th[..., None]; return torch.eye(3, dtype=w.dtype)[None] + torch.sin(th) * K + (1 - torch.cos(th)) * (K @ K)

class RoomFit:
    def __init__(self, room, P, V, stride=4, door_boxes=None, edges=None):
        self.room, self.P = room, P; S, H, W = room["labels"].shape; self.S = S
        V = np.asarray(V, float); n = len(V); cen = V.mean(0)
        phi, off, inferred = [], [], []
        for k in range(n):
            a, b = V[k], V[(k + 1) % n]; d = b - a; d /= max(np.linalg.norm(d), 1e-9); nn = np.array([d[1], -d[0]])
            if nn @ ((a + b) / 2 - cen) < 0: nn = -nn
            phi.append(np.arctan2(nn[1], nn[0])); off.append(nn @ a); inferred.append(bool(edges[k]["inferred"]) if edges else False)
        self.phi0 = torch.tensor(phi, dtype=torch.float64); self.off0 = torch.tensor(off, dtype=torch.float64); self.inferred = torch.tensor(inferred)
        self.h = float(room["ceil_m"])
        cb = room["cam_basis"]; self.c0 = torch.tensor([c["pos"] for c in cb], dtype=torch.float64)
        self.R0 = torch.tensor([[c["right"], c["up"], c["fwd"]] for c in cb], dtype=torch.float64)
        vs, us = np.mgrid[0:H:stride, 0:W:stride]; self.us, self.vs = us.ravel(), vs.ravel()
        K = P["intrinsic"]; self.dirs_cam, self.r_obs, self.lab, self.good = [], [], [], []
        for i in range(S):
            x = (self.us - K[i][0, 2]) / K[i][0, 0]; y = (self.vs - K[i][1, 2]) / K[i][1, 1]; dc = np.stack([x, -y, np.ones_like(x)], -1)
            z = P["depth"][i][self.vs, self.us].reshape(-1); r = z * np.linalg.norm(dc, axis=1) / room["stats"]["scale_units_per_m"]
            self.dirs_cam.append(torch.tensor(dc / np.linalg.norm(dc, axis=1, keepdims=True), dtype=torch.float64)); self.r_obs.append(torch.tensor(r, dtype=torch.float64))
            lab = room["labels"][i][self.vs, self.us].reshape(-1).copy(); g = room["good"][i][self.vs, self.us].reshape(-1).copy()
            for (ii, x0, y0, x1, y1) in (door_boxes or []):
                if ii == i: inside = (self.us >= x0) & (self.us <= x1) & (self.vs >= y0) & (self.vs <= y1); g[inside] = False; lab[inside] = 0
            self.lab.append(torch.tensor(lab)); self.good.append(torch.tensor(g))
        self.phi = self.phi0.clone().requires_grad_(True); self.off = self.off0.clone().requires_grad_(True); self.log_s = torch.zeros(1, dtype=torch.float64)
        self.dw = torch.zeros(S, 3, dtype=torch.float64, requires_grad=True); self.dc = torch.zeros(S, 3, dtype=torch.float64, requires_grad=True)
        self.off_lim = None   # per-edge max |offset change| (m); set by the caller when a VLM / plan dimension bounds the walls

    def poses(self): return so3_exp(self.dw) @ self.R0, self.c0 + self.dc
    def lines(self): return torch.stack([torch.cos(self.phi), torch.sin(self.phi)], 1), self.off   # normals (n,2) in xz, offsets
    def verts(self):
        N, O = self.lines(); n = len(O); V = []
        for k in range(n):
            A = torch.stack([N[k - 1], N[k]]); det = A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]
            det = torch.where(det.abs() < 1e-3, torch.sign(det) * 1e-3 + (det == 0) * 1e-3, det)
            b = torch.stack([O[k - 1], O[k]]); V.append(torch.stack([(b[0] * A[1, 1] - A[0, 1] * b[1]) / det, (A[0, 0] * b[1] - A[1, 0] * b[0]) / det]))
        return torch.stack(V)   # V[k] = start of edge k

    def render(self, i, R, c):
        d = self.dirs_cam[i] @ R[i]; N, O = self.lines(); V = self.verts(); n = len(O); cands = []
        t_f = -c[i, 1] / d[:, 1]; cands.append(torch.where(d[:, 1] < -1e-6, t_f, torch.full_like(t_f, 1e9)))
        t_c = (self.h - c[i, 1]) / d[:, 1]; cands.append(torch.where(d[:, 1] > 1e-6, t_c, torch.full_like(t_c, 1e9)))
        for k in range(n):
            n3 = torch.stack([N[k, 0], torch.zeros((), dtype=N.dtype), N[k, 1]]); dn = d @ n3
            t = (O[k] - c[i] @ n3) / torch.where(dn.abs() < 1e-6, torch.full_like(dn, 1e-6), dn); hpt = c[i] + t[:, None] * d
            a, b = V[k], V[(k + 1) % n]; seg = b - a; L = torch.linalg.norm(seg).clamp_min(1e-6); dirk = seg / L
            s = (hpt[:, 0] - a[0]) * dirk[0] + (hpt[:, 2] - a[1]) * dirk[1]
            ok = (t > 0.05) & (s >= -0.02) & (s <= L + 0.02) & (hpt[:, 1] >= -0.02) & (hpt[:, 1] <= self.h + 0.02)
            cands.append(torch.where(ok, t, torch.full_like(t, 1e9)))
        T = torch.stack(cands, 1); return T.min(1)

    def loss(self, w_depth=1.0, w_free=0.1, w_prior=0.05):
        R, c = self.poses(); L_d = 0; L_f = 0; n_d = 0; per_img = []
        for i in range(self.S):
            t, which = self.render(i, R, c); r = self.r_obs[i]; g = self.good[i] & (t < 1e8) & (r > 0.1); lab = self.lab[i]
            struct = g & ((lab == FLOOR) | (lab == CEIL) | (lab == WALL)); e = torch.log(t[struct]) - torch.log(r[struct])
            L_d = L_d + torch.nn.functional.huber_loss(e, torch.zeros_like(e), delta=0.05, reduction="sum"); n_d += int(struct.sum())
            L_f = L_f + torch.relu(torch.log(r[g]) - torch.log(t[g]) - 0.03).clamp_max(0.3).sum()
            per_img.append(float(e.abs().median()) if struct.sum() > 0 else float("nan"))
        n_d = max(n_d, 1)
        w_off = torch.where(self.inferred, 0.005, w_prior); w_phi = torch.where(self.inferred, 0.5, 4.0)
        prior = (w_off * (self.off - self.off0) ** 2).sum() + (w_phi * (self.phi - self.phi0) ** 2).sum() + 1.0 * (self.dw ** 2).sum() + 1.0 * (self.dc ** 2).sum()
        return w_depth * L_d / n_d + w_free * L_f / n_d + prior, {"depth_med_logerr": per_img, "free_viol": float(L_f / n_d), "scale": 1.0}

    def run(self, iters=300, lr=0.01, log_every=100):
        opt = torch.optim.Adam([{"params": [self.off], "lr": lr}, {"params": [self.phi], "lr": lr * 0.3}, {"params": [self.dw, self.dc], "lr": lr * 0.3}]); hist = []
        for it in range(iters):
            opt.zero_grad(); L, info = self.loss()
            if not torch.isfinite(L):
                with torch.no_grad(): self.off.copy_(self.off0); self.phi.copy_(self.phi0); self.dw.zero_(); self.dc.zero_()
                print("[fit] non-finite loss; reset to init and stop"); break
            L.backward(); opt.step()
            if self.off_lim is not None:
                with torch.no_grad(): self.off.copy_(torch.minimum(torch.maximum(self.off, self.off0 - self.off_lim), self.off0 + self.off_lim))
            if it % log_every == 0 or it == iters - 1:
                hist.append({"it": it, "loss": float(L), **info}); print(f"[fit] it {it:4d} loss {float(L):.4f} depth med log-err {np.nanmedian(info['depth_med_logerr']):.4f} free-viol {info['free_viol']:.4f}")
        return hist

    def polygon(self):
        with torch.no_grad():
            bad = ~torch.isfinite(self.off) | ~torch.isfinite(self.phi)
            if bad.any(): self.off[bad] = self.off0[bad]; self.phi[bad] = self.phi0[bad]
            return self.verts().numpy()

    def apply(self):
        R, c = self.poses(); R = R.detach().numpy(); c = c.detach().numpy(); room, P = self.room, self.P
        S, H, W = room["labels"].shape; K = P["intrinsic"]; vs, us = np.mgrid[0:H, 0:W]
        import geometry as G
        for i in range(S):
            x = (us - K[i][0, 2]) / K[i][0, 0]; y = (vs - K[i][1, 2]) / K[i][1, 1]; _, zs = G.smoothed_points(P, i)
            dc = np.stack([x * zs, -y * zs, zs], -1) / room["stats"]["scale_units_per_m"]
            pts = c[i] + dc @ R[i]; room["pts"][i] = pts.astype(np.float32); room["normals"][i] = G.normals(room["pts"][i], c[i])
            room["cam_basis"][i].update({"pos": c[i].round(4).tolist(), "right": R[i][0].round(4).tolist(), "up": R[i][1].round(4).tolist(), "fwd": R[i][2].round(4).tolist()})
        room["cams"] = c.astype(np.float64)
        up_dot = room["normals"][..., 1]; good = room["good"]; ptsy = room["pts"][..., 1]; lab = np.zeros_like(room["labels"])
        lab[good & (up_dot > 0.85) & (np.abs(ptsy) < 0.25)] = FLOOR; lab[good & (up_dot < -0.85) & (np.abs(ptsy - self.h) < 0.3)] = CEIL; lab[good & (np.abs(up_dot) < 0.35)] = WALL
        room["labels"] = lab; room["stats"]["cam_heights_m"] = c[:, 1].round(3).tolist()
        return room

def see_through_openings(rf, ratio=1.6, min_w=0.6, min_h=1.2):
    """Pixels whose observed depth is far beyond the fitted wall are passages; cluster them per edge into rectangles."""
    import cv2
    R, c = rf.poses(); R = R.detach(); c = c.detach()
    with torch.no_grad(): V = rf.verts().numpy(); N, O = rf.lines(); N = N.numpy(); O = O.numpy()
    n = len(O); openings = []; masks = []
    for i in range(rf.S):
        with torch.no_grad(): t, which = rf.render(i, R, c)
        r = rf.r_obs[i]; g = rf.good[i] & (t < 1e8); thr = (r > ratio * t) & g & (which >= 2); m = thr.numpy(); masks.append(m)
        if m.sum() < 30: continue
        d = (rf.dirs_cam[i] @ R[i]).numpy(); hit = c[i].numpy() + t.numpy()[:, None] * d; wk = which.numpy() - 2
        for k in np.unique(wk[m]):
            sel = m & (wk == k); a, b = V[k], V[(k + 1) % n]; seg = b - a; L = max(np.linalg.norm(seg), 1e-6); dirk = seg / L
            along = (hit[sel][:, 0] - a[0]) * dirk[0] + (hit[sel][:, 2] - a[1]) * dirk[1]; hgt = hit[sel][:, 1]
            nx = max(2, int(L / 0.1)); ny = max(2, int(rf.h / 0.1)); img = np.zeros((ny, nx), np.uint8)
            u = np.clip((along / 0.1).astype(int), 0, nx - 1); v = np.clip((hgt / 0.1).astype(int), 0, ny - 1); img[v, u] = 1
            img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)); nl, lab, st, _ = cv2.connectedComponentsWithStats(img)
            for j in range(1, nl):
                x, y, w, h, area = st[j]
                if w * 0.1 >= min_w and h * 0.1 >= min_h and area >= 0.5 * w * h:
                    s_a, s_b = x * 0.1, (x + w) * 0.1; cxz = a + dirk * (s_a + s_b) / 2
                    openings.append({"kind": "passage", "edge": int(k), "img": i, "center": [round(float(cxz[0]), 3), round(float((y + h / 2) * 0.1), 3), round(float(cxz[1]), 3)], "normal": [float(N[k, 0]), 0.0, float(N[k, 1])],
                                     "width_m": round(w * 0.1, 2), "height_m": round(h * 0.1, 2), "sill_m": round(y * 0.1, 2), "s0": float(s_a), "s1": float(s_b), "score": 1.0})
    return openings, masks

def fit_two_pass(rf, iters=300):
    rf.run(iters=iters, log_every=iters)
    passages, masks = see_through_openings(rf)
    if passages:
        for i, m in enumerate(masks): rf.good[i] = rf.good[i] & ~torch.tensor(m); rf.lab[i][torch.tensor(m)] = 0
        print(f"[fit] {len(passages)} see-through passages masked; refitting"); rf.run(iters=iters // 2, log_every=iters)
    return passages
