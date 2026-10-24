"""Pipeline 2, stage 5a: cube-map panorama of the shell from the room centre. Each face pixel: first hit on the shell
(walls / floor / ceiling), colour from the best photo whose own 3D point agrees with that shell point (so objects and
anything seen through openings do not smear onto walls), hole mask where no photo saw the surface, metric depth for
the diffusion ControlNet. Faces: +x -x +y -y +z -z in the room frame (y up)."""
import sys, json, pathlib, numpy as np
from PIL import Image

FACES = {"px": ([0, 0, -1], [0, 1, 0], [1, 0, 0]), "nx": ([0, 0, 1], [0, 1, 0], [-1, 0, 0]), "py": ([1, 0, 0], [0, 0, -1], [0, 1, 0]),
         "ny": ([1, 0, 0], [0, 0, 1], [0, -1, 0]), "pz": ([1, 0, 0], [0, 1, 0], [0, 0, 1]), "nz": ([-1, 0, 0], [0, 1, 0], [0, 0, -1])}   # right, up, fwd

def face_rays(name, size):
    r, u, f = (np.array(v, float) for v in FACES[name]); j, i = np.mgrid[0:size, 0:size]; x = (i + 0.5) / size * 2 - 1; y = 1 - (j + 0.5) / size * 2
    d = f[None, None] + x[..., None] * r[None, None] + y[..., None] * u[None, None]; return d / np.linalg.norm(d, axis=-1, keepdims=True)

def shell_hit(c, d, V, ceil_m):
    """First hit of rays d (N,3) from c on the shell. Returns t (N,), surface id (N,) (-1 floor, -2 ceiling, k wall k)."""
    N = len(d); best_t = np.full(N, np.inf); sid = np.full(N, -9, int); V = np.asarray(V, float); n_e = len(V); cen = V.mean(0)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = -c[1] / d[:, 1]; m = (d[:, 1] < -1e-6) & (t > 0.05) & (t < best_t); best_t[m] = t[m]; sid[m] = -1
        t = (ceil_m - c[1]) / d[:, 1]; m = (d[:, 1] > 1e-6) & (t > 0.05) & (t < best_t); best_t[m] = t[m]; sid[m] = -2
        for k in range(n_e):
            a, b = V[k], V[(k + 1) % n_e]; e = b - a; L = np.linalg.norm(e); e = e / max(L, 1e-9); n2 = np.array([e[1], -e[0]])
            if n2 @ ((a + b) / 2 - cen) < 0: n2 = -n2
            n3 = np.array([n2[0], 0.0, n2[1]]); dn = d @ n3; t = (n3 @ np.array([a[0], 0, a[1]]) - c @ n3) / np.where(np.abs(dn) < 1e-6, 1e-6, dn)
            h = c + t[:, None] * d; s_ = (h[:, 0] - a[0]) * e[0] + (h[:, 2] - a[1]) * e[1]
            m = (np.abs(dn) > 1e-6) & (t > 0.05) & (t < best_t) & (s_ >= -0.01) & (s_ <= L + 0.01) & (h[:, 1] >= -0.01) & (h[:, 1] <= ceil_m + 0.01)
            best_t[m] = t[m]; sid[m] = k
    return best_t, sid

def render_faces(room, P, V, sel, size=768, tol=0.2, centre=None, projective=False):
    from fuse import cam_matrices
    V = np.asarray(V, float); ceil_m = room["ceil_m"]
    c = np.array([V[:, 0].mean(), min(1.5, ceil_m * 0.55), V[:, 1].mean()]) if centre is None else np.asarray(centre, float)
    S_, H, W = room["labels"].shape; photos = [np.asarray(Image.open(p).convert("RGB")) for p in sel]
    out = {}
    # inward shell normals per surface id for the projective weights: index k -> wall k, -1 floor (up), -2 ceiling (down)
    n_e = len(V); cen2 = V.mean(0); shell_norm = np.zeros((n_e + 2, 3))
    for k in range(n_e):
        a, b = V[k], V[(k + 1) % n_e]; e = b - a; e /= max(np.linalg.norm(e), 1e-9); n2 = np.array([e[1], -e[0]])
        if n2 @ ((a + b) / 2 - cen2) < 0: n2 = -n2
        shell_norm[k] = [-n2[0], 0.0, -n2[1]]
    shell_norm[-1] = [0, 1, 0]; shell_norm[-2] = [0, -1, 0]
    if projective and "_allowed" not in room:   # exterior seen through windows must not be painted on walls: mask 'other' pixels inside dilated window components
        import cv2; allowed = np.ones_like(room["good"])
        for i in range(S_):   # letterbox / pillarbox padding (uniform bars at the photo's edges) is not room surface
            g = np.asarray(Image.fromarray(photos[i]).convert("L").resize((W, H), Image.BILINEAR)).astype(np.float32)
            def bar(axis, rev):
                prof_std = g.std(axis=axis); prof_mean = g.mean(axis=axis); n = 0; rng_ = range(len(prof_std) - 1, -1, -1) if rev else range(len(prof_std))
                for k in rng_:
                    if prof_std[k] < 4.0 and (prof_mean[k] > 235 or prof_mean[k] < 20): n += 1
                    else: break
                return n
            l, r_, t_, b_ = bar(0, False), bar(0, True), bar(1, False), bar(1, True)
            if l: allowed[i][:, :l] = False
            if r_: allowed[i][:, W - r_:] = False
            if t_: allowed[i][:t_, :] = False
            if b_: allowed[i][H - b_:, :] = False
        for i in range(S_):
            win = (room["seg"][i] == 4).astype(np.uint8) if "seg" in room else None
            if win is None or win.sum() < 200: continue
            ring = cv2.dilate(win, np.ones((25, 25), np.uint8)).astype(bool); allowed[i] &= ~(ring & (room["seg"][i] == 0))
        room["_allowed"] = allowed
    for name in FACES:
        d = face_rays(name, size).reshape(-1, 3); t, sid = shell_hit(c, d, V, ceil_m); hit = np.isfinite(t); p = c + t[:, None] * d
        col = np.zeros((len(d), 3), np.float32); wbest = np.zeros(len(d)); src = np.full(len(d), -1, int); labsel = np.full(len(d), -1, np.int16)
        for i in range(S_):
            R, ci, K = cam_matrices(room, P, i); ph = photos[i]; sy, sx = ph.shape[0] / H, ph.shape[1] / W
            cam = (p - ci) @ R.T; z = cam[:, 2]; ok = hit & (z > 0.1)
            u = K[0, 0] * cam[:, 0] / np.where(ok, z, 1) + K[0, 2]; v = -K[1, 1] * cam[:, 1] / np.where(ok, z, 1) + K[1, 2]
            ui = np.clip(np.round(u).astype(int), 0, W - 1); vi = np.clip(np.round(v).astype(int), 0, H - 1); inb = ok & (u >= 0) & (u < W) & (v >= 0) & (v < H)
            r_obs = np.linalg.norm(room["pts"][i][vi, ui] - ci, axis=1); r_hit = np.linalg.norm(p - ci, axis=1)
            view = (ci - p); view /= (np.linalg.norm(view, axis=1, keepdims=True) + 1e-9)
            if projective:
                # Path A: paint the whole photo onto the box, no agreement test. Weight: frontal to the SHELL normal, near,
                # and away from the photo's own borders (lens distortion, vignetting). Skip pixels the segmentation calls
                # 'other' only when they lie inside a window component (exterior seen through the glass).
                agree = inb & room.get("_allowed", np.ones_like(room["good"]))[i][vi, ui]
                if "seg" in room:   # a texel takes only pixels of its own surface kind: no floor painted on walls, no ceiling slabs
                    lab = room["seg"][i][vi, ui]; surf = np.where(sid >= 0, 0, np.where(sid == -1, 1, 2))
                    okk = np.where(surf == 0, ~np.isin(lab, [1, 2]), np.where(surf == 1, np.isin(lab, [1, 7, 8]), lab == 2))
                    agree = agree & okk
                nshell = shell_norm[np.where(sid < -2, 0, sid)]; frontal = np.clip(np.einsum("ij,ij->i", nshell, view), 0.05, 1.0)
                border = np.clip(np.minimum(np.minimum(u, W - u) / (0.15 * W), np.minimum(v, H - v) / (0.15 * H)), 0.2, 1.0)
                w = frontal * border / np.maximum(r_hit, 0.8) * agree
            else:
                agree = inb & room["good"][i][vi, ui] & (np.abs(r_obs - r_hit) < tol)
                nrm = room["normals"][i][vi, ui]
                w = np.clip(np.einsum("ij,ij->i", nrm, view), 0.05, 1.0) / np.maximum(r_hit, 0.5) * agree
            better = w > wbest; uo = np.clip((u * sx).astype(int), 0, ph.shape[1] - 1); vo = np.clip((v * sy).astype(int), 0, ph.shape[0] - 1)
            col[better] = ph[vo[better], uo[better]]; wbest[better] = w[better]; src[better] = i
            if projective and "seg" in room: labsel[better] = room["seg"][i][vi, ui][better]
        seen = wbest > 0
        if projective:   # feather the seams between photos
            import cv2; si = src.reshape(size, size); ci_ = col.reshape(size, size, 3)
            edge = np.zeros((size, size), bool); edge[:, 1:] |= (si[:, 1:] != si[:, :-1]) & (si[:, 1:] >= 0) & (si[:, :-1] >= 0); edge[1:, :] |= (si[1:, :] != si[:-1, :]) & (si[1:, :] >= 0) & (si[:-1, :] >= 0)
            edge = cv2.dilate(edge.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & seen.reshape(size, size)
            if edge.any(): blur = cv2.GaussianBlur(ci_.astype(np.uint8), (0, 0), 2.5); ci_[edge] = blur[edge]; col = ci_.reshape(-1, 3)
        out[name] = {"rgb": col.reshape(size, size, 3).astype(np.uint8), "seen": seen.reshape(size, size), "depth": np.where(hit, t, 0).reshape(size, size).astype(np.float32),
                     "sid": sid.reshape(size, size), "src": src.reshape(size, size), "lab": labsel.reshape(size, size)}
    out["_centre"] = c.tolist(); return out

def save_faces(faces, out_dir):
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True); stats = {}
    for name, f in faces.items():
        if name.startswith("_"): continue
        Image.fromarray(f["rgb"]).save(out_dir / f"{name}_rgb.png"); Image.fromarray((f["seen"] * 255).astype(np.uint8)).save(out_dir / f"{name}_seen.png")
        dmax = max(1e-6, float(np.percentile(f["depth"][f["depth"] > 0], 99))) if (f["depth"] > 0).any() else 1.0
        inv = np.where(f["depth"] > 0, 1.0 - np.clip(f["depth"] / dmax, 0, 1), 0.0); Image.fromarray((inv * 255).astype(np.uint8)).save(out_dir / f"{name}_depth.png")
        np.save(out_dir / f"{name}_sid.npy", f["sid"]); np.save(out_dir / f"{name}_lab.npy", f.get("lab", np.full_like(f["sid"], -1))); stats[name] = {"seen_frac": round(float(f["seen"].mean()), 3)}
    json.dump({"centre": faces["_centre"], "faces": stats}, open(out_dir / "pano.json", "w"), indent=1); return stats

def contact_sheet(out_dir, path):
    out_dir = pathlib.Path(out_dir); order = ["nx", "pz", "px", "nz", "py", "ny"]; ims = []
    for n in order:
        rgb = Image.open(out_dir / f"{n}_rgb.png").convert("RGB"); seen = np.asarray(Image.open(out_dir / f"{n}_seen.png")) > 0
        a = np.asarray(rgb).copy(); a[~seen] = (a[~seen] * 0.3 + np.array([255, 0, 255]) * 0.7).astype(np.uint8); ims.append(Image.fromarray(a).resize((384, 384)))
    sheet = Image.new("RGB", (384 * 4, 384 * 2)); [sheet.paste(im, ((k % 4) * 384, (k // 4) * 384)) for k, im in enumerate(ims)]; sheet.save(path)
