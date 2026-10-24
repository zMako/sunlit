"""Path B: best photo -> 360 panorama (SD outpainting) -> layout from segmentation -> textured box GLB.
Usage: run.py <listing_dir> <room_name> <photo list, comma-separated file names> [--pano-only]
Outputs in app/rooms: <name>_B.glb, <name>_B_polished.glb, <name>_B.json, <name>_B_pano.jpg, <name>_B_review.jpg"""
import sys, json, time, pathlib, numpy as np, cv2
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parents[1] / "pipeline")); sys.path.insert(0, str(HERE.parents[1]))
import equirect as E, outpaint as O, blayout as LY, export_box as X
ROOMS = HERE.parents[1] / "rooms"; PW, PH = 2048, 1024

def floor_plane_cam(P, i, segl):
    """Floor plane in the camera frame of photo i (OpenCV axes). Returns up vector in our frame (x right, y up, z fwd) and camera height (VGGT units)."""
    depth = P["depth"][i]; K = P["intrinsic"][i]; H, W = depth.shape[:2]
    u, v = np.meshgrid(np.arange(W), np.arange(H)); z = depth.squeeze()
    x = (u - K[0, 2]) / K[0, 0] * z; y = (v - K[1, 2]) / K[1, 1] * z; pts = np.stack([x, y, z], -1)
    m = (segl == 1) & (P["conf"][i] > 1.1) & (z > 0.1)
    if m.sum() < 500: return np.array([0, 1, 0.0]), None
    Q = pts[m].reshape(-1, 3); Q = Q[np.random.RandomState(0).choice(len(Q), min(len(Q), 20000), replace=False)]
    c = Q.mean(0); _, _, vt = np.linalg.svd(Q - c, full_matrices=False); n = vt[-1]
    if n[1] > 0: n = -n            # OpenCV y is down: the floor normal pointing up has negative y
    h = abs(np.dot(n, c))          # camera-to-plane distance
    up = np.array([n[0], -n[1], n[2]])   # to our frame (y up)
    return up / np.linalg.norm(up), float(h)

def main(listing_dir, name, photos, pano_only=False, reuse=False, guided=False):
    t0 = time.time(); d = pathlib.Path(listing_dir); paths = [str(d / p) for p in photos]; log = []
    import seg as S, recon
    P = recon.run(paths); S.model()
    segs = [S.segment(p)[0] for p in paths]; Hs, Ws = P["conf"].shape[1:]
    segl = [np.asarray(Image.fromarray(s).resize((Ws, Hs), Image.NEAREST)) for s in segs]
    hfov = [2 * np.degrees(np.arctan(Ws / (2 * P["intrinsic"][i][0, 0]))) for i in range(len(paths))]
    floorfrac = [float((s == 1).mean()) for s in segl]
    score = [ff * (1 + hf / 90) for ff, hf in zip(floorfrac, hfov)]; i = int(np.argmax(score))
    up, h_units = floor_plane_cam(P, i, segl[i])
    pitch = float(np.arctan2(-up[2], up[1])); roll = float(np.arctan2(-up[0], up[1]))
    log.append(f"photo {photos[i]} hfov {hfov[i]:.0f} floor {floorfrac[i]*100:.0f}% pitch {np.degrees(pitch):+.1f} roll {np.degrees(roll):+.1f} cam_h_units {h_units}")
    print("[B]", log[-1])
    # prompt from the structure pass (cached per listing)
    rtype = name.split("_")[-2] if name.count("_") >= 3 else "room"
    try:
        import vlm_structure; st = vlm_structure.structure(paths, rtype) or {}
    except Exception as e: st = {}; log.append(f"structure failed {type(e).__name__}")
    prompt = f"interior photo of an empty unfurnished {rtype}, {st.get('wall_colour', 'light')} painted walls, {st.get('floor_material', 'wood')} floor, white ceiling, natural daylight, real estate photography, wide angle, continuous room, photorealistic"
    # place the photo
    img = np.asarray(Image.open(paths[i]).convert("RGB"))
    # letterboxed listing photos (uniform white/black bars left-right or top-bottom): crop them, keep the principal point centred
    def bar(line): return line.std() < 6 and (line.mean() > 235 or line.mean() < 20)
    g = img.mean(-1); x0, x1, y0, y1 = 0, img.shape[1], 0, img.shape[0]
    while x1 - x0 > 200 and bar(g[:, x0]) and bar(g[:, x1 - 1]): x0 += 1; x1 -= 1
    while y1 - y0 > 200 and bar(g[y0, :]) and bar(g[y1 - 1, :]): y0 += 1; y1 -= 1
    if (x0, y0) != (0, 0): img = img[y0:y1, x0:x1]; log.append(f"cropped letterbox {x0}px x {y0}px per side")
    if img.shape[1] > 1600: img = np.asarray(Image.fromarray(img).resize((1600, int(img.shape[0] * 1600 / img.shape[1])), Image.LANCZOS))
    full_w = Image.open(paths[i]).size[0]; scale_crop = img.shape[1] / max(x1 - x0, 1)
    f_full = P["intrinsic"][i][0, 0] * full_w / Ws * scale_crop
    pano = np.zeros((PH, PW, 3), np.uint8); known = np.zeros((PH, PW), bool)
    R = E.rot(0.0, pitch, roll); E.paste_image(pano, known, img, R, f_full, img.shape[1] / 2 - 0.5, img.shape[0] / 2 - 0.5, feather=1)
    sfx = "_Bg" if guided else "_B"; box = None; depth_fn = None
    if guided:
        import guided as G
        labimg = np.asarray(Image.fromarray(segs[i]).resize(img.shape[1::-1], Image.NEAREST)); lab3 = np.repeat(labimg[..., None], 3, -1).astype(np.uint8)
        labp = np.full((PH, PW, 3), 255, np.uint8); kn2 = np.zeros((PH, PW), bool); E.paste_image(labp, kn2, lab3, R, f_full, img.shape[1] / 2 - 0.5, img.shape[0] / 2 - 0.5, feather=1, nearest=True)
        lab = np.where(kn2, labp[..., 0].astype(np.int16), -1)
        box = G.box_from_photo(lab, kn2, 1.45, st.get("width_m"), st.get("depth_m"), S.FLOOR, S.CEIL, S.WALL); depth_fn = G.depth_fn_for(box)
        log.append(f"box {box['width_m']:.2f}x{box['depth_m']:.2f} ceil {box['ceiling_m']:.2f} measured {box['measured_sides']} from {box['n_boundary_cols']} cols"); print("[B]", log[-1])
    Image.fromarray(pano).save(ROOMS / f"{name}{sfx}_pano_init.jpg", quality=85)
    ref = Image.fromarray(img).resize((512, 512)); cached = ROOMS / f"{name}{sfx}_pano.jpg"
    if reuse and cached.exists(): pano = np.asarray(Image.open(cached).convert("RGB")).copy(); log.append("pano reused")
    else:
        t = time.time(); pano, known = O.outpaint(pano, known, prompt, ref, log=lambda s: print("[B]", s), depth_fn=depth_fn); log.append(f"outpaint {time.time()-t:.0f}s")
        if (~known).any():   # the few texels no view covered (pole caps): nearest known colour
            pano = cv2.inpaint(pano, (~known).astype(np.uint8), 3, cv2.INPAINT_TELEA)
        Image.fromarray(pano).save(cached, quality=90)
    if pano_only: json.dump({"name": name, "log": log, "s": round(time.time() - t0)}, open(ROOMS / f"{name}{sfx}.json", "w"), indent=1); return
    # layout
    proc, net, dev, lut = S.model()
    import torch
    def seg_fn(rgb):
        inp = proc(images=Image.fromarray(rgb), return_tensors="pt").to(dev)
        with torch.no_grad(): out = net(**inp)
        return lut[proc.post_process_semantic_segmentation(out, target_sizes=[rgb.shape[:2]])[0].cpu().numpy()]
    t = time.time(); lab = LY.label_pano(pano, seg_fn); fl, ce = LY.boundaries(lab, S.FLOOR, S.CEIL, S.WALL); lay = LY.rectangle(fl, ce, cam_h=1.5); log.append(f"layout {time.time()-t:.0f}s")
    vlm_area = (st.get("width_m") or 0) * (st.get("depth_m") or 0)
    lay["area_m2_at_cam_h_1p5"] = lay["area_m2"]
    vlm_ceil = st.get("ceiling_m") if st.get("ceiling_m") and 2.2 <= float(st.get("ceiling_m")) <= 3.6 else None
    if guided: lay_free = lay; lay = dict(box); lay["free_layout_area_m2"] = round(lay_free["area_m2"], 1)
    elif vlm_area:   # absolute scale is free in a panorama; the shape comes from the panorama, the size from the VLM estimate (camera height follows)
        cam_h = float(np.clip(1.5 * np.sqrt(vlm_area / lay["area_m2"]), 0.9, 1.8)); lay = LY.rectangle(fl, ce, cam_h=cam_h); lay["area_m2_at_cam_h_1p5"] = round(lay["area_m2"] * (1.5 / cam_h) ** 2, 1); log.append(f"scale: cam_h {cam_h:.2f} m to match VLM area {vlm_area:.1f} m2")
    # the generated panorama puts far walls too far for its own ceiling line; after scaling the floor to the VLM area the ceiling
    # comes out low, so the ceiling height is taken from the VLM (or 2.5 m) and the wall textures stretch a little vertically
    lay["ceiling_m_from_pano"] = round(lay["ceiling_m"], 2); lay["ceiling_m"] = float(vlm_ceil or 2.5) if not guided else lay["ceiling_m"]
    lay.update({"vlm_width_m": st.get("width_m"), "vlm_depth_m": st.get("depth_m"), "vlm_area_m2": round(vlm_area, 1) if vlm_area else None, "area_ratio_vs_vlm": round(lay["area_m2"] / vlm_area, 2) if vlm_area else None})
    print("[B] layout", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in lay.items() if k != "corners"})
    # export
    ceil_rgb = np.median(img[np.asarray(Image.fromarray(segs[i]).resize(img.shape[1::-1], Image.NEAREST)) == S.CEIL].reshape(-1, 3), 0) if (segs[i] == S.CEIL).sum() > 200 else np.array([235, 235, 232])
    glb = X.export(pano, lay, str(ROOMS / f"{name}{sfx}.glb"), ceil_rgb=ceil_rgb.astype(np.uint8)); import shutil; shutil.copy(glb, ROOMS / f"{name}{sfx}_polished.glb")
    # review sheet: panorama with boundaries + source photo
    ov = LY.overlay(pano, fl, ce); ovs = Image.fromarray(ov).resize((1536, 768)); src = Image.fromarray(img); src.thumbnail((1536, 400))
    sheet = Image.new("RGB", (1536, 768 + src.height), "black"); sheet.paste(ovs, (0, 0)); sheet.paste(src, (0, 768)); sheet.save(ROOMS / f"{name}{sfx}_review.jpg", quality=85)
    meta = {"name": name, "path": "B-guided" if guided else "B-free", "listing": d.name, "photos": photos, "chosen_photo": photos[i], "hfov_deg": round(hfov[i], 1), "pitch_deg": round(np.degrees(pitch), 1), "prompt": prompt,
            "area_m2": round(lay["area_m2"], 2), "width_m": round(lay["width_m"], 2), "depth_m": round(lay["depth_m"], 2), "ceiling_m": round(lay["ceiling_m"], 2), "layout": lay, "log": log, "s": round(time.time() - t0)}
    def _san(o):
        if isinstance(o, dict): return {k: _san(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [_san(v) for v in o]
        if isinstance(o, (np.floating, np.integer)): return o.item()
        return o
    json.dump(_san(meta), open(ROOMS / f"{name}{sfx}.json", "w"), indent=1); print(f"[B] {name}: {meta['area_m2']} m2 ({meta['width_m']} x {meta['depth_m']}, ceil {meta['ceiling_m']}), {meta['s']}s")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3].split(","), pano_only="--pano-only" in sys.argv, reuse="--reuse-pano" in sys.argv, guided="--guided" in sys.argv)
