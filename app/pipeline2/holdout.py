"""Hold-out test for the shell: build a room from all photos but one, texture the shell from the panorama (no diffusion),
render it from the held-out camera's pose and compare with the real photo. The held-out pose is transferred from the
full reconstruction by a similarity fit on the shared cameras. Usage: holdout.py <photo_dir> <photos comma list> <holdout idx>"""
import sys, json, pathlib, numpy as np
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parents[0] / "pipeline")); sys.path.insert(0, str(HERE))
import recon, build_room2, pano, complete
from PIL import Image
ROOMS = HERE.parents[0] / "rooms"

def similarity(src, dst):
    """Umeyama: s, R, t with dst ~ s R src + t. src/dst (N,3), N>=2 (N=2 -> scale+rotation about the pair, roll free)."""
    ms, md = src.mean(0), dst.mean(0); A = (src - ms); B = (dst - md); U, Sg, Vt = np.linalg.svd(A.T @ B)
    D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt)); R = (U @ D @ Vt).T; s = (Sg * np.diag(D)).sum() / max((A ** 2).sum(), 1e-9); t = md - s * R @ ms
    return s, R, t

def run(photo_dir, photos, hold, name="p2_holdout"):
    d = pathlib.Path(photo_dir); files = [str(d / p) for p in photos]; keep = [f for i, f in enumerate(files) if i != hold]
    full = recon.run(files); import geometry; Rf = geometry.gravity_frame(full["extrinsic"])
    cams_full = (Rf @ full["cam_centers"].T).T; fwd_full = np.array([Rf @ full["extrinsic"][i, 2, :3] for i in range(len(files))]); up_full = np.array([-(Rf @ full["extrinsic"][i, 1, :3]) for i in range(len(files))]); right_full = np.array([Rf @ full["extrinsic"][i, 0, :3] for i in range(len(files))])
    res = build_room2.build(d, name, ",".join(pathlib.Path(f).name for f in keep), 2.6, fit=True, quiet=True)
    if not res.get("ok"): return {"ok": False, "error": res.get("error")}
    meta = json.load(open(ROOMS / f"{name}.json")); cb = meta["cameras"]
    kept_idx = [i for i in range(len(files)) if i != hold]
    src = np.array([cams_full[i] for i in kept_idx]); dst = np.array([c["pos"] for c in cb])
    if len(src) >= 2: s, R, t = similarity(src, dst)
    else: s, R, t = 1.0, np.eye(3), dst[0] - src[0]
    pos = s * R @ cams_full[hold] + t; right, up, fwd = R @ right_full[hold], R @ up_full[hold], R @ fwd_full[hold]
    # textured shell from the (uncompleted) panorama
    pj = json.load(open(ROOMS / f"{name}_pano" / "pano.json")); faces = {f: np.asarray(Image.open(ROOMS / f"{name}_pano" / f"{f}_rgb.png").convert("RGB")) for f in pano.FACES}
    seen = {f: np.asarray(Image.open(ROOMS / f"{name}_pano" / f"{f}_seen.png")) > 0 for f in pano.FACES}
    ph = Image.open(files[hold]).convert("RGB"); W0, H0 = ph.size; W, H = 518, int(round(H0 * 518 / W0 / 14) * 14); K = full["intrinsic"][hold]
    j, i = np.mgrid[0:H, 0:W]; x = (i - K[0, 2]) / K[0, 0]; y = (j - K[1, 2]) / K[1, 1]; dirs = (fwd[None, None] + x[..., None] * right[None, None] - y[..., None] * up[None, None]).reshape(-1, 3); dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    V = np.array(meta["polygon"]); t_, sid = pano.shell_hit(pos, dirs, V, meta["ceiling_m"]); hit = np.isfinite(t_); P = pos + t_[:, None] * dirs
    cdirs = P - np.array(pj["centre"]); cdirs /= (np.linalg.norm(cdirs, axis=1, keepdims=True) + 1e-9)
    col = complete.sample_cube(faces, cdirs); sn = complete.sample_cube({f: np.repeat(seen[f][..., None], 3, -1).astype(np.uint8) * 255 for f in pano.FACES}, cdirs)[:, 0] > 0
    img = col.reshape(H, W, 3); valid = (sn & hit).reshape(H, W); ref = np.asarray(ph.resize((W, H), Image.LANCZOS)).astype(np.float32)
    err = ((img.astype(np.float32) - ref) ** 2)[valid].mean() if valid.any() else float("nan"); psnr = 10 * np.log10(255 ** 2 / max(err, 1e-6))
    out = np.concatenate([np.asarray(ph.resize((W, H))), img], 1); Image.fromarray(out).save(ROOMS / f"{name}_holdout{hold}.png")
    r = {"ok": True, "holdout": hold, "psnr_on_photographed": round(float(psnr), 2), "photographed_fraction": round(float(valid.mean()), 3), "n_photos": len(files), "scale_fit": round(float(s), 3)}
    print(f"[holdout] photo {hold} of {len(files)}: PSNR {psnr:.1f} dB on the {valid.mean()*100:.0f}% of pixels the shell had photo texture for; sim scale {s:.3f}"); return r

if __name__ == "__main__": run(sys.argv[1], sys.argv[2].split(","), int(sys.argv[3]))
