"""LaMa inpainting (TorchScript big-lama) for wall and floor textures: fills unseen regions with plausible texture, no objects."""
import torch, numpy as np, pathlib, threading
_W = pathlib.Path(__file__).resolve().parents[2] / "feasibility/weights/big-lama.pt"; _model = None; _lock = threading.Lock()
def model():
    global _model
    with _lock:
        if _model is None: _model = torch.jit.load(str(_W), map_location="cpu").eval()
    return _model
def inpaint(img_u8, mask_bool, min_side=256):
    """img (H,W,3) uint8, mask True where to fill. Returns (H,W,3) uint8."""
    H, W = mask_bool.shape; s = max(1.0, min_side / max(1, min(H, W)))
    import cv2
    h, w = int(np.ceil(H * s / 8) * 8), int(np.ceil(W * s / 8) * 8)
    im = cv2.resize(img_u8, (w, h), interpolation=cv2.INTER_LINEAR); mk = cv2.resize(mask_bool.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
    mk = cv2.dilate(mk, np.ones((3, 3), np.uint8))
    x = torch.from_numpy(im).permute(2, 0, 1)[None].float() / 255.0; m = torch.from_numpy(mk)[None, None].float()
    with torch.no_grad(): out = model()(x, m)[0].permute(1, 2, 0).clamp(0, 1).numpy()
    out = cv2.resize((out * 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_AREA)
    res = img_u8.copy(); res[mask_bool] = out[mask_bool]; return res
