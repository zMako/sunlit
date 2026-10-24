"""Equirectangular panorama math. Frame: x right, y up, z forward; lon in (-pi, pi] measured from +z toward +x; lat up.
Panorama arrays are (H, W, 3) uint8 with a boolean 'known' mask alongside."""
import numpy as np, cv2

def dirs(W, H):
    lon = ((np.arange(W) + 0.5) / W * 2 - 1) * np.pi; lat = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    LON, LAT = np.meshgrid(lon, lat); cl = np.cos(LAT)
    return np.stack([cl * np.sin(LON), np.sin(LAT), cl * np.cos(LON)], -1).astype(np.float32)   # (H, W, 3)

def rot(yaw=0.0, pitch=0.0, roll=0.0):
    cy, sy, cp, sp, cr, sr = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch), np.cos(roll), np.sin(roll)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]); Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]]); Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return (Ry @ Rx @ Rz).astype(np.float32)   # cam -> world; pitch > 0 looks up

def lonlat_to_px(d, W, H):
    lon = np.arctan2(d[..., 0], d[..., 2]); lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    return ((lon / np.pi + 1) / 2 * W - 0.5).astype(np.float32), ((0.5 - lat / np.pi) * H - 0.5).astype(np.float32)

def view_rays(N, fov_deg, R):
    f = (N / 2) / np.tan(np.radians(fov_deg) / 2); u, v = np.meshgrid(np.arange(N) + 0.5, np.arange(N) + 0.5)
    c = np.stack([(u - N / 2) / f, -(v - N / 2) / f, np.ones_like(u)], -1); c /= np.linalg.norm(c, axis=-1, keepdims=True)
    return (c @ R.T).astype(np.float32)

def render_view(pano, known, N, fov_deg, R):
    """Perspective crop of the panorama: rgb (N,N,3), known (N,N) bool."""
    H, W = known.shape; d = view_rays(N, fov_deg, R); mx, my = lonlat_to_px(d, W, H)
    rgb = cv2.remap(pano, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    kn = cv2.remap(known.astype(np.uint8) * 255, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP) > 200
    return rgb, kn

def paste_image(pano, known, img, R, f_px, cx, cy, only_unknown=True, feather=24, D=None, nearest=False):
    """Project a perspective image (camera rotation R cam->world, focal f_px, principal point cx, cy) into the panorama.
    Pixels within 'feather' px of the image border get a soft weight so seams blend."""
    H, W = known.shape; h, w = img.shape[:2]
    D = dirs(W, H) if D is None else D; c = D @ R   # world -> cam: R^T applied as row vectors
    z = c[..., 2]; ok = z > 1e-3
    u = np.where(ok, f_px * c[..., 0] / np.where(ok, z, 1) + cx, -1); v = np.where(ok, -f_px * c[..., 1] / np.where(ok, z, 1) + cy, -1)
    inside = ok & (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
    if not inside.any(): return 0
    samp = cv2.remap(img, u.astype(np.float32), v.astype(np.float32), cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    wgt = np.clip(np.minimum(np.minimum(u, w - 1 - u), np.minimum(v, h - 1 - v)) / max(feather, 1), 0, 1); wgt = np.where(inside, wgt, 0)
    target = inside & (~known if only_unknown else np.ones_like(known))
    if only_unknown and not nearest:   # blend into the already-known neighbourhood a little so the seam is soft
        edge = inside & known & (cv2.dilate((inside & ~known).astype(np.uint8), np.ones((feather, feather), np.uint8)) > 0)
        a = (wgt * 0.5)[..., None]; pano[edge] = (pano[edge] * (1 - a[edge]) + samp[edge] * a[edge]).astype(np.uint8)
    pano[target] = samp[target]; known[target] = True
    return int(target.sum())

def sample(pano, d):
    """Bilinear lookup of directions d (..., 3) -> rgb."""
    H, W = pano.shape[:2]; mx, my = lonlat_to_px(d, W, H); shp = d.shape[:-1]
    n = int(np.prod(shp)); cols = min(n, 16384); rows = -(-n // cols); pad = rows * cols - n
    fx = np.concatenate([mx.ravel(), np.zeros(pad, np.float32)]).reshape(rows, cols); fy = np.concatenate([my.ravel(), np.zeros(pad, np.float32)]).reshape(rows, cols)
    out = cv2.remap(pano, fx, fy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP).reshape(-1, 3)[:n]
    return out.reshape(shp + (3,))
