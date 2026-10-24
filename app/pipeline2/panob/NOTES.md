# Path B: panorama-first room (app/pipeline2/panob)

One listing photo -> 360 panorama by SD 1.5 inpainting view by view -> Manhattan box from the panorama's floor/ceiling
boundaries (segmentation, no extra weights) -> textured box GLB. Geometry is plausible, not measured.

    feasibility/.venv/bin/python app/pipeline2/panob/run.py <listing_dir> <room_name> <photos,comma> [--reuse-pano] [--guided] [--pano-only]

Outputs in app/rooms: `<name>_B.glb`, `<name>_B_polished.glb` (same file), `<name>_B.json`, `<name>_B_pano.jpg`,
`<name>_B_pano_init.jpg` (photo placed, nothing generated), `<name>_B_review.jpg` (panorama + floor/ceiling boundary + photo).
`--guided` writes `_Bg` files instead (depth-ControlNet steered to a VLM-sized box; see below).

Modules: `equirect.py` (equirect maths, perspective <-> panorama paste/sample), `outpaint.py` (SD inpaint pipeline, view
schedule, ceiling prompt for upward views), `blayout.py` (perspective-view segmentation -> equirect labels -> floor/ceiling
boundary -> dominant axes -> per-wall median distance -> rectangle, ceiling height), `export_box.py` (textured box, flat
ceiling colour), `guided.py` (box from the photo's visible walls + VLM dims, depth control), `view.html` (minimal viewer:
`/pipeline2/panob/view.html?room=<name>_B&view=inside|outside&yaw=<rad>`).

Choices and findings (Oct 24):
- Best photo = largest floor fraction x FOV (VGGT intrinsics). Camera pitch/roll from the VGGT floor plane of that photo.
  Letterboxed photos (1000 Green) are cropped before placement.
- Outpainting: 18 views (8 at pitch 0, 4 at -40, 4 at +40, 2 poles), 640 px, 20 steps, IP-Adapter on the source photo
  (0.5; 0.1 for ceiling views), 89 s per room when the GPU is free (10 min when sharing with two other SD jobs).
- Free outpainting places generated walls at the same distance as the photographed far wall (camera assumed central),
  so the room comes out 3-4x the VLM area at camera height 1.5 m. Absolute scale is free in a panorama: the floor is
  scaled to the VLM area (camera height follows, ~0.9-1.15 m), the ceiling height is taken from the VLM (2.5-2.6 m).
- Guided mode (depth ControlNet of a VLM-sized box, cn 0.8, IP 0.5) painted wood grain over every near wall: worse.
  A retry with IP 0.15 / cn 0.5 was started; see `app/rooms/panob_guided2.log`.
- Ceilings: SD invents planks/beams; the box ceiling is a flat colour sampled from the photo's ceiling.
