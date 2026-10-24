"""Outpaint one perspective photo into a full 360 panorama with SD 1.5 inpainting, view by view."""
import sys, time, pathlib, numpy as np, cv2, torch
from PIL import Image
import equirect as E
_pipe = None
NEG = "furniture, sofa, bed, table, chairs, cabinet, curtains, plant, picture frame, people, text, watermark, lamp, clutter, distorted, cartoon, dark, blurry, collage, border"

_pipe_cn = None
def pipe_cn():
    """Inpainting under the depth ControlNet (same cached models as complete.py) + IP-Adapter on the source photo."""
    global _pipe_cn
    if _pipe_cn is None:
        from diffusers import StableDiffusionControlNetInpaintPipeline, ControlNetModel
        cn = ControlNetModel.from_pretrained("lllyasviel/control_v11f1p_sd15_depth", torch_dtype=torch.float16)
        _pipe_cn = StableDiffusionControlNetInpaintPipeline.from_pretrained("stable-diffusion-v1-5/stable-diffusion-inpainting", controlnet=cn, torch_dtype=torch.float16, safety_checker=None)
        _pipe_cn.load_ip_adapter("h94/IP-Adapter", subfolder="models", weight_name="ip-adapter_sd15.bin"); _pipe_cn.set_ip_adapter_scale(0.5)
        _pipe_cn = _pipe_cn.to("mps"); _pipe_cn.set_progress_bar_config(disable=True)
    return _pipe_cn

def pipe():
    global _pipe
    if _pipe is None:
        from diffusers import StableDiffusionInpaintPipeline
        _pipe = StableDiffusionInpaintPipeline.from_pretrained("stable-diffusion-v1-5/stable-diffusion-inpainting", torch_dtype=torch.float16, safety_checker=None)
        _pipe.load_ip_adapter("h94/IP-Adapter", subfolder="models", weight_name="ip-adapter_sd15.bin"); _pipe.set_ip_adapter_scale(0.5)
        _pipe = _pipe.to("mps"); _pipe.set_progress_bar_config(disable=True)
    return _pipe

# (pitch_deg, yaw_deg, fov_deg): sideways first, then floor and ceiling, then the poles
SCHEDULE = [(0, 0, 90), (0, 45, 90), (0, -45, 90), (0, 90, 90), (0, -90, 90), (0, 135, 90), (0, -135, 90), (0, 180, 90),
            (-40, 0, 95), (-40, 90, 95), (-40, 180, 95), (-40, -90, 95), (40, 0, 95), (40, 90, 95), (40, 180, 95), (40, -90, 95),
            (-89, 0, 110), (89, 0, 110)]

import os
def fill_view(rgb, kn, prompt, ref, steps=20, seed=0, work=640, control=None, cn_scale=float(os.environ.get("CN_SCALE", "0.8"))):
    med = np.median(rgb[kn].reshape(-1, 3), 0).astype(np.uint8) if kn.any() else np.array([205, 200, 192], np.uint8)
    fill = rgb.copy(); fill[~kn] = med
    mask = cv2.dilate((~kn).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    im = Image.fromarray(fill).resize((work, work), Image.LANCZOS); mk = Image.fromarray((mask * 255).astype(np.uint8)).resize((work, work), Image.NEAREST)
    g = torch.Generator(device="cpu").manual_seed(seed)
    if control is not None:
        dp = Image.fromarray(control).convert("RGB").resize((work, work), Image.BILINEAR)
        out = pipe_cn()(prompt=prompt, negative_prompt=NEG, image=im, mask_image=mk, control_image=dp, ip_adapter_image=ref, num_inference_steps=steps, guidance_scale=6.5, controlnet_conditioning_scale=cn_scale, generator=g, strength=1.0).images[0]
    else:
        out = pipe()(prompt=prompt, negative_prompt=NEG, image=im, mask_image=mk, ip_adapter_image=ref, num_inference_steps=steps, guidance_scale=6.5, generator=g, strength=1.0).images[0]
    out = np.asarray(out.resize(rgb.shape[1::-1], Image.LANCZOS)); res = rgb.copy(); res[~kn] = out[~kn]
    return res

def outpaint(pano, known, prompt, ref, N=640, steps=20, log=print, min_unknown=0.01, schedule=SCHEDULE, depth_fn=None):
    """depth_fn(N, fov, R) -> uint8 (N, N) inverse-depth control image of the target box, or None for free outpainting."""
    H, W = known.shape; D = E.dirs(W, H); t0 = time.time()
    for k, (pitch, yaw, fov) in enumerate(schedule):
        R = E.rot(np.radians(yaw), np.radians(pitch)); rgb, kn = E.render_view(pano, known, N, fov, R)
        unk = 1 - kn.mean()
        if unk < min_unknown: log(f"  view {k:2d} p{pitch:+d} y{yaw:+d}: known, skip"); continue
        pr = prompt if pitch < 30 else "plain flat smooth white painted ceiling of an apartment room, matte, even light, no beams, no planks, no fixtures except a small round light, photorealistic"
        if pitch >= 30: (pipe_cn() if depth_fn else pipe()).set_ip_adapter_scale(0.1)
        else: (pipe_cn() if depth_fn else pipe()).set_ip_adapter_scale(float(os.environ.get("IP_SCALE", "0.5")))
        t = time.time(); res = fill_view(rgb, kn, pr, ref, steps=steps, seed=k, control=depth_fn(N, fov, R) if depth_fn else None)
        f = (N / 2) / np.tan(np.radians(fov) / 2); n = E.paste_image(pano, known, res, R, f, N / 2 - 0.5, N / 2 - 0.5, D=D)
        log(f"  view {k:2d} p{pitch:+d} y{yaw:+d}: {unk*100:4.0f}% unknown -> painted {n} px in {time.time()-t:.1f}s")
    log(f"  outpaint total {time.time()-t0:.0f}s, known {known.mean()*100:.1f}%")
    return pano, known
