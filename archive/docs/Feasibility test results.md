# Sunlit feasibility test: results and decision

Oct 23, 2026, 22:20 to 22:45 · ran on the M4 Max (128 GB), VGGT-1B on PyTorch `mps`, fp32

## Decision: GO, with one architecture change

Listing-photo reconstruction works at the level the product needs, but not the way the one-pager assumed. VGGT cannot fuse a whole listing into one model: photos of unrelated rooms get dumped into the same frame and overlap into a jumble (see `feasibility/out/dFeacz7doeHJyiJHf7sr3b/topdown.png`). What does work:

1. **Single photo to window geometry.** One photo gives a clean room fragment with windows on walls, with size, sill height and wall normal. The bay-window photo in the Filbert listing yields three panes facing 53°, 87° and 119°, each about 1.0 × 1.9 m. Single-image confidence is 13 versus 1 to 2 for whole-listing runs.
2. **Same-room photos fuse.** Six photos of one living/kitchen room fused into a coherent 5 × 6 m rectangle with the island in the right place and camera heights 1.2 to 1.5 m.
3. **Rooms can be separated automatically.** Cross-view depth consistency (project image i's points into camera j, compare with j's depth) is 1.0 on VGGT's own example, 0.6 within a real room, and ~0 between unrelated rooms. Connected components of that graph are rooms. Every listing had at least one cluster of 3+ mutually consistent photos.

So the pipeline becomes: photos → VGGT once → consistency graph → per-room clusters → per-room re-run (or single best photo per room) → windows per room. The demo visual "the room builds itself" still holds, per room.

## Scoreboard (12 real SF Craigslist listings, 7 to 21 photos each)

| Bar from one-pager | Pass bar | Result |
| --- | --- | --- |
| Reconstruction: recognizable room | 4 of 5 | 12 of 12 per room, 0 of 12 per whole listing |
| Photo registration: 1 room with 3+ photos registered | 1 per listing | 12 of 12 (biggest cluster 3 to 12 photos) |
| Window on the right wall in 3D | 4 of 5 | 85 to 100% of window detections sit on vertical surfaces in every listing |
| Metric scale (door ≈ 2.0 m) | ±25% | Ceiling-normalized doors 2.2 to 2.4 m where detections are real doors; MapAnything direct metric: single photo ceiling 2.26 m, camera 1.23 m; six-photo living room ceiling 2.92 m, cameras 1.3 to 1.5 m, camera spacing 1.6 to 6.8 m (all plausible, within ±15%) |
| Window size | ±30% | Median widths 0.7 to 1.6 m across listings, heights ~1.9 m, visually plausible; no ground truth yet |
| Orientation anchoring | ±30° | Not tested tonight (needs facade pick or exterior match) |
| Ground truth on your own room | ±30 min | Not tested; do tomorrow morning |
| Runtime, 15 photos, mps | < 3 min | 2 to 19 s inference, 5 s model load |

Per-listing numbers are in `feasibility/out/*/analysis.json`, `regcheck.json`, `stats.json`; renders in `topdown.png`, `detections.png`, `inputs_conf.png`.

## What failed or needs work

- **Whole-listing floor/ceiling scale is unreliable** (median camera height ranged 0.4 to 2.4 m across listings) because the peaks come from a jumble. Normalize per room cluster instead; within one listing the cameras are mutually consistent (IQR 0.05 to 0.25 m).
- **Window detector (OWLv2, "a window")** at 0.25 misses big bright windows; at 0.12 it finds them but also flags cabinets as doors. Filter by size (doors 1.8 to 2.4 m tall, windows 0.4 to 4 m wide) and dedupe overlapping boxes.
- **Listing hygiene:** drop logos, floor plans and maps (different aspect ratio or mostly flat colour) before VGGT, or they force white padding onto every image.
- **Craigslist works as a source** (plain HTML, `imgList` JSON, 1200 px images, lat/lon included). Zillow was not attempted.
- **MapAnything** runs on mps too (3.3 s single image) and gives metric scale directly; its weights download hit HF rate limits mid-test. On the six-photo room MapAnything gave ceiling 2.92 m and cameras at 1.3 to 1.5 m, so it is good enough to be the metric source. Use VGGT for clustering and MapAnything (or its metric_scaling_factor) per room cluster.

## Pitch wording to change

"From the listing photos alone" is false: facing and floor come from the user or the facade match. Say "from the listing", and add floor as an input. The interior differentiator is per-window geometry (size, sill, wall), not the room model.

## Code

`feasibility/run_vggt.py` (VGGT on mps, aspect filter, renders), `analyze.py` (gravity, floor/ceiling scale, OWLv2 windows/doors lifted to 3D), `regcheck.py` (cross-view consistency, room clustering input), `summarize.py` (scoreboard), `run_mapany.py` (metric check), `fetch_listings.py` (Craigslist photos). Environment: `feasibility/.venv` (Python 3.12, torch mps), weights in `feasibility/weights/model.pt`.
