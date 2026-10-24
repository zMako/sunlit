"""Pipeline 2, stage 5b + 6: complete the cube-map panorama with SD 1.5 inpainting under the depth ControlNet (our shell's
depth), seen pixels always win; then texture the shell from the completed panorama and export the polished GLB.
Standalone: works from rooms/<name>.json and rooms/<name>_pano/."""
import sys, json, pathlib, numpy as np, cv2, torch
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parents[0] / "pipeline")); sys.path.insert(0, str(HERE))
import pano, seg as S
ROOMS = HERE.parents[0] / "rooms"
_pipe = None
PROMPT = "interior of an empty unfurnished apartment, bare painted walls, wood floor, plain ceiling, natural daylight, photorealistic, consistent with the rest of the room"
NEG = "furniture, sofa, bed, table, cabinet, curtains, plant, picture frame, people, text, watermark, lamp, clutter, distorted, cartoon, dark, blurry"

def pipe():
    global _pipe
    if _pipe is None:
        from diffusers import StableDiffusionControlNetInpaintPipeline, ControlNetModel
        cn = ControlNetModel.from_pretrained("lllyasviel/control_v11f1p_sd15_depth", torch_dtype=torch.float16)
        _pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained("stable-diffusion-v1-5/stable-diffusion-inpainting", controlnet=cn, torch_dtype=torch.float16, safety_checker=None)
        _pipe.load_ip_adapter("h94/IP-Adapter", subfolder="models", weight_name="ip-adapter_sd15.bin"); _pipe.set_ip_adapter_scale(0.55); _pipe = _pipe.to("mps"); _pipe.set_progress_bar_config(disable=True)
    return _pipe

def reference_image(name):
    """IP-Adapter reference: a 2x2 montage of the room's own photos (style, colours, materials)."""
    ps = sorted((ROOMS / f"{name}_photos").glob("*.jpg"))[:4]
    if not ps: return None
    ims = [Image.open(p).convert("RGB").resize((256, 256)) for p in ps]
    while len(ims) < 4: ims.append(ims[-1])
    m = Image.new("RGB", (512, 512)); [m.paste(im, ((k % 2) * 256, (k // 2) * 256)) for k, im in enumerate(ims)]; return m

def remove_blobs(rgb, seen, sid, max_frac=0.006, thr=55):
    """Photographed texels that differ strongly from the surrounding surface colour in small isolated blobs are
    misprojections (sun patch on a radiator, a blind seen through the glass): treat them as unseen."""
    out = seen.copy(); surf = sid >= 0
    for mask in (surf & seen, (sid == -1) & seen, (sid == -2) & seen):
        if mask.sum() < 500: continue
        med = np.median(rgb[mask].reshape(-1, 3), 0); dev = np.abs(rgb.astype(np.int32) - med.astype(np.int32)).sum(-1) > thr * 3
        n, lab, st, _ = cv2.connectedComponentsWithStats((dev & mask).astype(np.uint8))
        for j in range(1, n):
            if st[j, cv2.CC_STAT_AREA] < max_frac * mask.size: out[lab == j] = False
    return out

def complete_face(rgb, seen, depth_png, work=(640, 640), steps=22, seed=0, cn_scale=0.85, ref=None, prompt=None, strength=1.0):
    H, W = seen.shape; work = (work, work) if isinstance(work, int) else work
    if seen.mean() > 0.995: return rgb.copy(), np.zeros_like(seen)
    fill = rgb.copy(); med = np.median(rgb[seen].reshape(-1, 3), 0).astype(np.uint8) if seen.any() else np.array([200, 196, 190], np.uint8); fill[~seen] = med
    mask = cv2.dilate((~seen).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    im = Image.fromarray(fill).resize(work, Image.LANCZOS); mk = Image.fromarray((mask * 255).astype(np.uint8)).resize(work, Image.NEAREST); dp = Image.fromarray(depth_png).convert("RGB").resize(work, Image.BILINEAR)
    g = torch.Generator(device="cpu").manual_seed(seed)
    if ref is None:   # the adapter is loaded, so an image must be given: a flat image of the surface colour carries no texture
        ref = Image.fromarray(np.tile(med, (224, 224, 1)).astype(np.uint8)); pipe().set_ip_adapter_scale(0.15)
    else: pipe().set_ip_adapter_scale(0.3)
    kw = {"ip_adapter_image": ref}
    out = pipe()(prompt=prompt or PROMPT, negative_prompt=NEG, image=im, mask_image=mk, control_image=dp, num_inference_steps=steps, guidance_scale=6.0, controlnet_conditioning_scale=cn_scale, generator=g, strength=strength, **kw).images[0]
    out = np.asarray(out.resize((W, H), Image.LANCZOS)); res = rgb.copy(); res[~seen] = out[~seen]
    # soften the seam between photographed and generated texels
    edge = cv2.dilate(seen.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & ~cv2.erode(seen.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    blur = cv2.GaussianBlur(res, (0, 0), 2); res[edge] = blur[edge]
    return res, ~seen

SIDE = ["nx", "pz", "px", "nz"]
def complete_pano(name, work=512, steps=22):
    """Side faces as ONE strip (consistent colour and light around the room), then ceiling and floor with their own prompts."""
    d = ROOMS / f"{name}_pano"; done = {}; import time; t = time.time(); ref = reference_image(name)
    F = {}
    for face in pano.FACES:
        rgb = np.asarray(Image.open(d / f"{face}_rgb.png").convert("RGB")); seen = np.asarray(Image.open(d / f"{face}_seen.png")) > 0; dp = np.asarray(Image.open(d / f"{face}_depth.png")); sid = np.load(d / f"{face}_sid.npy")
        seen = remove_blobs(rgb, seen, sid)
        # pinholes between projected texels: fill from neighbours and count as seen
        dense = cv2.morphologyEx(seen.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)).astype(bool); holes = dense & ~seen
        if holes.any(): rgb = cv2.inpaint(np.ascontiguousarray(rgb), holes.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA); seen = dense
        # photographed areas that are mostly pinholes are not reliable texture: regenerate them
        dens = cv2.blur(seen.astype(np.float32), (31, 31)); seen = seen & (dens > 0.55)
        F[face] = (rgb, seen, dp)
    Sz = F["px"][0].shape[0]
    # surface colours from everything photographed: walls, floor, ceiling
    def med_colour(sid_val_fn, bright_half=False, lab_ok=None):
        def pick(f):
            m = sid_val_fn(np.load(d / f"{f}_sid.npy")) & F[f][1]
            if lab_ok is not None and (d / f"{f}_lab.npy").exists():
                lab = np.load(d / f"{f}_lab.npy")
                if (lab >= 0).any(): m = m & np.isin(lab, lab_ok)   # only texels that came from pixels of the paint itself (no glass, doors, cabinets)
            return F[f][0][m]
        acc = [pick(f) for f in pano.FACES]; acc = np.concatenate([a for a in acc if len(a)]) if any(len(a) for a in acc) else None
        if acc is None or len(acc) < 200: return None
        acc = acc.reshape(-1, 3)
        if bright_half:   # the paint, not the doors, closets and shadows that share the wall
            lum = acc.astype(np.float32).mean(1); acc = acc[lum >= np.quantile(lum, 0.5)]
        return np.median(acc, 0).astype(np.uint8)
    wall_c = med_colour(lambda sid: sid >= 0, bright_half=True, lab_ok=[3]); floor_c = med_colour(lambda sid: sid == -1, lab_ok=[1]); ceil_c = med_colour(lambda sid: sid == -2, bright_half=True, lab_ok=[2])
    wall_c = wall_c if wall_c is not None else np.array([226, 222, 212], np.uint8); floor_c = floor_c if floor_c is not None else np.array([170, 130, 90], np.uint8)
    ceil_default = np.minimum(wall_c.astype(int) + 12, 255).astype(np.uint8)
    if ceil_c is None or ceil_c.mean() < wall_c.mean() - 5 or (int(ceil_c.max()) - int(ceil_c.min())) > 30: ceil_c = ceil_default   # a ceiling is never darker or more saturated than the walls
    # faces with little photo coverage: flat paint per surface (an empty room's wall IS flat paint); diffusion only continues photographed faces
    gen_mask = {}
    for f in SIDE:
        rgb_f, seen_f, dp_f = F[f]; sid = np.load(d / f"{f}_sid.npy")
        flat = np.where((sid == -1)[..., None], floor_c, np.where((sid == -2)[..., None], ceil_c, wall_c)).astype(np.uint8)
        yy = np.linspace(1.03, 0.96, Sz)[:, None, None]; flat = np.clip(flat * yy, 0, 255).astype(np.uint8)
        flat[seen_f] = rgb_f[seen_f]; gen_mask[f] = ~seen_f
        # faces with little coverage stay flat paint; faces with real coverage get a light diffusion pass over the unseen part
        F[f] = (flat, np.ones_like(seen_f) if seen_f.mean() < 0.15 else seen_f, dp_f)
    rgb = np.concatenate([F[f][0] for f in SIDE], 1); seen = np.concatenate([F[f][1] for f in SIDE], 1); dp = np.concatenate([F[f][2] for f in SIDE], 1)
    wc = np.median(rgb[seen].reshape(-1, 3), 0) if seen.any() else np.array([225, 220, 210]); tone = "warm off-white" if wc.mean() > 190 and wc[0] > wc[2] + 5 else ("white" if wc.mean() > 200 else "light grey")
    import os
    if os.environ.get("VARIANT") == "A": res, gen = rgb.copy(), ~seen   # Path A: unseen wall is flat measured paint, no diffusion (it invents colour casts)
    else: res, gen = complete_face(rgb, seen, dp, work=(4 * work, work), steps=steps, seed=1, ref=None, strength=0.45, prompt=f"interior of an empty unfurnished apartment, smooth flat {tone} painted walls, plain, evenly lit, photorealistic, no texture, no stains")
    for k, f in enumerate(SIDE): done[f] = res[:, k * Sz:(k + 1) * Sz]; Image.fromarray(done[f]).save(d / f"{f}_done.png"); Image.fromarray((gen_mask[f] * 255).astype(np.uint8)).save(d / f"{f}_gen.png")
    # ceiling: plain. The measured ceiling colour (or the walls' lightest tone) with a soft gradient; diffusion invents texture here.
    rgb, seen, _ = F["py"]; cc = np.median(rgb[seen].reshape(-1, 3), 0) if seen.mean() > 0.02 else np.minimum(np.median(done["pz"].reshape(-1, 3), 0) * 1.06, 255)
    yy = np.linspace(0, 1, Sz)[:, None, None]; ceil_img = np.clip(cc[None, None, :] * (0.97 + 0.06 * yy), 0, 255).astype(np.uint8).repeat(Sz, 1)
    done["py"] = ceil_img; Image.fromarray(ceil_img).save(d / "py_done.png"); Image.fromarray(((~seen) * 255).astype(np.uint8)).save(d / "py_gen.png")
    res, gen = complete_face(F["ny"][0], F["ny"][1], F["ny"][2], work=(work, work), steps=steps, seed=2, ref=ref, prompt="wood floor of an empty apartment room seen from above, photorealistic, consistent planks, same wood as the reference"); done["ny"] = res
    Image.fromarray(res).save(d / "ny_done.png"); Image.fromarray((gen * 255).astype(np.uint8)).save(d / "ny_gen.png")
    print(f"[complete] {name}: strip + 2 faces in {time.time()-t:.0f}s"); return done

def sample_cube(faces, dirs, allowed=None):
    """dirs (N,3) unit -> colours (N,3) from the cube map dict face->(S,S,3). allowed: restrict to these faces (a floor texel
    samples the floor face even when its direction leaves the cube through a side face)."""
    ax = np.argmax(np.abs(dirs), axis=1); out = np.zeros((len(dirs), 3), np.uint8)
    if allowed:
        # pick the allowed face whose forward axis best matches the direction, then project onto it (may fall outside the face: clamp)
        best = None
        for name in allowed:
            r, u, f = (np.array(v, float) for v in pano.FACES[name]); df = dirs @ f
            if best is None or True:
                m = (df > 1e-3) if best is None else (df > best[1])
                if best is None: best = (np.array([name] * len(dirs), dtype=object), df.copy())
                else: best[0][m] = name; best[1][m] = df[m]
        for name in allowed:
            r, u, f = (np.array(v, float) for v in pano.FACES[name]); m = best[0] == name
            if not m.any(): continue
            dd = dirs[m]; df = np.maximum(dd @ f, 1e-3); sx = np.clip((dd @ r) / df, -1, 1); sy = np.clip((dd @ u) / df, -1, 1); img = faces[name]; Sz = img.shape[0]
            i = np.clip(((sx + 1) / 2 * Sz).astype(int), 0, Sz - 1); j = np.clip(((1 - sy) / 2 * Sz).astype(int), 0, Sz - 1); out[m] = img[j, i]
        return out
    for name, (r, u, f) in pano.FACES.items():
        r, u, f = (np.array(v, float) for v in (r, u, f)); comp = int(np.argmax(np.abs(f))); sgn = np.sign(f[comp])
        m = (ax == comp) & (np.sign(dirs[:, comp]) == sgn)
        if not m.any(): continue
        dd = dirs[m]; df = dd @ f; sx = (dd @ r) / df; sy = (dd @ u) / df; img = faces[name]; Sz = img.shape[0]
        i = np.clip(((sx + 1) / 2 * Sz).astype(int), 0, Sz - 1); j = np.clip(((1 - sy) / 2 * Sz).astype(int), 0, Sz - 1); out[m] = img[j, i]
    return out

def textures_from_pano(meta, faces, centre, res=0.01):
    import polish
    V = np.array(meta["polygon"]); ceil_m = meta["ceiling_m"]; frames = polish.wall_frames(meta["edges"], ceil_m); c = np.asarray(centre); tex = {}
    for fr in frames:
        nx, ny = max(8, int(fr["len"] / res)), max(8, int(ceil_m / res)); s_ = (np.arange(nx) + 0.5) * res; y_ = ceil_m - (np.arange(ny) + 0.5) * res
        Sg, Yg = np.meshgrid(s_, y_); P = np.stack([fr["a"][0] + fr["dir"][0] * Sg, Yg, fr["a"][1] + fr["dir"][1] * Sg], -1).reshape(-1, 3)
        dirs = P - c; dirs /= np.linalg.norm(dirs, axis=1, keepdims=True); tex[fr["k"]] = sample_cube(faces, dirs, allowed=SIDE).reshape(ny, nx, 3)
    lo = V.min(0); hi = V.max(0); nx, nz = max(8, int((hi[0] - lo[0]) / res)), max(8, int((hi[1] - lo[1]) / res))
    xs = lo[0] + (np.arange(nx) + 0.5) * (hi[0] - lo[0]) / nx; zs = lo[1] + (np.arange(nz) + 0.5) * (hi[1] - lo[1]) / nz; X, Z = np.meshgrid(xs, zs)
    P = np.stack([X, np.zeros_like(X), Z], -1).reshape(-1, 3); dirs = P - c; dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    ftex = {"img": sample_cube(faces, dirs, allowed=["ny"]).reshape(nz, nx, 3), "lo": lo.tolist(), "hi": hi.tolist()}
    P = np.stack([X, np.full_like(X, ceil_m), Z], -1).reshape(-1, 3); dirs = P - c; dirs /= np.linalg.norm(dirs, axis=1, keepdims=True); ceil_img = sample_cube(faces, dirs, allowed=["py"]).reshape(nz, nx, 3)
    return frames, tex, ftex, ceil_img

def export(name, faces, centre):
    import polish_export, trimesh
    meta = json.load(open(ROOMS / f"{name}.json")); frames, tex, ftex, ceil_img = textures_from_pano(meta, faces, centre)
    room = {"ceil_m": meta["ceiling_m"], "ceil_colour": np.median(ceil_img.reshape(-1, 3), 0).astype(int).tolist()}
    ops = []
    for j, o in enumerate(meta["windows"]): ops.append({**o, "kind": "window"})
    for o in meta["doors"]: ops.append({**o, "kind": o.get("kind", "door")})
    pol = {"openings": ops}; outside = {}   # windows are detected and cut; what lies beyond them comes later
    path = polish_export.export_polished(room, np.array(meta["polygon"]), frames, pol, tex, outside, ftex, ROOMS, name); print(f"[complete] wrote {path}"); return path

if __name__ == "__main__":
    import os
    name = sys.argv[1]; var = os.environ.get("VARIANT", "")
    if var and not name.endswith("_" + var): name = f"{name}_{var}"
    d = ROOMS / f"{name}_pano"; pj = json.load(open(d / "pano.json"))
    faces = complete_pano(name) if "--no-sd" not in sys.argv else {f: np.asarray(Image.open(d / f"{f}_rgb.png").convert("RGB")) for f in pano.FACES}
    export(name, faces, pj["centre"])
