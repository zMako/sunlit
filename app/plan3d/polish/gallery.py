"""Write polish.html: one card per pair (photo | render | polished) with the honest caption, camera and polish settings.
Self-contained (inline CSS, relative image paths: copies of the photo crops live in out/<key>/photo.jpg)."""
import json, html, pathlib
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent
from common import LIST
VERDICT = json.load(open(HERE / "verdicts.json"))
cams = json.load(open(HERE / "cameras.json")); intr = json.load(open(HERE / "work/intrinsics.json")); cards = []
for c in cams:
    lid, n = c["photo"].replace(".jpg", "").split("/"); key = f"{lid}_{n}"; d = HERE / "out" / key
    if not (d / "meta.json").exists(): continue
    m = json.load(open(d / "meta.json")); x0, y0, x1, y1 = intr[f"{lid}/{n}"]["crop"]
    Image.open(LIST / f"{lid}/{n}.jpg").convert("RGB").crop((x0, y0, x1, y1)).save(d / "photo.jpg", quality=92)
    pm = c["photo_metrology"]; v = VERDICT.get(key, {})
    cam = f"pos ({c['pos'][0]:.2f}, {c['pos'][1]:.2f}, {c['pos'][2]:.2f}) m · yaw {c['yaw']:.0f}° · pitch {c['pitch']:+.1f}° · hfov {c['fov']:.0f}° (VGGT)"
    cam += f" · photo metrology: eye {pm['h_measured']:.2f} m, {pm['D']:.1f} m from the far wall, {pm['yaw_rel']:+.0f}° off its normal" + (" · clamped into the plan room" if c["clamped"] else "") + (f" · adjusted: {c['adjusted']}" if c.get("adjusted") else "")
    cards.append(f"""<section><h2>{html.escape(m['room_name'])} <span>{html.escape(c['unit'])} · photo {html.escape(c['photo'])} · {v.get('score','')}</span></h2>
<div class="row"><figure><img src="out/{key}/photo.jpg"><figcaption>Listing photo (a unit in the same building; the gallery mixes units)</figcaption></figure>
<figure><img src="out/{key}/render.png"><figcaption>Our furnished render from the estimated camera</figcaption></figure>
<figure><img src="out/{key}/polished.png"><figcaption><b>Our render, polished; every object is where the solver put it</b></figcaption></figure></div>
<p class="v">{html.escape(v.get('text',''))}</p>
<p class="d">{html.escape(cam)}<br>polish: SD 1.5 img2img strength {m['strength']}, {m['steps']} steps, depth ControlNet {m['controlnet_scale']} on our render's depth, IP-Adapter {m['ip_adapter_scale']} on the listing photo, {m['sd_seconds']} s on MPS · {html.escape(m['note'])}<br>prompt: {html.escape(m['prompt'])}</p></section>""")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Photo next to render · Move-in</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/ui/movein.css"><style>
main{{width:min(1320px,100vw - 64px);margin:0 auto;padding:40px 0 100px}}
.top{{display:flex;justify-content:space-between;align-items:center;padding:20px 32px}} .top a{{text-decoration:none}} .top .mark{{font-family:var(--serif);font-size:22px}}
h1{{font-family:var(--serif);font-weight:400;font-size:clamp(40px,5vw,64px);line-height:1.02;letter-spacing:-.02em;margin:24px 0 16px}}
.lead{{color:var(--graphite);font-size:17px;max-width:72ch;margin:0}}
section{{margin:72px 0 0}} h2{{font-family:var(--serif);font-weight:400;font-size:30px;margin:0 0 14px}} h2 span{{font-family:var(--sans);color:var(--graphite);font-size:13px;margin-left:10px}}
.row{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}} figure{{margin:0}} img{{width:100%;display:block;border-radius:16px;background:var(--mist)}}
figcaption{{font-size:13px;color:var(--graphite);margin-top:8px}} figcaption b{{color:var(--ink);font-weight:500}} .v{{margin:16px 0 6px;font-size:15px;max-width:90ch}} .d{{color:var(--graphite);font-size:12px;max-width:110ch}}
@media (max-width:900px){{.row{{grid-template-columns:1fr}}}}
</style></head><body class="mi"><header class="top"><a class="mark" href="../landing.html">Move-in</a><a class="muted" href="../index.html">Every apartment</a></header>
<main><h1>Listing photo, our render, our render polished.</h1>
<p class="lead">The render is the plan-built apartment with the furnishing solver's real products, seen from a camera estimated from the listing photo (field of view from VGGT, pitch, eye height and distance from the floor/ceiling lines of the photo's segmentation). The polish is Stable Diffusion 1.5 image-to-image at low strength, held to our render's depth by ControlNet and given the photo only as a style and lighting reference. It cannot move or add objects; the geometry and every item are ours. The photos come from the building's gallery, so they may show another unit with the same plan type: differences in windows, mouldings and floors are real differences between the photo and our model, not polish artefacts.</p>
{''.join(cards)}</main></body></html>"""
open(HERE / "polish.html", "w").write(page); print(len(cards), "cards")
