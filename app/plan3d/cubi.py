"""Learned wall/window/door segmentation for floor plans: CubiCasa5K (Kalervo et al. 2019, hg_furukawa_original, weights
CC BY-NC 4.0) run on our plans. Plans are rescaled so walls are ~12 px thick (the training data's median), predicted with
4-rotation test-time averaging, and cropped to the main drawing automatically (key plans, logos, titles and page margins
dropped; two-level townhouse plans keep both levels).

Cache per plan image, next to it: cubi_<stem>.npz (rooms, icons, crop at inference size) + cubi_<stem>.json (scale, levels).
Usage: [CUBI_WEIGHTS=... CUBI_TAG=ft1] cubi.py predict [--force] [plan images ...]   (no images: every feasibility/listings/*/plans/plan_*)"""
import sys, os, json, glob, pathlib, time
import numpy as np, cv2
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]
REPO = ROOT / "feasibility" / "cubicasa5k_repo"
WEIGHTS = pathlib.Path(os.environ.get("CUBI_WEIGHTS") or ROOT / "feasibility" / "weights" / "cubicasa_model_best_val_loss_var.pkl")
TAG = os.environ.get("CUBI_TAG", "")   # cache suffix for predictions from other weights (fine-tuned): cubi_<stem>_<tag>.npz
# what the engine uses (masks_at): walls + crop + levels from the fine-tuned model (ft1: fixes 74% of the reviewed wall errors on
# held-out plans), windows + doors from the pretrained one (the fine-tune made them slightly worse); either falls back to the
# pretrained cache when its own is missing
WALLS_TAG = os.environ.get("CUBI_WALLS_TAG", "ft1"); ICONS_TAG = os.environ.get("CUBI_ICONS_TAG", "")
TARGET_T = 12.0; MAX_SIDE = 2200
ROOM_CLASSES = ["Background", "Outdoor", "Wall", "Kitchen", "Living Room", "Bed Room", "Bath", "Entry", "Railing", "Storage", "Garage", "Undefined"]
ICON_CLASSES = ["No Icon", "Window", "Door", "Closet", "Electrical Appliance", "Toilet", "Sink", "Sauna Bench", "Fire Place", "Bathtub", "Chimney"]
WALL, WINDOW, DOOR = 2, 1, 2   # rooms channel: wall; icons channel: window, door
_model = None; _dev = None

def load_model(weights=None):
    global _model, _dev
    if _model is not None: return _model, _dev
    import torch
    sys.path.insert(0, str(REPO)); from floortrans.models import get_model
    cwd = os.getcwd(); os.chdir(REPO)   # get_model loads floortrans/models/model_1427.pth by relative path
    try: m = get_model("hg_furukawa_original", 51)
    finally: os.chdir(cwd)
    m.conv4_ = torch.nn.Conv2d(256, 44, bias=True, kernel_size=1); m.upsample = torch.nn.ConvTranspose2d(44, 44, kernel_size=4, stride=4)
    ck = torch.load(str(weights or WEIGHTS), map_location="cpu", weights_only=False); m.load_state_dict(ck["model_state"] if "model_state" in ck else ck)
    _dev = torch.device("mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu"))
    _model = m.eval().to(_dev); return _model, _dev

def plan_scale(path):
    """Factor that brings the plan's wall strokes to ~TARGET_T px, capped by MAX_SIDE."""
    sys.path.insert(0, str(HERE)); from plan_engine import load_ink, wall_thickness
    im = Image.open(path); side = max(im.size); side_eff = min(side, 4000)
    g, ink, s = load_ink(path, max_side=side_eff); t = wall_thickness(ink) / s   # thickness in original px (load_ink scales by s)
    return min(TARGET_T / max(t, 1.0), MAX_SIDE / side), t

def logits(rgb):
    """Rooms (12) + icons (11) logits averaged over 4 rotations, at the input size."""
    import torch, torch.nn.functional as F
    m, dev = load_model()
    x = torch.from_numpy(2 * (rgb.astype(np.float32) / 255.0) - 1).permute(2, 0, 1)[None]
    H, W = x.shape[2:]; x = F.pad(x, (0, (-W) % 64, 0, (-H) % 64), value=1.0).to(dev); acc = None
    with torch.no_grad():
        for k in range(4):
            p = m(torch.rot90(x, k, (2, 3))); p = torch.rot90(p, -k, (2, 3))
            p = F.interpolate(p, size=x.shape[2:], mode="bilinear", align_corners=True)[:, 21:]
            acc = p if acc is None else acc + p
    return (acc[0, :, :H, :W] / 4).float().cpu().numpy()

def crop_levels(rooms):
    """Main drawing(s) from the predicted walls: each group of connected walls spans a footprint (its convex hull); keep the
    footprints >= 1/3 of the largest (both levels of a townhouse), drop key plans, logos, titles and the room-class blotches
    the model paints on empty paper (no walls, so no footprint)."""
    wall = (rooms == WALL).astype(np.uint8)
    k = int(TARGET_T * 3) | 1; wc = cv2.morphologyEx(wall, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(wc, 8)
    hulls = []
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 4 * TARGET_T * TARGET_T: continue
        pts = cv2.findNonZero((lab == i).astype(np.uint8)); h = cv2.convexHull(pts); hulls.append((float(cv2.contourArea(h)), h))
    if not hulls: return np.zeros_like(wall), []
    big = max(a for a, _ in hulls); keep = [(a, h) for a, h in hulls if a >= big / 3]
    crop = np.zeros_like(wall)
    for a, h in keep: cv2.fillPoly(crop, [h], 1)
    crop = cv2.dilate(crop, cv2.getStructuringElement(cv2.MORPH_RECT, (int(TARGET_T * 2) | 1,) * 2))   # keep the outer wall's full stroke
    levels = []
    for a, h in keep:
        x, y, ww, hh = cv2.boundingRect(h); levels.append({"bbox": [int(x), int(y), int(x + ww), int(y + hh)], "area_px": int(a)})
    levels.sort(key=lambda L: (L["bbox"][0] // 50, L["bbox"][1]))   # left to right, then top to bottom
    return crop, levels

def cache_paths(path, tag=None):
    p = pathlib.Path(path); t = TAG if tag is None else tag; sfx = f"_{t}" if t else ""
    return p.parent / f"cubi_{p.stem}{sfx}.npz", p.parent / f"cubi_{p.stem}{sfx}.json"

def predict(path, force=False):
    npz, meta = cache_paths(path)
    if npz.exists() and meta.exists() and not force: return load(path)
    t0 = time.time(); k, t_src = plan_scale(path)
    src = Image.open(path).convert("RGB"); W0, H0 = src.size
    im = src.resize((max(64, round(W0 * k)), max(64, round(H0 * k))), Image.LANCZOS)
    lg = logits(np.asarray(im)); rooms = lg[:12].argmax(0).astype(np.uint8); icons = lg[12:].argmax(0).astype(np.uint8)
    crop, levels = crop_levels(rooms)
    np.savez_compressed(npz, rooms=rooms, icons=icons, crop=crop)
    M = {"plan": str(path), "orig_size": [W0, H0], "size": list(im.size), "k": k, "wall_px_src": round(t_src, 2), "levels": levels,
         "weights": str(WEIGHTS.name), "sec": round(time.time() - t0, 2)}
    json.dump(M, open(meta, "w"), indent=1); return load(path)

def load(path, tag=None):
    npz, meta = cache_paths(path, tag)
    if not (npz.exists() and meta.exists()): return None
    d = np.load(npz); M = json.load(open(meta)); M.update(rooms=d["rooms"], icons=d["icons"], crop=d["crop"], tag=TAG if tag is None else tag); return M

def load_engine(path):
    """(walls source, icons source): the hybrid the engine uses, each falling back to the pretrained prediction"""
    Pw = load(path, WALLS_TAG) or load(path, ""); Pi = load(path, ICONS_TAG) or load(path, "")
    if Pw is not None and Pi is not None and Pw["rooms"].shape != Pi["icons"].shape: Pi = Pw   # predicted at different scales: no mixing
    return Pw, Pi

def masks_at(path, shape):
    """Cropped wall / window / door masks resampled to `shape` (H, W), e.g. plan_engine's work image. None if not predicted.
    Walls, crop and levels from WALLS_TAG, windows and doors from ICONS_TAG (see load_engine)."""
    P, Pi = load_engine(path)
    if P is None: return None
    H, W = shape; rs = lambda a: cv2.resize(a.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    crop = rs(P["crop"]); out = {"crop": crop, "walls_tag": P.get("tag", ""), "icons_tag": Pi.get("tag", "")}
    out["wall"] = rs(P["rooms"] == WALL) & crop; out["window"] = rs(Pi["icons"] == WINDOW) & crop; out["door"] = rs(Pi["icons"] == DOOR) & crop
    out["rooms"] = rs(P["rooms"]) * crop; out["levels"] = [{"bbox": [v * W / P["size"][0] if j % 2 == 0 else v * H / P["size"][1] for j, v in enumerate(L["bbox"])], "area_px": L["area_px"]} for L in P["levels"]]
    return out

def preview(path, out=None, max_side=1100):
    """Plan at inference size: outside the crop dimmed, walls red, windows cyan, doors green; level boxes in magenta."""
    P = load(path); src = Image.open(path).convert("RGB").resize(tuple(P["size"]), Image.LANCZOS)
    a = np.asarray(src).astype(np.float32); o = a.copy(); crop = P["crop"].astype(bool)
    o[~crop] = 0.35 * a[~crop] + 0.65 * 235
    for m, col in [(P["rooms"] == WALL, (220, 38, 38)), (P["icons"] == WINDOW, (6, 182, 212)), (P["icons"] == DOOR, (22, 163, 74))]:
        m = m & crop; o[m] = 0.35 * a[m] + 0.65 * np.array(col)
    im = Image.fromarray(o.astype(np.uint8)); from PIL import ImageDraw; d = ImageDraw.Draw(im)
    for L in P["levels"]: d.rectangle(L["bbox"], outline=(200, 0, 200), width=3)
    z = min(1.0, max_side / max(im.size)); im = im.resize((int(im.width * z), int(im.height * z)), Image.LANCZOS)
    if out: im.save(out, quality=88)
    return im

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "predict":
        force = "--force" in args; rest = [a for a in args[1:] if not a.startswith("--")]
        paths = rest or sorted(p for p in glob.glob(str(ROOT / "feasibility/listings/*/plans/plan_*.*")) if p.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
        load_model(); t0 = time.time(); n_ok = 0
        for i, p in enumerate(paths):
            try:
                M = predict(p, force=force); n_ok += 1
                if i % 25 == 0: print(f"[cubi] {i + 1}/{len(paths)} {p.split('listings/')[-1]} k {M['k']:.2f} levels {len(M['levels'])} {M['sec']}s  ({time.time() - t0:.0f}s)", flush=True)
            except Exception as e: print(f"[cubi] FAIL {p}: {type(e).__name__} {e}", flush=True)
        print(f"[cubi] done {n_ok}/{len(paths)} in {time.time() - t0:.0f}s", flush=True)
    else: print(__doc__)
