# Pivot: from listing photos to a real room you can stand in, inside the real city

Oct 24, 2026, 02:15 · hero for now: "stand in a real room inside the real city, take a quick tour". Sun hours stay as a layer on top. Scope narrows later, after the base is right.

## What "right" means

1. Photos of one room become a complete, photoreal, tourable 3D model. Nothing seen is removed; nothing unseen is left black.
2. The room sits in the real building at the real position, floor and heading, with the real street visible through its windows.
3. Every part of the model knows its provenance: photographed, inferred from structure, or generated.

## Base geometry

- Keep VGGT for clustering and MapAnything for metric scale. Drop Manhattan alignment: wall planes at any angle from a 5° normal histogram with a weak prior toward the two dominant directions, so bays keep their three panes.
- Room polygon is general, from the free-space carve snapped to fitted plane lines. The analysis-by-synthesis fit gets edge angles as parameters.
- Snapping only where the normal agrees with the plane within 20° and the residual is under 8 cm. Window reveals, radiators, furniture keep their depth.
- Fuse all photos of a room into one textured mesh (TSDF, view-dependent blending). Furniture stays as geometry.

## Structure where photos are silent

- Walls, floor, ceiling and openings from the layout behind and between the photos.
- Wall texture projected where seen, inpainted where unseen with a local diffusion inpainter on the M4 Max. Inpainted regions tagged.
- Window openings are real holes; through them the real 3D Tiles of the street.

## Photoreal: Gaussian splats

- Tier 1, today: pixel-aligned Gaussians from the fused geometry, no training, rendered with a three.js splat viewer.
- Tier 2: real 3DGS optimisation against the photos. Port the rasterizer to pure PyTorch on MPS (tile-based forward, autograd backward), initialised from tier 1 so it only refines. Few hundred iterations per room is enough when the start is this good.

## Generative completion (state-of-the-art route)

- Camera-conditioned novel-view generation (Stable Virtual Camera class) from the real photos, conditioned on the layout depth so geometry stays put. Generate the views that fill blind spots, small extrapolations first.
- Reconstruct again from real plus generated views; generated pixels carry a provenance mask and render slightly desaturated or can be toggled off.
- Precompute only; never on the live path.

## Furniture as objects

- Claude already names and describes furniture per room. Match descriptions to assets from Poly Pizza (key in `.env`), place them on the floor where the photo mesh shows them, scaled from the metric reconstruction.
- Photo mesh remains the truth where intact; assets fill where it is torn. Toggle between the two.

## Anchoring in the city

- Register the room's exterior wall, bay included, to the LiDAR footprint boundary in 2D: heading, position along the facade, room inside the lot. A bay matches one bump.
- Detect the window grid on the facade from 3D Tiles textures and Street View; match the room's window spacing and widths to it for position, floor and a scale check.
- Sun-patch cue for front versus back, Claude's side judgement as fallback. Floor from unit number, confirmed by the facade row.

## Status

- Step 1 done Oct 24 03:10: wall planes at any angle (5° normal histogram, offsets per direction), bays modelled as their own panes (Filbert bay: directions 2°, 32°, 92°, 152°), general polygon snapped to plane lines with plane-less edges regularised to the fitted directions, selective ray-snap (normal within 20°, residual under 10 cm), fit generalised to line angle + offset with validity guard. Backups: `pipeline/*_backup.py`.

- Step 2 done Oct 24 03:40: `pipeline/fuse.py`: numpy TSDF fusion (2 cm voxels, 8 cm truncation, frontal/near weighting, best-view colour, crumbs removed) -> `<room>_fused.glb`; pixel-aligned Gaussians (position, normal-oriented, pixel-footprint scale, photo colour) -> `<room>.splat.ply` in 3DGS format; room viewer has 'fused mesh' and 'splats' layers (mkkellogg gaussian-splats-3d). Splat rendering verified only partially in headless Chrome.

- Step 3 done Oct 24 03:10 (geometry part): `pipeline/register.py` registers the room polygon to the LiDAR footprint: search yaw ±8°, slide along the chosen facade, depth ±0.25 m; score = room inside the lot (x3) + exterior-wall samples on the footprint boundary (x1.5). Broadway: inside 1.00, on-boundary 1.00; Filbert: 0.97 / 1.00; Nob Hill: 0.99 / 0.70. Plan images: `rooms/<room>_site_plan.png`. Bay rooms default to the street side when no sun patch or Claude hint exists. Not done: facade window grid from 3D Tiles or Street View (position along the facade still comes from geometry only).

- Step 4 done Oct 24 03:35: `pipeline/lama.py` (big-lama TorchScript, CPU, ~0.4 s per texture) fills unseen wall and floor regions; walls seen under 4% get the room's median wall colour; textures at 2.5 cm/px; each wall keeps its seen mask and inpainted fraction (provenance). Window openings remain real holes. Known: cut-outs sit ~30 cm off the frames painted in the texture on Broadway; needs the window box refined against the wall texture.

- Step 5 done Oct 24 04:05: `pipeline/objects.py`: non-structure geometry on the floor -> blobs with measured size/position; Claude (Haiku) names each from a photo crop (structured JSON); Poly Pizza (CC-BY, attribution kept) supplies a GLB cached in `app/assets/`; the asset is scaled to the blob and placed facing into the room; `rooms/<room>_objects.json`; viewer 'objects' layer. First results: toilet, radiators, wardrobe, kitchen cabinet, fridge, stove detected and placed in the Nob Hill rooms. Listings are mostly empty, so existing-furniture coverage is small by nature; the same machinery places new items for the furnishing product.

- Step 6 done Oct 24 04:45 (first version): `pipeline/outpaint.py` widens each photo by 20% per side with SD 1.5 inpainting on MPS (~10 s per photo), bare-walls prompt, strong negatives; `GEN=1` builds reconstruct from the widened set; generated pixels are tracked per pixel, per wall (`wall_generated_frac`) and generated pixels that reconstruct as objects are discarded. Bay-window test: structure continues correctly; the model still invents doors and a lamp in the margins. Not done: camera-conditioned novel views (SEVA-class, gated weights) and tinting generated regions in the viewer.

- Step 7 done (first version) Oct 24 05:50: `pipeline/splat_opt.py` is a pure-PyTorch tile rasteriser on MPS (16 px tiles, depth-sorted, chunked compositing with carried transmittance, autograd backward). Bay room: 200 iterations in 43 s, PSNR 24.8 -> 55 dB on its single view. Broadway, 7 views, 350 iterations in 131 s: per-view PSNR init 16-23 dB -> optimised 21-34 dB; a novel pose midway between two photos renders as a recognisable but smeared room (sparse-view limit; no densification yet). Export keeps low-confidence pixels as faint Gaussians so the optimiser can raise them. Hold-out test added (train on 6 photos, score the 7th): on Broadway the optimiser makes the held-out view WORSE (17.5 -> 15.5 dB; gentler settings 16.8 dB), i.e. it paints photos onto whatever is in front, which is the artefact the user saw. So the optimised file is used only when `<room>.splat_opt.json` says it beat the hold-out; otherwise the viewer shows the unoptimised splats. Those now place low-confidence pixels on the fitted room shell along their pixel ray (`fuse.shell_raycast`), which restored coverage (hold-out init 10 -> 17.5 dB) without wrong-depth paint. Poly Pizza objects dropped by default (looked out of place).

- Step 8 done Oct 24 05:50: sun layer runs unchanged on the rebuilt rooms (index.html shows per-room December hours and verdicts; placements from footprint registration).

## Order

1. Planes at any angle, bays, selective snapping.
2. Fused textured mesh, furniture kept, splat tier 1.
3. Footprint and facade-window registration, room inside the tiles.
4. Wall-texture inpainting.
5. Furniture assets.
6. Generative novel views, then re-reconstruction.
7. Splat tier 2 on MPS.
8. Sun layer re-attached; then narrow the pitch.

## Guardrails that stay

Spend ledger and key proxy as in PLAN.md. All model inference local. Paid calls: geocodes, root-tile requests, Claude room graphs.

## Polish pass (Oct 24, 07:00-08:30): the shell is the base

Decision: plausible beats exact; the tourable asset is the clean shell with photos baked onto it, photo meshes and splats become optional truth layers.

- `pipeline/polish.py`: every photo pixel is cast onto the shell (first hit among walls, floor, ceiling); per wall: 1 cm textures with provenance (at / beyond / front counts, brightness, colour saturation, generated fraction), flat-fielding (smooth illumination divided out per wall), pinhole fill, LaMa for unseen; openings detected in wall-texture space from see-through + brightness + colour + detector priors, box trimmed on cues, sill from local texture variance (the glass is busy, the wall under it is not), edges snapped to frame lines; the view beyond each opening captured from the photos.
- `pipeline/polish_export.py`: walls with openings cut, reveals (15 cm), frames, transparent glass, billboards behind every opening (windows 12 m, doors 2.5 m) carrying the real view with LaMa-outpainted margins, baseboards, flat ceiling in the measured colour, 1 cm flat-fielded floor. Viewer layer "polished shell".
- Broadway result: the window pair is one opening with the right sill (0.47 m), the tree view shows through it, walls even, passage to the kitchen shows the next room. Known: a false "door" over the kitchen appliances on wall 7; passages' billboards are low quality; detectors on textures were tried and demoted to priors.
- Hold-out and coverage tests for the shell are not yet automated.
