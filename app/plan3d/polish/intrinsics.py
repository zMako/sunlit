"""Single-image intrinsics per listing photo: letterbox-crop the photo, run VGGT on that one image (MPS), hfov from fx.
Writes polish/work/intrinsics.json {"<lid>/<NN>": {crop, hfov_deg, vfov_deg, size}}. Fallback 65 deg hfov if VGGT fails."""
import sys, json, math, pathlib, numpy as np
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[2]
for p in ("app/pipeline", "app/pipeline2/wallwrap"): sys.path.insert(0, str(ROOT / p))
import geom
sys.path.insert(0, str(HERE)); from common import pad_crop
PHOTOS = [("gs-22612", "03"), ("gs-22612", "04"), ("gs-22612", "05"), ("gs-20665", "11"), ("gs-20665", "13"), ("gs-20665", "17"), ("gs-20665", "18")]
out = {}; work = HERE / "work"; work.mkdir(exist_ok=True)
try:
    import recon; ok = True
except Exception as e: print("VGGT unavailable", e); ok = False
for lid, n in PHOTOS:
    img = np.asarray(Image.open(ROOT / f"feasibility/listings/{lid}/{n}.jpg").convert("RGB")); crop = pad_crop(img)
    x0, y0, x1, y1 = crop; c = Image.fromarray(img[y0:y1, x0:x1]); cp = work / f"{lid}_{n}_crop.jpg"; c.save(cp, quality=95)
    hf = 65.0; src = "fallback"
    if ok:
        try:
            P = recon.run([cp]); K = P["intrinsic"][0]; W = 518.0
            hf = math.degrees(2 * math.atan(W / 2 / K[0, 0])); src = "vggt"
        except Exception as e: print("vggt failed", lid, n, e)
    w, h = c.size; vf = math.degrees(2 * math.atan(math.tan(math.radians(hf) / 2) * h / w))
    out[f"{lid}/{n}"] = {"crop": [int(v) for v in crop], "size": [w, h], "hfov_deg": round(hf, 2), "vfov_deg": round(vf, 2), "source": src}
    print(lid, n, out[f"{lid}/{n}"])
json.dump(out, open(work / "intrinsics.json", "w"), indent=1)
