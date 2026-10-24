"""Step 6: generative completion by outpainting. Each listing photo is extended by a margin on every side with a diffusion
inpainter (small extrapolation, conditioned on the photo itself), then the widened set is reconstructed again.
Every generated pixel is tracked in a mask so provenance survives into textures and the viewer."""
import sys, json, pathlib, numpy as np, torch
from PIL import Image
_pipe = None
MODEL = "stable-diffusion-v1-5/stable-diffusion-inpainting"

def pipe():
    global _pipe
    if _pipe is None:
        from diffusers import StableDiffusionInpaintPipeline
        _pipe = StableDiffusionInpaintPipeline.from_pretrained(MODEL, torch_dtype=torch.float16, safety_checker=None).to("mps"); _pipe.set_progress_bar_config(disable=True)
    return _pipe

def outpaint_photo(path, out_dir, margin=0.2, work=768, steps=24, prompt=None, seed=0):
    """Returns (widened image path, generated-mask path). Canvas = photo padded by margin*size on each side; the padding is
    filled by the inpainter at `work` px on the long side, then composited back at full resolution."""
    im = Image.open(path).convert("RGB"); W, H = im.size; mx, my = int(W * margin), int(H * margin)
    canvas = Image.new("RGB", (W + 2 * mx, H + 2 * my)); 
    # seed the border with mirrored content so the model continues structure instead of inventing
    arr = np.asarray(im); pad = np.pad(arr, ((my, my), (mx, mx), (0, 0)), mode="reflect"); canvas = Image.fromarray(pad)
    mask = np.zeros((H + 2 * my, W + 2 * mx), np.uint8); mask[:my, :] = 255; mask[-my:, :] = 255; mask[:, :mx] = 255; mask[:, -mx:] = 255
    s = work / max(canvas.size); small = canvas.resize((int(canvas.width * s) // 8 * 8, int(canvas.height * s) // 8 * 8), Image.LANCZOS)
    msmall = Image.fromarray(mask).resize(small.size, Image.NEAREST)
    g = torch.Generator(device="cpu").manual_seed(seed)
    out = pipe()(prompt=prompt or "empty unfurnished apartment room, the same bare painted walls, wood floor and plain ceiling continuing beyond the edge of the photo, nothing on the walls, photorealistic, natural daylight",
                 negative_prompt="curtains, drapes, furniture, sofa, cabinet, box, plant, picture, painting, people, text, watermark, clutter, distorted, cartoon, dark", image=small, mask_image=msmall, num_inference_steps=steps, guidance_scale=5.0, generator=g).images[0]
    out = out.resize(canvas.size, Image.LANCZOS); res = np.asarray(canvas).copy(); mk = mask > 0; res[mk] = np.asarray(out)[mk]
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True); name = pathlib.Path(path).name
    Image.fromarray(res).save(out_dir / name, quality=92); Image.fromarray(mask).save(out_dir / (name[:-4] + "_gen.png"))
    return str(out_dir / name), str(out_dir / (name[:-4] + "_gen.png"))

def outpaint_room(photo_paths, out_dir, prompt=None):
    import time; t = time.time(); outs = []
    for i, p in enumerate(photo_paths): outs.append(outpaint_photo(p, out_dir, prompt=prompt, seed=i))
    print(f"[outpaint] {len(outs)} photos widened by 25% per side in {time.time()-t:.0f}s -> {out_dir}"); return outs

if __name__ == "__main__":
    outs = outpaint_room(sys.argv[1:-1], sys.argv[-1])
