"""Polish: the shell is the base. Every photo pixel is cast onto the shell; per wall we get a high-res texture, provenance,
an opening map (see-through + brightness + detector prior) and the view outside each window. Walls are flat-fielded,
openings become reveal+frame+glass with a billboard of the real view behind. Baseboards and ceiling are procedural."""
import numpy as np, cv2, json, pathlib
from geometry import FLOOR, CEIL, WALL, OTHER

RES = 0.01   # texel size in metres

def wall_frames(edges, ceil_m):
    fr = []
    for k, e in enumerate(edges):
        a, b = np.array(e["a"]), np.array(e["b"]); d = b - a; L = float(np.linalg.norm(d)); d = d / max(L, 1e-9)
        n = np.array(e["n"], float); fr.append({"k": k, "a": a, "dir": d, "n": n, "offset": float(e["offset"]), "len": L, "nx": max(8, int(L / RES)), "ny": max(8, int(ceil_m / RES))})
    return fr

def cast_pixels(room, P, frames, ceil_m, stride=1):
    """For each pixel of each photo: first shell surface hit along the pixel ray (walls, floor, ceiling); observed range
    vs hit range -> at / beyond / front. Returns per-wall accumulators."""
    from fuse import cam_matrices
    S, H, W = room["labels"].shape; acc = {}
    for f in frames:
        acc[f["k"]] = {"col": np.zeros((f["ny"], f["nx"], 3)), "n_at": np.zeros((f["ny"], f["nx"])), "beyond_col": np.zeros((f["ny"], f["nx"], 3)), "n_beyond": np.zeros((f["ny"], f["nx"])),
                       "n_front": np.zeros((f["ny"], f["nx"])), "n_any": np.zeros((f["ny"], f["nx"])), "lum": np.zeros((f["ny"], f["nx"])), "gen": np.zeros((f["ny"], f["nx"])), "sat": np.zeros((f["ny"], f["nx"]))}
    gen = room.get("generated")
    for i in range(S):
        R, c, K = cam_matrices(room, P, i); vs, us = np.mgrid[0:H:stride, 0:W:stride]; us, vs = us.reshape(-1), vs.reshape(-1)
        x = (us - K[0, 2]) / K[0, 0]; y = (vs - K[1, 2]) / K[1, 1]; d = np.stack([x, -y, np.ones_like(x)], -1) @ R; dn = np.linalg.norm(d, axis=1); d = d / dn[:, None]
        pts = room["pts"][i][vs, us]; r_obs = np.linalg.norm(pts - c, axis=1); rgb = room["rgb"][i][vs, us].astype(float); g = room["good"][i][vs, us]
        gm = gen[i][vs, us] if gen is not None else np.zeros(len(us), bool)
        best_t = np.full(len(d), np.inf); best_k = np.full(len(d), -1); best_s = np.zeros(len(d)); best_h = np.zeros(len(d))
        with np.errstate(divide="ignore", invalid="ignore"):
            tf = -c[1] / d[:, 1]; m = (d[:, 1] < -1e-6) & (tf > 0.1) & (tf < best_t); best_t[m] = tf[m]; best_k[m] = -2
            tc = (ceil_m - c[1]) / d[:, 1]; m = (d[:, 1] > 1e-6) & (tc > 0.1) & (tc < best_t); best_t[m] = tc[m]; best_k[m] = -3
            for f in frames:
                n3 = np.array([f["n"][0], 0.0, f["n"][1]]); ddn = d @ n3; t = (f["offset"] - c @ n3) / np.where(np.abs(ddn) < 1e-6, 1e-6, ddn)
                hpt = c + t[:, None] * d; s_ = (hpt[:, 0] - f["a"][0]) * f["dir"][0] + (hpt[:, 2] - f["a"][1]) * f["dir"][1]
                m = (np.abs(ddn) > 1e-6) & (t > 0.1) & (t < best_t) & (s_ >= 0) & (s_ <= f["len"]) & (hpt[:, 1] >= 0) & (hpt[:, 1] <= ceil_m)
                best_t[m] = t[m]; best_k[m] = f["k"]; best_s[m] = s_[m]; best_h[m] = hpt[m, 1]
        for f in frames:
            m = best_k == f["k"]
            if not m.any(): continue
            u = np.clip((best_s[m] / RES).astype(int), 0, f["nx"] - 1); v = np.clip(((ceil_m - best_h[m]) / RES).astype(int), 0, f["ny"] - 1)
            t_hit = best_t[m]; ro = r_obs[m]; col = rgb[m]; gg = g[m]; lum = 0.299 * col[:, 0] + 0.587 * col[:, 1] + 0.114 * col[:, 2]
            at = gg & (np.abs(ro - t_hit) < 0.15); beyond = (ro > t_hit + 0.25); front = gg & (ro < t_hit - 0.15)
            A = acc[f["k"]]
            sat = (col.max(1) - col.min(1)) / np.maximum(col.max(1), 1.0)
            np.add.at(A["n_any"], (v, u), 1); np.add.at(A["lum"], (v, u), lum); np.add.at(A["gen"], (v, u), gm[m].astype(float)); np.add.at(A["sat"], (v, u), sat)
            np.add.at(A["col"], (v[at], u[at]), col[at]); np.add.at(A["n_at"], (v[at], u[at]), 1)
            np.add.at(A["beyond_col"], (v[beyond], u[beyond]), col[beyond]); np.add.at(A["n_beyond"], (v[beyond], u[beyond]), 1)
            np.add.at(A["n_front"], (v[front], u[front]), 1)
    return acc

def flat_field(img, seen, sigma_px=90):
    """Divide out smooth illumination per wall (exposure/vignetting across photos), keep detail."""
    lum = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32) + 1.0; w = seen.astype(np.float32)
    num = cv2.GaussianBlur(lum * w, (0, 0), sigma_px); den = cv2.GaussianBlur(w, (0, 0), sigma_px) + 1e-6; illum = num / den
    target = float(np.median(lum[seen])) if seen.any() else 128.0
    gain = np.clip(target / np.maximum(illum, 1.0), 0.7, 1.4)[..., None]
    out = np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8); return out

_owl = None
def owl_on_texture(img, thr=0.2):
    """Open-vocabulary detector on the orthographic wall texture: frontal, metric, no perspective merge with the radiator below."""
    global _owl
    import torch
    from transformers import Owlv2Processor, Owlv2ForObjectDetection
    from PIL import Image as _Im
    if _owl is None: _owl = (Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble"), Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").eval())
    proc, det = _owl; im = _Im.fromarray(img); q = [["a window", "a door", "a doorway"]]
    inp = proc(text=q, images=im, return_tensors="pt")
    with torch.no_grad(): o = det(**inp)
    r = proc.post_process_grounded_object_detection(o, threshold=thr, target_sizes=torch.tensor([[max(im.size)] * 2]), text_labels=q)[0]
    out = []
    for b, sc, l in zip(r["boxes"], r["scores"], r["labels"]):
        x0, y0, x1, y1 = [int(v) for v in b]; x0, x1 = max(0, x0), min(img.shape[1] - 1, x1); y0, y1 = max(0, y0), min(img.shape[0] - 1, y1)
        if x1 - x0 > 0.3 / RES and y1 - y0 > 0.3 / RES: out.append({"box": [x0, y0, x1, y1], "label": ["window", "door", "passage"][int(l)], "score": float(sc)})
    # suppress boxes contained in larger boxes of the same label
    out.sort(key=lambda d: -(d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1])); keep = []
    for d in out:
        bx = d["box"]
        if any(k["label"] == d["label"] and k["box"][0] <= bx[0] + 5 and k["box"][1] <= bx[1] + 5 and k["box"][2] >= bx[2] - 5 and k["box"][3] >= bx[3] - 5 for k in keep): continue
        keep.append(d)
    return keep

def detect_openings_tex(A, f, ceil_m, owl_boxes=None, tex_img=None):
    """Opening map in wall-texel space: see-through fraction + brightness + detector prior -> rectangles snapped to edges."""
    n_any = A["n_any"]; seen = n_any > 0; lum = np.where(seen, A["lum"] / np.maximum(n_any, 1), 0)
    beyond_frac = A["n_beyond"] / np.maximum(n_any, 1); wall_lum = np.median(lum[(A["n_at"] > 0)]) if (A["n_at"] > 0).any() else 150
    bright = np.clip((lum - wall_lum - 25) / 60, 0, 1) * seen
    satm = np.where(seen, A["sat"] / np.maximum(n_any, 1), 0); wall_sat = np.median(satm[(A["n_at"] > 0)]) if (A["n_at"] > 0).any() else 0.1
    colourful = np.clip((satm - wall_sat - 0.08) / 0.25, 0, 1) * seen   # the world outside has colour; painted walls do not
    cues = 0.6 * beyond_frac + 0.45 * bright + 0.5 * colourful; score = cues
    prior = np.zeros_like(score); img_tex = tex_img if tex_img is not None else np.clip(A["col"] / np.maximum(A["n_at"], 1)[..., None], 0, 255).astype(np.uint8)
    tex_boxes = owl_on_texture(img_tex) if seen.mean() > 0.08 else []
    tex_boxes = [d for d in tex_boxes if (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]) < 0.6 * prior.size]
    for d in tex_boxes:
        x0, y0, x1, y1 = d["box"]; prior[y0:y1, x0:x1] = np.maximum(prior[y0:y1, x0:x1], 0.5 * d["score"])
    for (s0, s1, y0, y1) in owl_boxes or []:   # photo-space detector boxes lifted onto the wall: widths are reliable
        u0, u1 = int(s0 / RES), int(s1 / RES); v0, v1 = int((ceil_m - y1) / RES), int((ceil_m - y0) / RES); prior[max(v0, 0):v1, max(u0, 0):u1] = np.maximum(prior[max(v0, 0):v1, max(u0, 0):u1], 0.8)
    score = score + 0.6 * prior
    m = (score > 0.45).astype(np.uint8); k = max(3, int(0.08 / RES))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)); m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m); out = []
    img = tex_img if tex_img is not None else np.clip(A["col"] / np.maximum(A["n_at"], 1)[..., None], 0, 255).astype(np.uint8); gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    gx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)); gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    for j in range(1, n):
        x, y, w, h, area = st[j]
        if w * RES < 0.35 or h * RES < 0.35 or area < 0.5 * w * h: continue
        # trim the box to the rows/columns that actually score (a bright wall strip under a window must not pull it to the floor)
        sub = cues[y:y + h, x:x + w]; rows = sub.mean(1); cols = sub.mean(0)   # trim on photo cues only, not on the detector prior
        csub = colourful[y:y + h, x:x + w]; crow = csub.mean(1)
        print(f"[polish-dbg] wall {f['k']} cand {w*RES:.2f}x{h*RES:.2f} colourful mean {csub.mean():.3f} top-half {crow[:len(crow)//2].mean():.3f} bottom-half {crow[len(crow)//2:].mean():.3f}")
        if crow[:max(1, len(crow)//2)].mean() > 0.08 and crow[:max(1, len(crow)//2)].mean() > 2.5 * (crow[len(crow)//2:].mean() + 0.01):
            thr_c = 0.5 * crow[:len(crow)//2].mean(); last = int(np.max(np.nonzero(crow > thr_c)[0])) + 1 if (crow > thr_c).any() else len(crow)
            rows = np.where(np.arange(len(crow)) < last, 1.0, 0.0); cols = np.ones(len(cols))
        def core(prof, thr=0.25):
            k0 = int(np.argmax(prof)); lo = k0; hi = k0
            while lo > 0 and prof[lo - 1] >= thr: lo -= 1
            while hi < len(prof) - 1 and prof[hi + 1] >= thr: hi += 1
            return lo, hi + 1
        r0, r1 = core(rows); c0, c1 = core(cols)
        if (r1 - r0) * RES >= 0.3 and (c1 - c0) * RES >= 0.3: y, h, x, w = y + r0, r1 - r0, x + c0, c1 - c0
        # a detector box that overlaps this candidate and sits off the floor is a window: do not let the box run below its sill
        for (ps0, ps1, py0, py1) in owl_boxes or []:
            if py0 >= 0.3 and min(ps1, (x + w) * RES) - max(ps0, x * RES) > 0.3 * (ps1 - ps0):
                ybot = int((ceil_m - (py0 - 0.1)) / RES)
                if y + h > ybot and ybot - y > 0.3 / RES: h = ybot - y
        # snap each side to the strongest edge within +-25 cm
        band = int(0.45 / RES)
        def snap_col(x0):
            lo, hi = max(0, x0 - band), min(gray.shape[1] - 1, x0 + band); prof = gx[y:y + h, lo:hi + 1].mean(0); return lo + int(np.argmax(prof)) if prof.size else x0
        def snap_row(y0):
            lo, hi = max(0, y0 - band), min(gray.shape[0] - 1, y0 + band); prof = gy[lo:hi + 1, x:x + w].mean(1); return lo + int(np.argmax(prof)) if prof.size else y0
        x0, x1, y0, y1 = snap_col(x), snap_col(x + w), snap_row(y), snap_row(y + h)
        if x1 - x0 < 0.3 / RES or y1 - y0 < 0.3 / RES: x0, x1, y0, y1 = x, x + w, y, y + h
        # sill from local variance: scanning up from the bottom, the window starts where the texture becomes busy for 10 cm
        if (ceil_m - y1 * RES) < 0.3 and (y1 - y0) * RES > 1.3:
            kk = int(0.12 / RES) | 1; mu = cv2.blur(gray.astype(np.float32), (kk, kk)); var = cv2.blur(gray.astype(np.float32) ** 2, (kk, kk)) - mu ** 2
            prof = np.sqrt(np.clip(var, 0, None))[y0:y1, x0:x1].mean(1); hi_ = prof.max() + 1e-6; run = 0; sill_row = None
            for r in range(len(prof) - 1, -1, -1):
                run = run + 1 if prof[r] > 0.45 * hi_ else 0
                if run >= int(0.10 / RES): sill_row = r + run - 1; break
            if sill_row is not None:
                new_sill = ceil_m - (y0 + sill_row) * RES
                if 0.3 <= new_sill <= 1.4: y1 = y0 + sill_row
        if False:
            band_rows = gy[y0:y1, x0:x1].mean(1); busy = cv2.blur(gx + gy, (int(0.15 / RES) | 1, int(0.15 / RES) | 1))[y0:y1, x0:x1].mean(1)
            thr_line = max(band_rows.mean() + 2.0 * band_rows.std(), 1e-6); cand_rows = [r for r in range(len(band_rows)) if band_rows[r] > thr_line and 0.4 / RES < r < len(band_rows) - 0.05 / RES]
            best_r = None
            for r in cand_rows:
                above = busy[max(0, r - int(0.4 / RES)):r].mean() if r > 2 else 0; below = busy[r + int(0.05 / RES):min(len(busy), r + int(0.45 / RES))].mean() if r + 6 < len(busy) else 0
                if above > 1.3 * below + 1e-6 and (best_r is None or r > best_r): best_r = r
            if best_r is not None and (ceil_m - (y0 + best_r) * RES) > 0.3: y1 = y0 + best_r
        sill = ceil_m - y1 * RES; top = ceil_m - y0 * RES; width = (x1 - x0) * RES; height = top - sill
        kind = "door" if sill < 0.2 and height > 1.7 and width < 1.6 else ("passage" if sill < 0.2 and height > 1.7 else "window")
        bf = float(beyond_frac[y0:y1, x0:x1].mean()); br = float(bright[y0:y1, x0:x1].mean()); cf = float(colourful[y0:y1, x0:x1].mean()); sf = float(seen[y0:y1, x0:x1].mean())
        if sf < 0.15 or (bf < 0.08 and br < 0.12 and cf < 0.08): continue   # detector prior alone is not evidence
        if bf > 0.4 and sill < 0.6 and height > 1.4: kind = "passage" if width > 1.3 else "door"; height += sill; sill = 0.0; y1 = int(ceil_m / RES)
        out.append({"kind": kind, "edge": f["k"], "s0": round(x0 * RES, 3), "s1": round(x1 * RES, 3), "sill_m": round(sill, 3), "height_m": round(height, 3), "width_m": round(width, 3),
                    "beyond": round(bf, 2), "bright": round(br, 2), "tex_box": [int(x0), int(y0), int(x1), int(y1)]})
    return out, score

def wall_texture(A, f, ceil_m, wall_col):
    import lama
    n_at = A["n_at"]; seen = n_at > 0; img = np.zeros((f["ny"], f["nx"], 3), np.uint8)
    if seen.any(): img[seen] = np.clip(A["col"][seen] / n_at[seen][:, None], 0, 255).astype(np.uint8)
    # pinholes between projected pixels: fill from neighbours, then treat as seen (the region was observed, only sparsely)
    if seen.any():
        dense = cv2.morphologyEx(seen.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)).astype(bool)
        holes = dense & ~seen
        if holes.any(): img = cv2.inpaint(img, holes.astype(np.uint8) * 255, 2, cv2.INPAINT_TELEA); seen = dense
        # isolated dark specks (depth-edge pixels, outliers) are not wall: treat as unseen so they get inpainted
        lum = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY); med = np.median(lum[seen]) if seen.any() else 128
        dark = (lum < med - 45) & seen; n_, lab_, st_, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8))
        small = np.zeros_like(dark)
        for j in range(1, n_):
            if st_[j, cv2.CC_STAT_AREA] < int(0.04 / (RES * RES)): small |= lab_ == j
        seen = seen & ~small
    frac = float(seen.mean())
    if frac > 0.995: return img, seen
    if frac > 0.03:
        img2 = flat_field(img, seen); own = np.median(img2[seen].reshape(-1, 3), 0).astype(np.uint8); img2[~seen] = own   # this wall's own colour
        img2 = lama.inpaint(img2, ~seen)
    else:
        img2 = np.tile(wall_col, (img.shape[0], img.shape[1], 1)).astype(np.uint8)
    return img2, seen

def outside_view(A, box):
    x0, y0, x1, y1 = box; nb = A["n_beyond"][y0:y1, x0:x1]; col = A["beyond_col"][y0:y1, x0:x1]; nany = A["n_any"][y0:y1, x0:x1]; call = A["col"][y0:y1, x0:x1]
    img = np.zeros(nb.shape + (3,), np.uint8); has = nb > 0; img[has] = np.clip(col[has] / nb[has][:, None], 0, 255).astype(np.uint8)
    # where nothing was seen beyond, use whatever the window texels showed (glass pixels), else sky
    rest = ~has & (A["n_at"][y0:y1, x0:x1] > 0); img[rest] = np.clip(call[rest] / A["n_at"][y0:y1, x0:x1][rest][:, None], 0, 255).astype(np.uint8)
    none = ~has & ~rest; img[none] = (200, 215, 235)
    if none.mean() < 0.9 and (has | rest).any():
        import lama; img = lama.inpaint(img, none)
    return img, float(has.mean())
