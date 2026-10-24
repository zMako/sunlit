"""Overlay of the detected wall faces (floor line green, ceiling line magenta, face splits yellow) for each photo -> work/faces_<lid>_<n>.jpg"""
import sys, json, pathlib, numpy as np, cv2
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import cameras as C
for lid, n, *_ in C.PAIRS:
    info = C.INTR[f"{lid}/{n}"]; x0, y0, x1, y1 = info["crop"]; img = np.asarray(Image.open(C.LIST / f"{lid}/{n}.jpg").convert("RGB"))[y0:y1, x0:x1].copy()
    lab = np.load(C.LIST / f"{lid}/{n}.seg.npz")["labels"].astype(np.uint8)
    faces, yf, yc = C.geom.faces_from_masks(lab, C.WALLISH, C.FLOOR, C.CEIL, tuple(info["crop"]))
    L = lab[y0:y1, x0:x1]; col = np.array([[0,0,0],[255,160,0],[0,120,255],[200,200,200],[0,255,255],[255,0,0],[255,0,255],[0,255,0],[128,0,128]], np.uint8)
    img = (img * 0.6 + col[L] * 0.4).astype(np.uint8)
    for k, f in enumerate(faces):
        for key, c in (("floor", (0, 255, 0)), ("ceil", (255, 0, 255))):
            if f[key]: m, b = f[key]; cv2.line(img, (int(f["x0"]), int(m * f["x0"] + b)), (int(f["x1"]), int(m * f["x1"] + b)), c, 3)
        cv2.line(img, (int(f["x0"]), 0), (int(f["x0"]), img.shape[0]), (255, 255, 0), 1); cv2.putText(img, str(k), (int((f["x0"] + f["x1"]) / 2), 30), 0, 1, (255, 255, 0), 2)
    Image.fromarray(img).save(HERE / f"work/faces_{lid}_{n}.jpg")
