"""Pipeline 2, stage 3: semantic segmentation (Mask2Former, ADE20K) -> our labels, cached per photo."""
import sys, json, pathlib, numpy as np, torch
from PIL import Image
OTHER, FLOOR, CEIL, WALL, WINDOW, DOOR, MIRROR, FIXTURE, FURNITURE = range(9)
NAMES = ["other", "floor", "ceiling", "wall", "window", "door", "mirror", "fixture", "furniture"]
ADE = {"wall": WALL, "painting": WALL, "picture": WALL, "column": WALL, "pillar": WALL, "wallpaper": WALL, "fireplace": WALL,
       "floor": FLOOR, "rug": FLOOR, "carpet": FLOOR, "mat": FLOOR,
       "ceiling": CEIL, "chandelier": CEIL, "ceiling lamp": CEIL,
       "windowpane": WINDOW, "window": WINDOW, "blind": WINDOW, "sky": WINDOW, "screen door": WINDOW, "curtain": WINDOW, "shade": WINDOW,
       "door": DOOR, "double door": DOOR, "screen": DOOR,
       "mirror": MIRROR,
       "radiator": FIXTURE, "cabinet": FIXTURE, "kitchen island": FIXTURE, "counter": FIXTURE, "countertop": FIXTURE, "stove": FIXTURE, "oven": FIXTURE, "refrigerator": FIXTURE, "sink": FIXTURE,
       "bathtub": FIXTURE, "toilet": FIXTURE, "shower": FIXTURE, "wardrobe": FIXTURE, "bookcase": FIXTURE, "shelf": FIXTURE, "dishwasher": FIXTURE, "washer": FIXTURE, "microwave": FIXTURE, "hood": FIXTURE, "fan": CEIL,
       "bed": FURNITURE, "sofa": FURNITURE, "armchair": FURNITURE, "chair": FURNITURE, "table": FURNITURE, "coffee table": FURNITURE, "desk": FURNITURE, "chest of drawers": FURNITURE, "stool": FURNITURE, "lamp": FURNITURE, "plant": FURNITURE, "television receiver": FURNITURE, "cushion": FURNITURE, "pillow": FURNITURE}
_m = None
def model():
    global _m
    if _m is None:
        from transformers import AutoImageProcessor, Mask2FormerForUniversalSegmentation
        name = "facebook/mask2former-swin-large-ade-semantic"; proc = AutoImageProcessor.from_pretrained(name); net = Mask2FormerForUniversalSegmentation.from_pretrained(name).eval()
        dev = "mps" if torch.backends.mps.is_available() else "cpu"; net = net.to(dev); lut = np.zeros(len(net.config.id2label), np.uint8)
        for i, n in net.config.id2label.items(): lut[int(i)] = ADE.get(n.split(",")[0].strip(), OTHER)
        _m = (proc, net, dev, lut)
    return _m

def segment(path, cache=True):
    p = pathlib.Path(path); c = p.with_suffix(".seg.npz")
    if cache and c.exists(): d = np.load(c); return d["labels"], d["ade"]
    proc, net, dev, lut = model(); im = Image.open(p).convert("RGB"); inp = proc(images=im, return_tensors="pt").to(dev)
    with torch.no_grad(): out = net(**inp)
    ade = proc.post_process_semantic_segmentation(out, target_sizes=[im.size[::-1]])[0].cpu().numpy().astype(np.int16); lab = lut[ade]
    if cache: np.savez_compressed(c, labels=lab, ade=ade)
    return lab, ade

PAL = np.array([[60, 60, 60], [170, 120, 60], [220, 220, 230], [200, 190, 170], [40, 200, 255], [255, 60, 200], [255, 230, 40], [120, 90, 160], [60, 170, 90]], np.uint8)
def overlay(img, lab, alpha=0.55):
    img = np.asarray(img); return (img * (1 - alpha) + PAL[lab] * alpha).astype(np.uint8)

if __name__ == "__main__":
    import time, glob
    for d in sys.argv[1:]:
        t = time.time(); files = sorted(glob.glob(str(pathlib.Path(d) / "*.jpg"))); stats = {}
        for f in files:
            lab, _ = segment(f); ids, cnt = np.unique(lab, return_counts=True)
            for i, c in zip(ids, cnt): stats[NAMES[i]] = stats.get(NAMES[i], 0) + float(c) / lab.size / len(files)
        print(f"[seg] {pathlib.Path(d).name}: {len(files)} photos in {time.time()-t:.0f}s; mean fractions " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(stats.items(), key=lambda x: -x[1])))
