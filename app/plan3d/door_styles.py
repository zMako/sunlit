"""Door style per listing from its photos: OWLv2 finds the doors in each photo, CLIP classifies each door crop into a style
the builder knows (shaker / panel / slab / wood), votes are weighted by detection score. Local models only, no paid calls.
Listings without photos get no entry (the layout default, shaker, applies). -> door_styles.json

  door_styles.py [listings ...]   (default: every listing with a 3D layout)"""
import sys, json, glob, pathlib
import numpy as np
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; OUT = HERE / "door_styles.json"
STYLES = {
    "shaker": ["a white shaker style interior door with one recessed flat panel", "a modern white door with a single square recessed panel"],
    "panel": ["a white traditional six panel interior door", "a white door with raised decorative panels"],
    "slab": ["a plain flat white flush interior door with no panels", "a minimalist smooth slab door"],
    "wood": ["a dark stained wood interior door", "a natural wood grain flush door"],
}

def main(listings):
    import torch, open_clip
    from transformers import Owlv2Processor, Owlv2ForObjectDetection
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    owl_p = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble"); owl = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").to(dev).eval()
    clip, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k"); clip = clip.to(dev).eval(); tok = open_clip.get_tokenizer("ViT-B-32")
    names = list(STYLES); prompts = [p for n in names for p in STYLES[n]]
    with torch.no_grad():
        te = clip.encode_text(tok(prompts).to(dev)); te = te / te.norm(dim=-1, keepdim=True)
    out = json.load(open(OUT)) if OUT.exists() else {}
    for lid in listings:
        photos = sorted(p for p in glob.glob(str(ROOT / "feasibility/listings" / lid / "[0-9][0-9].jpg")))
        if not photos: continue
        votes = np.zeros(len(names)); crops = 0
        for ph in photos:
            im = Image.open(ph).convert("RGB")
            with torch.no_grad():
                inp = owl_p(text=[["a door", "an interior door"]], images=im, return_tensors="pt").to(dev); o = owl(**inp)
                W, H = im.size; S = max(W, H)   # OWLv2 pads to a square: boxes are in the padded frame
                res = owl_p.post_process_grounded_object_detection(outputs=o, threshold=0.25, target_sizes=torch.tensor([[S, S]]).to(dev))[0]
            for box, sc in zip(res["boxes"].cpu().numpy(), res["scores"].cpu().numpy()):
                x0, y0, x1, y1 = [int(v) for v in box]; x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
                if (x1 - x0) < 40 or (y1 - y0) < 80 or (y1 - y0) < 1.3 * (x1 - x0): continue   # doors are tall
                with torch.no_grad():
                    ie = clip.encode_image(pre(im.crop((x0, y0, x1, y1))).unsqueeze(0).to(dev)); ie = ie / ie.norm(dim=-1, keepdim=True)
                    p = (100 * ie @ te.T).softmax(-1)[0].cpu().numpy()
                per = np.array([p[i * 2:(i + 1) * 2].sum() for i in range(len(names))]); votes += float(sc) * per; crops += 1
        if crops:
            st = names[int(votes.argmax())]; out[lid] = {"style": st, "doors_seen": crops, "photos": len(photos), "votes": {n: round(float(v), 3) for n, v in zip(names, votes)}}
            print(f"[door_styles] {lid}: {st} from {crops} door crops in {len(photos)} photos {out[lid]['votes']}", flush=True)
        else: print(f"[door_styles] {lid}: no door seen in {len(photos)} photos", flush=True)
    json.dump(out, open(OUT, "w"), indent=1)

if __name__ == "__main__":
    ls = sys.argv[1:] or sorted({d["listing"] for d in json.load(open(HERE / "layouts" / "index.json"))})
    main(ls)
