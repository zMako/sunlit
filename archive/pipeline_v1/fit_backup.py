"""Phase 3: analysis-by-synthesis room fit. Parameters: wall-edge offsets, metric scale, per-camera pose deltas.
Render = closed-form ray/plane depth for floor, ceiling and axis-aligned wall segments; first hit = min over candidates.
Losses: depth agreement on floor/ceiling/wall pixels, free-space hinge on all pixels, weak priors."""
import numpy as np, torch
from geometry import FLOOR, CEIL, WALL

def so3_exp(w):
    th = torch.linalg.norm(w, dim=-1, keepdim=True).clamp_min(1e-9); k = w / th
    K = torch.zeros(w.shape[0], 3, 3, dtype=w.dtype); K[:, 0, 1], K[:, 0, 2], K[:, 1, 0], K[:, 1, 2], K[:, 2, 0], K[:, 2, 1] = -k[:, 2], k[:, 1], k[:, 2], -k[:, 0], -k[:, 1], k[:, 0]
    th = th[..., None]; return torch.eye(3, dtype=w.dtype)[None] + torch.sin(th) * K + (1 - torch.cos(th)) * (K @ K)

class RoomFit:
    def __init__(self, room, P, V, stride=4, door_boxes=None):
        self.room, self.P = room, P; S, H, W = room["labels"].shape; self.S = S
        self.V0 = np.asarray(V, float); n = len(V)
        # edges: axis (0: x=const, 2: z=const) and initial offsets; neighbours give extents
        self.axis = []; off = []
        for k in range(n):
            a, b = self.V0[k], self.V0[(k + 1) % n]
            self.axis.append(0 if abs(a[0] - b[0]) < 1e-6 else 2); off.append(a[0] if self.axis[-1] == 0 else a[1])
        self.axis = np.array(self.axis); self.off0 = torch.tensor(off, dtype=torch.float64)
        self.h = float(room["ceil_m"])
        # per-camera basis (room frame) and intrinsics
        cb = room["cam_basis"]; self.c0 = torch.tensor([c["pos"] for c in cb], dtype=torch.float64)
        self.R0 = torch.tensor([[c["right"], c["up"], c["fwd"]] for c in cb], dtype=torch.float64)  # rows: right, up, fwd
        vs, us = np.mgrid[0:H:stride, 0:W:stride]; self.us, self.vs = us.ravel(), vs.ravel()
        K = P["intrinsic"]; self.dirs_cam = []; self.r_obs = []; self.lab = []; self.good = []
        for i in range(S):
            x = (self.us - K[i][0, 2]) / K[i][0, 0]; y = (self.vs - K[i][1, 2]) / K[i][1, 1]
            dc = np.stack([x, -y, np.ones_like(x)], -1)  # camera: right, up(-y), fwd
            z = P["depth"][i][self.vs, self.us].reshape(-1); r = z * np.linalg.norm(dc, axis=1) * room["stats"]["scale_units_per_m"] ** -1
            self.dirs_cam.append(torch.tensor(dc / np.linalg.norm(dc, axis=1, keepdims=True), dtype=torch.float64)); self.r_obs.append(torch.tensor(r, dtype=torch.float64))
            lab = room["labels"][i][self.vs, self.us].reshape(-1).copy(); g = room["good"][i][self.vs, self.us].reshape(-1).copy()
            if door_boxes:
                for (ii, x0, y0, x1, y1) in door_boxes:
                    if ii == i: inside = (self.us >= x0) & (self.us <= x1) & (self.vs >= y0) & (self.vs <= y1); g[inside] = False; lab[inside] = 0
            self.lab.append(torch.tensor(lab)); self.good.append(torch.tensor(g))
        # params
        self.off = self.off0.clone().requires_grad_(True); self.log_s = torch.zeros(1, dtype=torch.float64)  # scale is anchored by the fixed ceiling; not optimised
        self.dw = torch.zeros(S, 3, dtype=torch.float64, requires_grad=True); self.dc = torch.zeros(S, 3, dtype=torch.float64, requires_grad=True)

    def poses(self):
        Rd = so3_exp(self.dw); R = Rd @ self.R0  # rows still right/up/fwd after small rotation
        return R, self.c0 + self.dc

    def extents(self):
        n = len(self.off); lo = torch.empty(n, dtype=torch.float64); hi = torch.empty(n, dtype=torch.float64)
        for k in range(n):
            a, b = self.off[(k - 1) % n], self.off[(k + 1) % n]; lo[k] = torch.minimum(a, b); hi[k] = torch.maximum(a, b)
        return lo, hi

    def render(self, i, R, c):
        d = self.dirs_cam[i] @ R[i]  # (N,3) room-frame unit rays
        cands = []
        t_f = -c[i, 1] / d[:, 1]; cands.append(torch.where(d[:, 1] < -1e-6, t_f, torch.full_like(t_f, 1e9)))
        t_c = (self.h - c[i, 1]) / d[:, 1]; cands.append(torch.where(d[:, 1] > 1e-6, t_c, torch.full_like(t_c, 1e9)))
        lo, hi = self.extents()
        for k in range(len(self.off)):
            a = int(self.axis[k]); b = 2 - a; da = d[:, a]
            t = (self.off[k] - c[i, a]) / torch.where(da.abs() < 1e-6, torch.full_like(da, 1e-6), da)
            hb = c[i, b] + t * d[:, b]; hy = c[i, 1] + t * d[:, 1]
            ok = (t > 0.05) & (hb >= lo[k] - 0.02) & (hb <= hi[k] + 0.02) & (hy >= -0.02) & (hy <= self.h + 0.02)
            cands.append(torch.where(ok, t, torch.full_like(t, 1e9)))
        T = torch.stack(cands, 1); tmin, which = T.min(1)
        return tmin, which

    def loss(self, w_depth=1.0, w_free=0.1, w_prior=0.05, verbose=False):
        R, c = self.poses(); s = torch.exp(self.log_s); L_d = 0; L_f = 0; n_d = 0; per_img = []
        for i in range(self.S):
            t, which = self.render(i, R, c); r = self.r_obs[i] * s; g = self.good[i] & (t < 1e8) & (r > 0.1)
            lab = self.lab[i]; struct = g & ((lab == FLOOR) | (lab == CEIL) | (lab == WALL))
            e = torch.log(t[struct]) - torch.log(r[struct]); L_d = L_d + torch.nn.functional.huber_loss(e, torch.zeros_like(e), delta=0.05, reduction="sum"); n_d += int(struct.sum())
            viol = torch.relu(torch.log(r[g]) - torch.log(t[g]) - 0.03).clamp_max(0.3); L_f = L_f + viol.sum()
            per_img.append(float(e.abs().median()) if struct.sum() > 0 else float("nan"))
        n_d = max(n_d, 1); prior = w_prior * ((self.off - self.off0) ** 2).sum() + 1.0 * (self.dw ** 2).sum() + 1.0 * (self.dc ** 2).sum()
        total = w_depth * L_d / n_d + w_free * L_f / n_d + prior
        return total, {"depth_med_logerr": per_img, "free_viol": float(L_f / n_d), "scale": float(s)}

    def run(self, iters=300, lr=0.01, log_every=100):
        opt = torch.optim.Adam([{"params": [self.off], "lr": lr}, {"params": [self.dw, self.dc], "lr": lr * 0.3}])
        hist = []
        for it in range(iters):
            opt.zero_grad(); L, info = self.loss(); L.backward(); opt.step()
            if not torch.isfinite(L):
                with torch.no_grad(): self.off.copy_(self.off0); self.dw.zero_(); self.dc.zero_()
                print("[fit] non-finite loss; reset to init and stop"); break
            if it % log_every == 0 or it == iters - 1:
                hist.append({"it": it, "loss": float(L), **info}); print(f"[fit] it {it:4d} loss {float(L):.4f} depth med log-err {np.nanmedian(info['depth_med_logerr']):.4f} free-viol {info['free_viol']:.4f} scale {info['scale']:.3f}")
        return hist

    def polygon(self):
        n = len(self.off); off = self.off.detach().numpy().copy(); bad = ~np.isfinite(off); off[bad] = self.off0.numpy()[bad]; V = []
        for k in range(n):
            e1a, e2a = self.axis[k], self.axis[(k + 1) % n]; o1, o2 = off[k], off[(k + 1) % n]
            V.append([o1 if e1a == 0 else o2, o1 if e1a == 2 else o2])
        return np.array(V)

    def apply(self):
        """Rebuild room points, cameras and basis from fitted poses and scale (in place)."""
        R, c = self.poses(); R = R.detach().numpy(); c = c.detach().numpy(); s = float(torch.exp(self.log_s)); room, P = self.room, self.P
        S, H, W = room["labels"].shape; K = P["intrinsic"]; vs, us = np.mgrid[0:H, 0:W]
        import geometry as G
        for i in range(S):
            x = (us - K[i][0, 2]) / K[i][0, 0]; y = (vs - K[i][1, 2]) / K[i][1, 1]
            # smoothed z from the room's existing points is lost; recompute from P depth with bilateral smoothing
            _, zs = G.smoothed_points(P, i)
            dc = np.stack([x * zs, -y * zs, zs], -1) * s / room["stats"]["scale_units_per_m"]  # metric camera coords (right, up, fwd)
            pts = c[i] + dc @ R[i]; room["pts"][i] = pts.astype(np.float32); room["normals"][i] = G.normals(room["pts"][i], c[i])
            room["cam_basis"][i].update({"pos": c[i].round(4).tolist(), "right": R[i][0].round(4).tolist(), "up": R[i][1].round(4).tolist(), "fwd": R[i][2].round(4).tolist()})
        room["cams"] = c.astype(np.float64)
        # relabel with fixed floor (0) and ceiling (h)
        up_dot = room["normals"][..., 1]; good = room["good"]; ptsy = room["pts"][..., 1]; lab = np.zeros_like(room["labels"])
        lab[good & (up_dot > 0.85) & (np.abs(ptsy) < 0.25)] = FLOOR; lab[good & (up_dot < -0.85) & (np.abs(ptsy - self.h) < 0.3)] = CEIL; lab[good & (np.abs(up_dot) < 0.35)] = WALL
        room["labels"] = lab; room["stats"]["cam_heights_m"] = c[:, 1].round(3).tolist(); room["stats"]["fit_scale"] = s
        return room

def see_through_openings(rf, ratio=1.6, min_w=0.6, min_h=1.2):
    """Pixels whose observed depth is far beyond the fitted wall are passages (doors, arches). Cluster them per edge
    into rectangles on the wall; return openings + a per-pixel mask (stride grid) to exclude from the loss."""
    import cv2
    R, c = rf.poses(); R = R.detach(); c = c.detach(); lo, hi = rf.extents(); lo = lo.detach().numpy(); hi = hi.detach().numpy()
    openings = []; masks = []
    for i in range(rf.S):
        with torch.no_grad(): t, which = rf.render(i, R, c)
        r = rf.r_obs[i]; g = rf.good[i] & (t < 1e8)
        thr = (r > ratio * t) & g & (which >= 2)  # hit a wall edge (index 2+) but observed much farther
        m = thr.numpy(); masks.append(m)
        if m.sum() < 30: continue
        d = (rf.dirs_cam[i] @ R[i]).numpy(); hit = c[i].numpy() + t.numpy()[:, None] * d
        wk = (which.numpy() - 2)
        for k in np.unique(wk[m]):
            sel = m & (wk == k); a = int(rf.axis[k]); b = 2 - a
            along = hit[sel][:, b]; hgt = hit[sel][:, 1]
            # rasterize on the wall at 10 cm, find connected blobs
            s0 = lo[k]; nx = max(2, int((hi[k] - lo[k]) / 0.1)); ny = max(2, int(rf.h / 0.1))
            img = np.zeros((ny, nx), np.uint8); u = np.clip(((along - s0) / 0.1).astype(int), 0, nx - 1); v = np.clip((hgt / 0.1).astype(int), 0, ny - 1); img[v, u] = 1
            img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)); n, lab, st, _ = cv2.connectedComponentsWithStats(img)
            for j in range(1, n):
                x, y, w, h, area = st[j]
                if w * 0.1 >= min_w and h * 0.1 >= min_h and area >= 0.5 * w * h:
                    off = float(rf.off[k]); s_a, s_b = s0 + x * 0.1, s0 + (x + w) * 0.1
                    center = [0, 0, 0]; center[a] = off; center[b] = (s_a + s_b) / 2; center[1] = (y + h / 2) * 0.1
                    openings.append({"kind": "passage", "edge": int(k), "img": i, "center": [round(v_, 3) for v_ in center], "normal": [1.0 if a == 0 else 0.0, 0.0, 1.0 if a == 2 else 0.0],
                                     "width_m": round(w * 0.1, 2), "height_m": round(h * 0.1, 2), "sill_m": round(y * 0.1, 2), "s0": float(s_a), "s1": float(s_b), "score": 1.0})
    return openings, masks

def fit_two_pass(rf, iters=300):
    rf.run(iters=iters, log_every=iters)
    passages, masks = see_through_openings(rf)
    if passages:
        for i, m in enumerate(masks):
            rf.good[i] = rf.good[i] & ~torch.tensor(m); rf.lab[i][torch.tensor(m)] = 0
        print(f"[fit] {len(passages)} see-through passages masked; refitting")
        rf.run(iters=iters // 2, log_every=iters)
    return passages
