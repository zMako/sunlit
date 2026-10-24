"""Shared helpers for the polish side-by-side: photo list, letterbox crop (white padding bars only; geom.letterbox is fooled
by flat white walls), paths."""
import pathlib, numpy as np
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[2]; LIST = ROOT / "feasibility/listings"
def pad_crop(img, thr=245):
    """img HxWx3 uint8 -> (x0, y0, x1, y1): strips columns/rows whose every pixel is near-white (the gallery's padding)."""
    H, W = img.shape[:2]; cm = img.min(axis=(0, 2)); rm = img.min(axis=(1, 2))
    x0 = 0
    while x0 < W // 3 and cm[x0] >= thr: x0 += 1
    x1 = W
    while x1 > 2 * W // 3 and cm[x1 - 1] >= thr: x1 -= 1
    y0 = 0
    while y0 < H // 3 and rm[y0] >= thr: y0 += 1
    y1 = H
    while y1 > 2 * H // 3 and rm[y1 - 1] >= thr: y1 -= 1
    if x0 > 0: x0 += 1
    if x1 < W: x1 -= 1
    return x0, y0, x1, y1
