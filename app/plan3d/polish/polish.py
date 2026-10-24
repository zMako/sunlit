"""Polish a photo-matched render with SD 1.5 at LOW strength: depth ControlNet (control_v11f1p_sd15_depth) fed with OUR
render's depth pass, IP-Adapter fed with the listing photo (style/lighting reference), prompt from photo_facts.
The only SD 1.5 weights cached locally are the inpainting checkpoint used by app/pipeline2/complete.py, so this reuses
complete.pipe() and runs it as img2img: mask = whole image, strength 0.25-0.4 (the denoiser starts from the noised render,
so layout and objects stay where the solver put them). Writes out/<photo>/polished.png, compare.png, meta.json.
Usage: polish.py [photo-filter] [--strength 0.3] [--steps 24] [--ip 0.5] [--cn 0.9]"""
import sys, json, time, argparse, pathlib, numpy as np, torch
from PIL import Image, ImageDraw, ImageFont
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "app/pipeline2")); sys.path.insert(0, str(HERE))
from common import LIST
NEG = "furniture changed, extra objects, extra furniture, people, text, watermark, logo, distorted, deformed, cartoon, painting, blurry, oversaturated"
CAT = {"wood_floor": "wood floor", "laminate": "laminate plank floor", "tile": "tile floor", "carpet": "carpet", "paint": "painted", "plaster": "smooth plaster"}

def colour_word(rgb):
    r, g, b = [v / 255 for v in rgb]; mx, mn = max(r, g, b), min(r, g, b); l = (mx + mn) / 2; s = 0 if mx == mn else (mx - mn) / (1 - abs(2 * l - 1) + 1e-6)
    if s < 0.12: return "white" if l > 0.8 else "light grey" if l > 0.6 else "grey" if l > 0.35 else "dark grey"
    warm = r >= b
    if warm: return ("light honey" if l > 0.55 else "honey brown" if l > 0.35 else "dark brown") if r > g * 1.05 else ("beige" if l > 0.6 else "olive")
    return "cool grey" if l > 0.5 else "blue grey"

def prompt_for(lid, n, room_type):
    pf = json.load(open(LIST / f"{lid}/photo_facts.json")); ph = next(x for x in pf["photos"] if x["index"] == int(n))
    idx = {m["id"]: m for m in json.load(open(ROOT / "app/furnish/materials/index.json"))}
    mat = ph.get("materials", {}); col = ph.get("colours", {})
    def mword(k):
        ids = mat.get(k) or []; m = idx.get(ids[0]) if ids else None; return CAT.get(m["category"], m["category"].replace("_", " ")) if m else ""
    floor = f"{colour_word(col['floor_rgb'])} {mword('floor') or 'wood floor'}" if col.get("floor_rgb") else mword("floor") or "wood floor"
    wall = "white painted walls"
    ceil = f"{colour_word(col['ceiling_rgb'])} ceiling" if col.get("ceiling_rgb") else "white ceiling"
    if "cedar" in (ph.get("room") or "").lower(): ceil = "warm cedar wood plank ceiling"
    win = "large windows with daylight" if ph.get("windows") else "natural light"
    return f"interior real-estate photo of a furnished {room_type}, {floor}, {wall}, {ceil}, {win}, natural light, photorealistic, sharp, high dynamic range"

def depth_control(depth_png, near=0.3, far=10.0):
    """our linear depth pass (grey = 1 - (z-near)/(far-near)) -> MiDaS-style normalised disparity image (near bright)."""
    g = np.asarray(Image.open(depth_png).convert("L")).astype(np.float32) / 255.0; z = near + (1 - g) * (far - near)
    disp = 1.0 / np.maximum(z, near); lo, hi = np.percentile(disp, 1), np.percentile(disp, 99.5); d = np.clip((disp - lo) / max(hi - lo, 1e-6), 0, 1)
    return Image.fromarray((d * 255).astype(np.uint8)).convert("RGB")

def work_size(w, h, long=768):
    s = long / max(w, h); return int(round(w * s / 8) * 8), int(round(h * s / 8) * 8)

def label(im, text, sub=None, H=58):
    W = im.width; c = Image.new("RGB", (W, im.height + H), (16, 20, 28)); c.paste(im, (0, H)); d = ImageDraw.Draw(c)
    try: f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22); fs = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    except Exception: f = fs = ImageFont.load_default()
    d.text((12, 6), text, fill=(240, 244, 250), font=f)
    if sub: d.text((12, 34), sub, fill=(160, 170, 185), font=fs)
    return c

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("filter", nargs="?", default=""); ap.add_argument("--strength", type=float, default=0.32)
    ap.add_argument("--steps", type=int, default=24); ap.add_argument("--ip", type=float, default=0.5); ap.add_argument("--cn", type=float, default=0.9); ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    import complete
    cams = json.load(open(HERE / "cameras.json")); intr = json.load(open(HERE / "work/intrinsics.json"))
    t0 = time.time(); P = complete.pipe(); print(f"pipeline ready in {time.time() - t0:.1f}s")
    for c in cams:
        if a.filter not in c["photo"]: continue
        lid, n = c["photo"].replace(".jpg", "").split("/"); key = f"{lid}_{n}"; d = HERE / "out" / key
        if not (d / "render.png").exists(): print("no render for", key); continue
        L = json.load(open(ROOT / f"app/plan3d/layouts/{c['unit']}.json")); room = next(r for r in L["rooms"] if r["id"] == c["room"])
        render = Image.open(d / "render.png").convert("RGB"); W, H = render.size; ws = work_size(W, H)
        x0, y0, x1, y1 = intr[f"{lid}/{n}"]["crop"]; photo = Image.open(LIST / f"{lid}/{n}.jpg").convert("RGB").crop((x0, y0, x1, y1))
        ctrl = depth_control(d / "depth.png"); ctrl.save(d / "control.png")
        prompt = prompt_for(lid, n, room["type"] if room["type"] != "living" else "living room")
        P.set_ip_adapter_scale(a.ip); g = torch.Generator(device="cpu").manual_seed(a.seed)
        mask = Image.new("L", ws, 255)
        t = time.time()
        out = P(prompt=prompt, negative_prompt=NEG, image=render.resize(ws, Image.LANCZOS), mask_image=mask, control_image=ctrl.resize(ws, Image.BILINEAR),
                ip_adapter_image=photo.resize((224, 224), Image.LANCZOS), num_inference_steps=a.steps, strength=a.strength, guidance_scale=6.0,
                controlnet_conditioning_scale=a.cn, generator=g, height=ws[1], width=ws[0]).images[0]
        if torch.backends.mps.is_available(): torch.mps.synchronize()
        sd_s = time.time() - t
        pol = out.resize((W, H), Image.LANCZOS); pol.save(d / "polished.png")
        # difference note: how much the polish moved pixels, and how far edges moved (structure check)
        import cv2
        ra = np.asarray(render.resize(ws)).astype(np.float32); pa = np.asarray(out).astype(np.float32)
        mad = float(np.abs(ra - pa).mean()); er = cv2.Canny(ra.astype(np.uint8), 80, 160) > 0; ep = cv2.Canny(pa.astype(np.uint8), 80, 160) > 0
        dt = cv2.distanceTransform((~ep).astype(np.uint8), cv2.DIST_L2, 3); edge_px = float(np.median(dt[er])) if er.any() else None
        kept = float((dt[er] <= 2).mean()) if er.any() else None
        note = f"polish changed pixels by {mad:.1f}/255 on average; {kept * 100:.0f}% of the render's edges are within 2 px in the polished image"
        meta = {"photo": c["photo"], "unit": c["unit"], "room": c["room"], "room_name": room["name"], "prompt": prompt, "negative": NEG, "strength": a.strength, "steps": a.steps,
                "ip_adapter_scale": a.ip, "controlnet_scale": a.cn, "seed": a.seed, "work_size": ws, "sd_seconds": round(sd_s, 1), "mean_abs_diff": round(mad, 2),
                "edges_kept_2px": round(kept, 3) if kept is not None else None, "note": note, "camera": {k: c[k] for k in ("pos", "yaw", "pitch", "fov")}}
        json.dump(meta, open(d / "meta.json", "w"), indent=1)
        # side-by-side: photo | render | polished, same height
        Ht = 480; sc = lambda im: im.resize((int(im.width * Ht / im.height), Ht), Image.LANCZOS)
        p1 = label(sc(photo), "Listing photo", f"{c['photo']}  (another unit's photo in the building gallery)" if lid.startswith("gs-") else c["photo"])
        p2 = label(sc(render), "Our furnished render, same camera", f"{c['unit']} · {room['name']} · plan-built, solver-placed")
        p3 = label(sc(pol), "Our render, polished", f"SD1.5 img2img s={a.strength} · depth CN {a.cn} · IP-Adapter {a.ip} · {sd_s:.0f} s")
        gap = 10; Wt = p1.width + p2.width + p3.width + 2 * gap; comp = Image.new("RGB", (Wt, p1.height + 40), (16, 20, 28))
        x = 0
        for p_ in (p1, p2, p3): comp.paste(p_, (x, 0)); x += p_.width + gap
        dr = ImageDraw.Draw(comp)
        try: fs = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except Exception: fs = ImageFont.load_default()
        dr.text((12, p1.height + 10), "our render, polished; every object is where the solver put it  ·  " + note, fill=(200, 210, 222), font=fs)
        comp.save(d / "compare.png"); print(key, f"SD {sd_s:.1f}s", note)

if __name__ == "__main__": main()
