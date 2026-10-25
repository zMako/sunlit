"""Fine-tune the CubiCasa5K wall model (cubi.py) on our plans with the reviewed labels (labels.py): wall / window / door
masks for the 300 training plans of labels/split.json (the 20 test plans are never seen).

Loss: the model's own heads, read as three binary questions: p(wall) from the room head, p(window) and p(door) from the icon
head (softmax marginals), binary cross-entropy + soft Dice, pixels outside the reviewed region ignored. Low learning rate,
batch-norm statistics frozen (small batches), random 512 px crops with rotation / flip / scale / colour jitter.

  finetune.py [--iters N] [--out PATH] [--bench]
  then: CUBI_WEIGHTS=PATH CUBI_TAG=ft1 cubi.py predict <test plans>; CUBI_TAG=ft1 labels.py score"""
import sys, os, json, time, random, pathlib
import numpy as np, cv2, torch, torch.nn.functional as F
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); import cubi, labels
CROP = 512

def load_plan(path):
    """image + labels cropped to the reviewed box (inference size), or None"""
    lp = labels.label_path(path); P = cubi.load(path, tag="")
    if not lp.exists() or P is None: return None
    Lb = np.load(lp); x0, y0, x1, y1 = [int(v) for v in Lb["box"]]
    if Lb["ignore"][y0:y1, x0:x1].mean() > 0.5: return None   # reviewer marked unusable
    img = np.asarray(Image.open(path).convert("RGB").resize(tuple(P["size"]), Image.LANCZOS))
    pad = 24; X0, Y0 = max(0, x0 - pad), max(0, y0 - pad); X1, Y1 = min(img.shape[1], x1 + pad), min(img.shape[0], y1 + pad)
    lab = np.stack([Lb["wall"], Lb["window"], Lb["door"], Lb["ignore"]], -1)[Y0:Y1, X0:X1].astype(np.uint8)
    return img[Y0:Y1, X0:X1].copy(), lab

def sample(data, rng):
    img, lab = data[rng.randrange(len(data))]
    s = rng.uniform(0.8, 1.25)   # wall thickness varies between plans: train around the 12 px target
    if abs(s - 1) > 0.03:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        lab = cv2.resize(lab, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    H, W = img.shape[:2]
    if H < CROP or W < CROP:   # pad with paper, ignored
        ph, pw = max(0, CROP - H), max(0, CROP - W)
        img = cv2.copyMakeBorder(img, 0, ph, 0, pw, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        lab = cv2.copyMakeBorder(lab, 0, ph, 0, pw, cv2.BORDER_CONSTANT, value=(0, 0, 0, 1)); H, W = img.shape[:2]
    for _ in range(6):   # prefer crops that hold walls
        y, x = rng.randrange(H - CROP + 1), rng.randrange(W - CROP + 1)
        if lab[y:y + CROP, x:x + CROP, 0].mean() > 0.01: break
    img, lab = img[y:y + CROP, x:x + CROP], lab[y:y + CROP, x:x + CROP]
    k = rng.randrange(4); img, lab = np.rot90(img, k), np.rot90(lab, k)
    if rng.random() < 0.5: img, lab = img[:, ::-1], lab[:, ::-1]
    img = img.astype(np.float32)
    if rng.random() < 0.3: img = np.repeat(img.mean(-1, keepdims=True), 3, -1)   # grey plans
    img = np.clip((img - 128) * rng.uniform(0.8, 1.2) + 128 + rng.uniform(-20, 20) + np.array([rng.uniform(-12, 12) for _ in range(3)]), 0, 255)
    return np.ascontiguousarray(img, dtype=np.float32), np.ascontiguousarray(lab)

def marginal_bce_dice(logits, c, y, valid, pos_w=1.0):
    """BCE + soft Dice of p(class c) = softmax(logits)[c] against y, on valid pixels"""
    lse = torch.logsumexp(logits, 1); lp = logits[:, c] - lse
    rest = logits.clone(); rest[:, c] = -1e4; l1mp = torch.logsumexp(rest, 1) - lse
    bce = -(pos_w * y * lp + (1 - y) * l1mp); bce = (bce * valid).sum() / valid.sum().clamp(min=1)
    p = lp.exp() * valid; yv = y * valid; dice = 1 - (2 * (p * yv).sum() + 1) / (p.sum() + yv.sum() + 1)
    return bce + dice

def main():
    a = sys.argv[1:]; iters = int(a[a.index("--iters") + 1]) if "--iters" in a else 2500
    out = pathlib.Path(a[a.index("--out") + 1]) if "--out" in a else ROOT / "feasibility/weights/cubicasa_ft1.pt"
    bench = "--bench" in a; rng = random.Random(0); torch.manual_seed(0)
    S = json.load(open(labels.LAB / "split.json")); t0 = time.time()
    data = [d for d in (load_plan(p) for p in S["train"]) if d is not None]
    print(f"[ft] {len(data)} training plans loaded in {time.time() - t0:.0f}s", flush=True)
    model, dev = cubi.load_model(); model.train()
    for m in model.modules():   # frozen batch-norm statistics: batches of 4 crops are too small to re-estimate them
        if isinstance(m, torch.nn.BatchNorm2d): m.eval(); m.weight.requires_grad_(False); m.bias.requires_grad_(False)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=3e-5, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-5, total_steps=iters, pct_start=0.05)
    B = 4; t0 = time.time(); hist = []
    for it in range(1, iters + 1):
        batch = [sample(data, rng) for _ in range(B)]
        x = torch.from_numpy(np.stack([b[0] for b in batch])).permute(0, 3, 1, 2).to(dev) / 127.5 - 1
        lab = torch.from_numpy(np.stack([b[1] for b in batch])).permute(0, 3, 1, 2).float().to(dev)
        o = model(x); o = F.interpolate(o, size=x.shape[2:], mode="bilinear", align_corners=True)
        valid = 1 - lab[:, 3]; rooms, icons = o[:, 21:33], o[:, 33:44]
        lw = marginal_bce_dice(rooms, cubi.WALL, lab[:, 0], valid)
        lwin = marginal_bce_dice(icons, cubi.WINDOW, lab[:, 1], valid, pos_w=2.0)
        ldoor = marginal_bce_dice(icons, cubi.DOOR, lab[:, 2], valid, pos_w=2.0)
        loss = lw + 0.7 * lwin + 0.7 * ldoor
        opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step()
        hist.append([lw.item(), lwin.item(), ldoor.item()])
        if bench and it == 10: print(f"[ft] bench: {(time.time() - t0) / 10:.2f} s/iter", flush=True); return
        if it % 50 == 0:
            h = np.mean(hist[-50:], 0); print(f"[ft] {it}/{iters} wall {h[0]:.3f} window {h[1]:.3f} door {h[2]:.3f}  {(time.time() - t0) / it:.2f} s/it", flush=True)
        if it % 500 == 0 or it == iters:
            torch.save({"model_state": model.state_dict(), "iter": it, "loss": hist[-1]}, out); print(f"[ft] saved {out} @ {it}", flush=True)
    print(f"[ft] done in {time.time() - t0:.0f}s", flush=True)

if __name__ == "__main__": main()
