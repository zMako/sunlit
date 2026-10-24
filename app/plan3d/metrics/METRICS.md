# Pitch metrics: what each number is, its n, and its caveats

Run `feasibility/.venv/bin/python app/plan3d/metrics/bench.py`. It aggregates the raw data in `data/`, running any missing
step first, prints the table and writes `summary.json` (shown on the landing page) and `details.json` (every sub-number).
`--fresh` re-runs every step; `--fresh=timing,page` re-runs only some of them (`gs`, `timing`, `page`, `cubicasa`). Nothing calls Claude,
and nothing outside this folder is written. Numbers below were measured on Oct 24 2026, after the batch_v2 rebuild chain.
`summary.json` entries have the shape `{key, value, unit, label, n, method}`; `n` is the sample size the value is computed over,
and `method` says how it was computed.

## A. Breadth (exact counts)

| key | value | n | source |
|---|---|---|---|
| plans_processed | 444 plan images | 26 buildings | every `feasibility/listings/gs-*/plans/plan_*` image; `sweep/sweep.json` ran the classical reader on all of them: 372 readable, 67 unreadable (no enclosed rooms / reader error), 5 not a plan |
| walkable_units | 359 apartments | 23 buildings | `layouts/index.json`: layouts with >= 2 rooms that open in `apartment.html` (82% of the 439 real plan images) |
| rooms_detected | 2523 | 359 units | rooms in those layouts. This count includes closets and hallways (~7 per unit) |
| doors_detected / windows_detected | 4775 / 1420 | 359 units | openings by type (plus 806 cased openings) |

Of the 359 units, 32 take their scale from printed room dimensions, 21 from printed square footage, and **306 from the
bedroom-count size prior** (`rescale.py`). Those 306 have no size ground truth. They are never used in any accuracy number.

## B. Speed

- **plan_to_layout_s = 0.49 s median** (n = 25 of 30 seeded random plan images; the other 5 were rejected as not a floor plan,
  which is correct: blank or photo pages). Each run is a fresh Python process (`time_one.py`), so imports are counted. It covers
  the plan image, the geometry path of `plan_engine.run` (`layout --novlm`), the layout JSON, and the per-room JSONs
  (`rooms_export`). Stages: layout 0.35 s, rooms_export 0.007 s. Max 1.35 s. Hardware: Apple-silicon laptop CPU.
- **first_frame_s = 3.79 s median** (n = 15 seeded units, range 1.5-4.1 s, 0 failures). Headless Chrome through Playwright,
  `apartment.html?unit=...&quality=low`, measured from navigation start to the first presented frame of the built scene: an
  init script counts WebGL draw calls and takes the next requestAnimationFrame after the first frame that drew with
  `window.apartment` set. The page was served by the app proxy on :8765. **SwiftShader is software GL**, so a real GPU is faster.
  Textures can still be streaming in after this frame.
- **plan_to_walkable_s = 4.3 s**: the sum of the two medians. Headline: "floor plan -> walkable 3D apartment in ~4 s".
- Caveat: the production layouts also make one optional VLM call (`plan_reader` for printed dimensions, and the annotate call
  for room names and fixtures). That call is cached and is **not** in these timings. The --novlm path gives unnamed rooms at
  door-width scale.

## C. Scale accuracy against printed ground truth (`gs_accuracy.py`, `data/gs_accuracy.json`)

Ground truth is what the landlord printed: room dimensions transcribed by `plan_reader` v2 (only rooms whose
`dims_source` is `printed` and whose width and depth text are both present), and the unit square footage printed on the plan or
listing. No listing in the corpus carries a `meta.floorplans[].sqft` value yet, and there are no avb-* listings. The plan's
geometry is re-extracted without the VLM review extras, so the regions can differ slightly from the shipped layout. Reader
rooms are matched to regions the way `reader_anchor` does: the biggest region whose centroid lies in the reader's rectangle.
A wrong match counts as an error. Dimensions are compared orientation-free: the shorter side against the shorter side, the
longer against the longer.

| key | value | n | meaning |
|---|---|---|---|
| door_scale_error | **12.6%** median, 46% of plans within 10% | 41 plans with printed dims | INTRINSIC scale: m/px from door widths alone (0.86 m door), compared with m/px fitted on the printed dimensions |
| printed_dims_room_error | **11.3%** median, 49% of dimensions within 10% | 80 rectangular rooms (160 dims), 33 plans | room width/depth vs its printed value, scale fitted on the **other** rooms of the same plan (leave-one-room-out, engine weights). In-sample this is ~8.6%, which is optimistic, so it is not reported. Area error on the same rooms: 22.3% |
| door_scale_unit_area_error | **36.2%** median (signed median -21.6%, 35% within 20%) | 26 units with printed sq ft | sum of room areas at door scale vs 0.85 x printed sq ft (the rescale.py net/gross factor). This measures scale **and** room coverage, because missed rooms and walls count as missing area. After the area rule it is 0 by construction, so that figure is not reported |

Further caveats:
- Door-scale room dimensions (no printed anchor) are 16.1% median off (n = 86 rooms).
- 3 units have no door scale at all and are excluded from the door numbers.
- The ground truth itself is a VLM transcription of printed text. It is not hand-verified.

## D. External benchmark: CubiCasa5K (`cubicasa_fetch.py`, `cubicasa_eval.py`)

Dataset: Kalervo et al. 2019, Zenodo record 2613548, CC BY-NC 4.0. It holds Finnish plans with SVG ground truth. The 5.4 GB
zip was not downloaded. Instead the zip is read over HTTP range requests, fetching only 100 seeded samples from the official
test split (seed 0; F1_scaled.png + model.svg; about 4 minutes, 40 MB in `data/cubicasa5k/`, not for redistribution). The
engine runs unchanged, with no training, no tuning and no VLM: `extract` + `metric_layout`. It ran on 96 of the 100 plans; the
other 4 were rejected as not a plan.

| metric | ours (untrained, n) | paper's trained CNN (test split) |
|---|---|---|
| GT indoor rooms recovered with IoU >= 0.5 | 23.5% (971 rooms) | n/a |
| room instance IoU, mean / median | 26.7% / 16.2% | rooms class mIoU 57.5% (pixel), 49.3% polygonised |
| interior (any room vs not) pixel IoU | 44.7% | n/a |
| wall pixel IoU | 31.7% | wall IoU 73.0% |
| door recall (detected as door / as any gap) | 20.1% / 26.9% (931 doors) | door IoU 53.6% (pixel) |
| window recall (as window / any gap) | 5.0% / 11.0% (843 windows) | window IoU 66.8% (pixel) |
| room count exact / within 1 | 4.2% / 18.8% (median predicted/GT 1.2) | n/a |

How to read this: the engine is classical vision tuned on US marketing plans (black poured walls, door arcs, white rooms).
CubiCasa plans are Finnish drawings with thin-line walls, triple-line windows, stairs and saunas, and their ground truth
counts every annotated space, including shafts and undefined spaces (outdoor spaces were excluded). The paper's figures are
per-class pixel segmentation from a CNN trained on 4,200 of these plans. Ours are instance and recall metrics on a task the
engine was not built or tuned for, so the two columns are not the same metric. Out of domain, without training, the classical
reader recovers about a quarter of rooms and doors and almost no windows. Windows are usually read as wall. **We do not
recommend these as pitch numbers.** At most they can be offered as an honest "out-of-domain, untrained" footnote.
