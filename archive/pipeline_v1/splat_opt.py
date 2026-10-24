"""Step 7: Gaussian-splat optimisation in pure PyTorch (MPS). Tile-based differentiable rasteriser; initialised from the
pixel-aligned splats; optimises position, scale, rotation, opacity and colour against the room's photos."""
import sys, json, time, pathlib, numpy as np, torch, torch.nn.functional as F
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = "mps" if torch.backends.mps.is_available() else "cpu"
TILE = 16; KMAX = 6144; KCH = 192

def read_splat_ply(path):
    with open(path, "rb") as f:
        header = b""
        while not header.endswith(b"end_header\n"): header += f.readline()
        n = int([l for l in header.decode().splitlines() if l.startswith("element vertex")][0].split()[-1]); props = [l.split()[-1] for l in header.decode().splitlines() if l.startswith("property")]
        A = np.frombuffer(f.read(n * len(props) * 4), dtype=np.float32).reshape(n, len(props))
    col = {p: A[:, i] for i, p in enumerate(props)}
    return {"xyz": np.stack([col["x"], col["y"], col["z"]], 1), "fdc": np.stack([col["f_dc_0"], col["f_dc_1"], col["f_dc_2"]], 1), "opacity": col["opacity"],
            "scale": np.stack([col["scale_0"], col["scale_1"], col["scale_2"]], 1), "rot": np.stack([col["rot_0"], col["rot_1"], col["rot_2"], col["rot_3"]], 1)}

def write_splat_ply(path, g):
    n = len(g["xyz"]); A = np.c_[g["xyz"], np.zeros((n, 3), np.float32), g["fdc"], g["opacity"], g["scale"], g["rot"]].astype(np.float32)
    header = "ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % n + "".join(f"property float {k}\n" for k in ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]) + "end_header\n"
    with open(path, "wb") as f: f.write(header.encode()); f.write(A.tobytes())

def quat_to_rot(q):
    q = q / q.norm(dim=-1, keepdim=True); w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], 1).view(-1, 3, 3)

class Cam:
    def __init__(self, cb, K, W, H, scale=0.5):
        self.R = torch.tensor([cb["right"], [-v for v in cb["up"]], cb["fwd"]], dtype=torch.float32, device=DEV)  # rows: x right, y down, z fwd
        self.c = torch.tensor(cb["pos"], dtype=torch.float32, device=DEV); self.W, self.H = int(W * scale), int(H * scale)
        self.fx, self.fy, self.cx, self.cy = K[0, 0] * scale, K[1, 1] * scale, K[0, 2] * scale, K[1, 2] * scale

def render(cam, xyz, scale_log, rot, opacity_logit, rgb):
    """Returns image (H,W,3) and alpha (H,W). Differentiable."""
    pc = (xyz - cam.c) @ cam.R.T; z = pc[:, 2]
    vis = z > 0.1
    pc = pc[vis]; z = z[vis]; S = torch.exp(scale_log[vis]); Rm = quat_to_rot(rot[vis]); op = torch.sigmoid(opacity_logit[vis]); col = rgb[vis]
    u = cam.fx * pc[:, 0] / z + cam.cx; v = cam.fy * pc[:, 1] / z + cam.cy
    # 3D covariance -> 2D
    M = Rm * S[:, None, :]; Sig = M @ M.transpose(1, 2)
    J = torch.zeros(len(z), 2, 3, device=DEV); J[:, 0, 0] = cam.fx / z; J[:, 0, 2] = -cam.fx * pc[:, 0] / z ** 2; J[:, 1, 1] = cam.fy / z; J[:, 1, 2] = -cam.fy * pc[:, 1] / z ** 2
    T = J @ cam.R[None]; Sig2 = T @ Sig @ T.transpose(1, 2); Sig2 = Sig2 + 0.3 * torch.eye(2, device=DEV)[None]
    det = Sig2[:, 0, 0] * Sig2[:, 1, 1] - Sig2[:, 0, 1] ** 2; det = det.clamp_min(1e-6)
    inv = torch.stack([Sig2[:, 1, 1], -Sig2[:, 0, 1], -Sig2[:, 1, 0], Sig2[:, 0, 0]], 1).view(-1, 2, 2) / det[:, None, None]
    mid = 0.5 * (Sig2[:, 0, 0] + Sig2[:, 1, 1]); lam = mid + torch.sqrt((mid ** 2 - det).clamp_min(0.01)); rad = (3.0 * torch.sqrt(lam)).detach()
    inb = (u + rad > 0) & (u - rad < cam.W) & (v + rad > 0) & (v - rad < cam.H) & (rad < 60)
    idx = torch.nonzero(inb).squeeze(1); u, v, inv, op, col, z, rad = u[idx], v[idx], inv[idx], op[idx], col[idx], z[idx], rad[idx]
    # tile assignment (bbox, capped 3x3 tiles)
    nTx, nTy = (cam.W + TILE - 1) // TILE, (cam.H + TILE - 1) // TILE
    tx0 = ((u - rad) / TILE).floor().clamp(0, nTx - 1).long(); tx1 = ((u + rad) / TILE).floor().clamp(0, nTx - 1).long(); ty0 = ((v - rad) / TILE).floor().clamp(0, nTy - 1).long(); ty1 = ((v + rad) / TILE).floor().clamp(0, nTy - 1).long()
    tx1 = torch.minimum(tx1, tx0 + 2); ty1 = torch.minimum(ty1, ty0 + 2)
    pairs_t, pairs_g = [], []
    for dy in range(3):
        for dx in range(3):
            tx = tx0 + dx; ty = ty0 + dy; ok = (tx <= tx1) & (ty <= ty1)
            pairs_t.append((ty * nTx + tx)[ok]); pairs_g.append(torch.nonzero(ok).squeeze(1))
    pt = torch.cat(pairs_t); pg = torch.cat(pairs_g)
    # sort by tile then depth (depth key quantised to keep it a single sort)
    key = pt.float() * 10000.0 + z[pg].clamp(0, 99) * 100.0; order = torch.argsort(key); pt, pg = pt[order], pg[order]
    # rank within tile; keep first KMAX
    counts = torch.bincount(pt, minlength=nTx * nTy); starts = torch.cumsum(counts, 0) - counts; rank = torch.arange(len(pt), device=DEV) - starts[pt]
    keep = rank < KMAX; pt, pg, rank = pt[keep], pg[keep], rank[keep]
    nT = nTx * nTy; K = min(KMAX, int(rank.max().item()) + 1) if len(rank) else 1
    # padded gather tensors [nT, K]
    def pad(x, fill):
        out = torch.full((nT, K) + tuple(x.shape[1:]), fill, device=DEV, dtype=x.dtype); out[pt, rank] = x[pg]; return out
    U, Vv, Op, Col = pad(u, -1e4), pad(v, -1e4), pad(op, 0.0), pad(col, 0.0); Inv = pad(inv.reshape(-1, 4), 0.0)
    # pixel grid per tile
    ty_idx = torch.arange(nT, device=DEV) // nTx; tx_idx = torch.arange(nT, device=DEV) % nTx
    py, px = torch.meshgrid(torch.arange(TILE, device=DEV), torch.arange(TILE, device=DEV), indexing="ij")
    PX = (tx_idx[:, None] * TILE + px.reshape(1, -1)).float() + 0.5; PY = (ty_idx[:, None] * TILE + py.reshape(1, -1)).float() + 0.5   # [nT, P]
    img = torch.zeros(nT, TILE * TILE, 3, device=DEV); alpha_acc = torch.zeros(nT, TILE * TILE, device=DEV)
    B = 64
    for s in range(0, nT, B):
        sl = slice(s, s + B); Trun = torch.ones(min(B, nT - s), TILE * TILE, device=DEV); acc = torch.zeros(min(B, nT - s), TILE * TILE, 3, device=DEV); aacc = torch.zeros(min(B, nT - s), TILE * TILE, device=DEV)
        for k0 in range(0, K, KCH):   # sequential depth chunks, transmittance carried across chunks: no per-tile cap
            ks = slice(k0, k0 + KCH)
            dx = PX[sl][:, None, :] - U[sl][:, ks, None]; dy = PY[sl][:, None, :] - Vv[sl][:, ks, None]   # [b, k, P]
            a, b_, c_, d_ = Inv[sl][:, ks, 0, None], Inv[sl][:, ks, 1, None], Inv[sl][:, ks, 2, None], Inv[sl][:, ks, 3, None]
            power = -0.5 * (a * dx * dx + (b_ + c_) * dx * dy + d_ * dy * dy)
            alpha = (Op[sl][:, ks, None] * torch.exp(power)).clamp(max=0.99); alpha = torch.where(power > 0, torch.zeros_like(alpha), alpha)
            Tr = torch.cumprod(1 - alpha + 1e-6, dim=1); Tprev = Trun[:, None, :] * torch.cat([torch.ones_like(Tr[:, :1]), Tr[:, :-1]], 1); w = alpha * Tprev
            acc = acc + (w[:, :, :, None] * Col[sl][:, ks, None, :]).sum(1); aacc = aacc + w.sum(1); Trun = Trun * Tr[:, -1]
        img[sl] = acc; alpha_acc[sl] = aacc
    # assemble tiles into image
    out = torch.zeros(nTy * TILE, nTx * TILE, 3, device=DEV); aout = torch.zeros(nTy * TILE, nTx * TILE, device=DEV)
    out = out.view(nTy, TILE, nTx, TILE, 3); out = img.view(nTy, nTx, TILE, TILE, 3).permute(0, 2, 1, 3, 4).reshape(nTy * TILE, nTx * TILE, 3)
    aout = alpha_acc.view(nTy, nTx, TILE, TILE).permute(0, 2, 1, 3).reshape(nTy * TILE, nTx * TILE)
    return out[:cam.H, :cam.W], aout[:cam.H, :cam.W]

def visible_counts(cams, xyz):
    """How many training cameras see each Gaussian (in front, inside the frame)."""
    cnt = torch.zeros(len(xyz), device=DEV)
    for cam in cams:
        pc = (xyz - cam.c) @ cam.R.T; z = pc[:, 2]; u = cam.fx * pc[:, 0] / z.clamp_min(1e-6) + cam.cx; v = cam.fy * pc[:, 1] / z.clamp_min(1e-6) + cam.cy
        cnt += ((z > 0.1) & (u >= 0) & (u < cam.W) & (v >= 0) & (v < cam.H)).float()
    return cnt

def optimise(room_name, iters=200, scale=0.5, lr_pos=0.0, log_every=25, max_g=150000, holdout=None, colour_prior=None):
    import os; colour_prior = float(os.environ.get("SPLAT_COLOUR_PRIOR", "2.0")) if colour_prior is None else colour_prior
    meta = json.load(open(ROOT / "rooms" / f"{room_name}.json")); g = read_splat_ply(ROOT / "rooms" / f"{room_name}.splat.ply")
    n = len(g["xyz"])
    if n > max_g: sel = np.random.default_rng(0).choice(n, max_g, replace=False); g = {k: v[sel] for k, v in g.items()}
    xyz = torch.tensor(g["xyz"], device=DEV, requires_grad=True); sc = torch.tensor(g["scale"], device=DEV, requires_grad=True); rot = torch.tensor(g["rot"], device=DEV, requires_grad=True)
    opl = torch.tensor(g["opacity"], device=DEV, requires_grad=True); rgb = torch.tensor(np.clip(g["fdc"] * 0.28209479 + 0.5, 0, 1), device=DEV, requires_grad=True)
    from PIL import Image
    photos = []; cams = []
    for i, cb in enumerate(meta["cameras"]):
        im = np.asarray(Image.open(ROOT / "rooms" / f"{room_name}_photos" / f"{i}.jpg").convert("RGB"))
        H0, W0 = im.shape[:2]; W, H = 518, int(round(H0 * 518 / W0 / 14) * 14)   # same size convention as reconstruction
        imr = np.asarray(Image.fromarray(im).resize((int(W * scale), int(H * scale)), Image.LANCZOS)).astype(np.float32) / 255
        photos.append(torch.tensor(imr, device=DEV))
        fx = W / (2 * np.tan(np.radians(cb["fov_h"] / 2))); fy = H / (2 * np.tan(np.radians(cb["fov_v"] / 2)))
        cams.append(Cam(cb, np.array([[fx, 0, W / 2], [0, fy, H / 2], [0, 0, 1]]), W, H, scale))
    train_ids = [i for i in range(len(cams)) if i != holdout]
    with torch.no_grad(): nview = visible_counts([cams[i] for i in train_ids], xyz); multi = (nview >= 2).float()[:, None]
    rgb0 = rgb.detach().clone(); opl0 = opl.detach().clone()
    print(f"[splat] {len(xyz)} gaussians, seen by >=2 training views: {float((nview >= 2).float().mean()):.2f}; hold-out view {holdout}")
    import os; lrm = float(os.environ.get("SPLAT_LR_MULT", "1.0"))
    groups = [{"params": [rgb], "lr": 0.01 * lrm}, {"params": [opl], "lr": 0.03 * lrm}, {"params": [sc], "lr": 0.004 * lrm}, {"params": [rot], "lr": 0.001 * lrm}]
    if lr_pos > 0: groups.append({"params": [xyz], "lr": lr_pos})
    opt = torch.optim.Adam(groups); t0 = time.time(); hist = []
    for it in range(iters):
        i = train_ids[it % len(train_ids)]; img, a = render(cams[i], xyz, sc, rot, opl, rgb); tgt = photos[i]
        # colour may drift only where several views constrain it; elsewhere it is held to the photo colour
        loss = (img - tgt).abs().mean() + 0.05 * (1 - a).mean() + colour_prior * (((rgb - rgb0) ** 2) * (1.0 - 0.9 * multi)).mean() + 0.5 * (((opl - opl0) ** 2) * (1.0 - 0.9 * multi[:, 0])).mean()
        opt.zero_grad(); loss.backward(); opt.step()
        with torch.no_grad(): sc.clamp_(-7.0, -1.5)
        if it % log_every == 0 or it == iters - 1:
            with torch.no_grad(): psnr = -10 * torch.log10(((img - tgt) ** 2).mean()).item()
            hist.append({"it": it, "l1": float(loss), "psnr": psnr}); print(f"[splat] it {it:4d} view {i} L1 {float(loss):.4f} PSNR {psnr:.2f} dB  ({time.time()-t0:.0f}s)")
    if holdout is not None:
        with torch.no_grad(): img, _ = render(cams[holdout], xyz, sc, rot, opl, rgb); ps = -10 * torch.log10(((img - photos[holdout]) ** 2).mean()).item()
        with torch.no_grad(): img0, _ = render(cams[holdout], torch.tensor(g["xyz"], device=DEV), torch.tensor(g["scale"], device=DEV), torch.tensor(g["rot"], device=DEV), torch.tensor(g["opacity"], device=DEV), rgb0); ps0 = -10 * torch.log10(((img0 - photos[holdout]) ** 2).mean()).item()
        print(f"[splat] HOLD-OUT view {holdout}: PSNR init {ps0:.2f} dB -> optimised {ps:.2f} dB  ({'better' if ps > ps0 else 'WORSE: overfitting'})")
        json.dump({"holdout": holdout, "psnr_init": ps0, "psnr_opt": ps, "passed": bool(ps > ps0)}, open(ROOT / "rooms" / f"{room_name}.splat_opt.json", "w"))
        from PIL import Image as _I; _I.fromarray((img.clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)).save(ROOT / "rooms" / f"{room_name}_holdout{holdout}_opt.png")
    out = {"xyz": xyz.detach().cpu().numpy(), "scale": sc.detach().cpu().numpy(), "rot": rot.detach().cpu().numpy(), "opacity": opl.detach().cpu().numpy(), "fdc": ((rgb.detach().cpu().numpy() - 0.5) / 0.28209479)}
    write_splat_ply(ROOT / "rooms" / f"{room_name}.splat_opt.ply", out); print(f"[splat] wrote {room_name}.splat_opt.ply with {len(out['xyz'])} gaussians, {time.time()-t0:.0f}s total"); return hist

if __name__ == "__main__":
    optimise(sys.argv[1], iters=int(sys.argv[2]) if len(sys.argv) > 2 else 200, holdout=int(sys.argv[3]) if len(sys.argv) > 3 else None)
