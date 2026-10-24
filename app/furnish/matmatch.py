#!/usr/bin/env python
"""Match listing-photo surfaces to the material library.
CLI: matmatch.py <listing_dir> <photo index>  -> JSON {"floor":[{id,score,cos,dE}], "wall":[...], "door":[...], "fixture":[...]}
"""
import json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matlib

LAB = {"floor": 1, "ceil": 2, "wall": 3, "door": 5, "fixture": 7}
ALLOW = {  # surface -> allowed material categories
    "floor": {"wood_floor", "tile", "carpet", "stone", "concrete", "laminate"},
    "wall": {"plaster", "paint", "tile", "brick", "concrete", "stone"},
    "door": {"laminate", "wood_floor", "paint", "metal"},
    "fixture": {"laminate", "metal", "stone", "paint", "tile", "wood_floor"},
}
MINPX = {"floor": 40, "wall": 40, "door": 24, "fixture": 24}  # min square side in full-res px
_model = None

def clip_model():
    global _model
    if _model is None:
        import torch, open_clip
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        m, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        _model = (m.eval().to(dev), pre, dev, torch)
    return _model

def embed(imgs):
    m, pre, dev, torch = clip_model()
    out = []
    with torch.no_grad():
        for i in range(0, len(imgs), 32):
            x = torch.stack([pre(im.convert("RGB")) for im in imgs[i:i + 32]]).to(dev)
            f = m.encode_image(x).float(); f = f / f.norm(dim=-1, keepdim=True)
            out.append(f.cpu().numpy())
    return np.concatenate(out)

def ensure_clip(index):
    todo = [m for m in index if "clip" not in m]
    if todo:
        E = embed([Image.open(os.path.join(matlib.MAT, m["id"], "thumb.jpg")) for m in todo])
        for m, e in zip(todo, E): m["clip"] = [round(float(x), 5) for x in e]
        json.dump(index, open(matlib.INDEX, "w"))
    return index

def largest_square(mask, step=4, erode=2):
    """Largest axis-aligned square fully inside mask (after erosion). Returns (x,y,side) in full-res px or None."""
    from scipy.ndimage import binary_erosion
    m = mask[::step, ::step]
    if erode: m = binary_erosion(m, iterations=erode)
    H, W = m.shape
    dp = np.zeros((H, W), np.int32)
    for y in range(H):
        for x in range(W):
            if m[y, x]:
                dp[y, x] = 1 + (min(dp[y - 1, x], dp[y, x - 1], dp[y - 1, x - 1]) if y and x else 0)
    s = dp.max()
    if s == 0: return None
    y, x = np.unravel_index(dp.argmax(), dp.shape)
    return (x - s + 1) * step, (y - s + 1) * step, s * step

def patches(photo, labels):
    W, H = photo.size
    lab = np.asarray(Image.fromarray(labels.astype(np.uint8)).resize((W, H), Image.NEAREST))
    out = {}
    for name, v in LAB.items():
        if name == "ceil": continue
        sq = largest_square(lab == v, step=max(2, W // 400))
        if sq and sq[2] >= MINPX[name]:
            x, y, s = sq; out[name] = ((x, y, s), photo.crop((x, y, x + s, y + s)).resize((224, 224), Image.LANCZOS))
    return out

def rgb2lab(rgb):
    c = np.asarray(rgb, float).reshape(-1, 3) / 255
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]]) / np.array([0.95047, 1, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)

def dE(rgb_a, rgbs_b, wl=0.5):
    a = rgb2lab(rgb_a)[0]; b = rgb2lab(rgbs_b)
    d = b - a; d[:, 0] *= wl   # lightness down-weighted: photos are lit differently from flat albedo
    return np.sqrt((d ** 2).sum(1))

def match(listing_dir, idx, k=3, pool=15, lam=0.004):
    index = ensure_clip(matlib.load_index())
    photo = Image.open(os.path.join(listing_dir, f"{int(idx):02d}.jpg")).convert("RGB")
    labels = np.load(os.path.join(listing_dir, f"{int(idx):02d}.seg.npz"))["labels"]
    P = patches(photo, labels)
    res = {n: [] for n in ("floor", "wall", "door", "fixture")}
    boxes = {}
    for name, (box, im) in P.items():
        boxes[name] = box
        cand = [m for m in index if m["category"] in ALLOW[name]]
        if not cand: continue
        C = np.array([m["clip"] for m in cand]); q = embed([im])[0]
        cos = C @ q
        top = np.argsort(-cos)[:pool]
        mean = np.asarray(im).reshape(-1, 3).mean(0)
        de = dE(mean, [cand[i]["mean_rgb"] for i in top])
        sc = cos[top] - lam * de
        for j in np.argsort(-sc)[:k]:
            m = cand[top[j]]
            res[name].append({"id": m["id"], "category": m["category"], "score": round(float(sc[j]), 4), "cos": round(float(cos[top[j]]), 4), "dE": round(float(de[j]), 1)})
    res["_patches"] = {n: list(map(int, b)) for n, b in boxes.items()}
    return res, P

def contact_sheet(tests, out):
    from PIL import ImageDraw
    T = 200; rows = []
    sheet = Image.new("RGB", (T * 5 + 10, (T + 20) * len(tests)), "white"); dr = ImageDraw.Draw(sheet)
    for r, (ld, idx) in enumerate(tests):
        res, P = match(ld, idx)
        y = r * (T + 20)
        photo = Image.open(os.path.join(ld, f"{int(idx):02d}.jpg")).convert("RGB"); photo.thumbnail((T, T))
        sheet.paste(photo, (0, y + 20)); dr.text((2, y + 4), f"{os.path.basename(ld)}/{idx}", fill="black")
        if "floor" in P:
            sheet.paste(P["floor"][1].resize((T, T)), (T + 10, y + 20)); dr.text((T + 12, y + 4), "floor patch", fill="black")
        for j, m in enumerate(res["floor"]):
            x = (2 + j) * T + 10
            sheet.paste(Image.open(os.path.join(matlib.MAT, m["id"], "thumb.jpg")).resize((T, T)), (x, y + 20))
            dr.text((x + 2, y + 4), f"{m['id'][:22]} {m['score']:.2f}", fill="black")
    sheet.save(out, quality=90)

if __name__ == "__main__":
    if sys.argv[1] == "--sheet":
        L = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "feasibility", "listings")
        contact_sheet([(f"{L}/gs-20665", 0), (f"{L}/gs-20665", 11), (f"{L}/gs-20665", 13), (f"{L}/gs-22612", 3)], os.path.join(matlib.MAT, "match_test.jpg")); sys.exit()
    r, _ = match(sys.argv[1], sys.argv[2])
    print(json.dumps(r, indent=1))
