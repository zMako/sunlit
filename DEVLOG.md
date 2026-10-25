# Development log (chronological; newest at the bottom)

This file is the running history of the project, kept verbatim as it was written during the hackathon. The current
concept and architecture are in README.md and ARCHITECTURE.md; the plan of record is ROADMAP.md; open decisions are in HOLD.md.

## Oct 23-24 (night): "Pipeline 2", photo reconstruction era

Oct 24, 2026, 05:40. Replaces the heuristic chain in `app/pipeline/` where it failed repeatedly; reuses what proved itself.
Goal: the room layout as precise as the photos allow (a judge glancing at it must not catch an error); everything unseen
completed plausibly; no holes, no seams, no "paint on the wrong wall". Furnishing comes after, on top of this.

## Principles

1. Learned models where we had thresholds: segmentation for pixel labels, generation for unseen appearance.
2. One canvas for appearance: a panorama from the room centre, completed once, conditioned on our own geometry.
3. Geometry wins over generation: the shell is fitted from measurements; diffusion is only allowed to paint on it.
4. No per-listing settings. A harness runs every listing we have and reports metrics and plan sheets.
5. Local only, except the room graph (Claude, cents per listing). Spend ledger and key proxy unchanged.

## Stages

1. **Room graph** (kept): Claude groups photos into rooms by content; geometric consistency may only split a group.
2. **Geometry** (kept): VGGT poses and depth; MapAnything metric scale; door height from segmentation as a scale check.
3. **Segmentation** (new): Mask2Former ADE20K per photo -> wall, floor, ceiling, window, door, mirror, object.
4. **Layout** (replaced): wall planes from wall-labelled points (any angle); floor footprint from floor-labelled points
   unprojected onto the floor plane; polygon = wall lines snapped around the footprint, closed behind the cameras
   where unseen; refined by the analysis-by-synthesis fit. Openings = window/door masks projected onto their wall plane.
   SpatialLM: one-hour timeboxed trial as an alternative layout source; nothing depends on it.
5. **Panorama** (new): render the shell from the room centre with the photos projected; holes where unseen;
   SD 1.5 inpainting with the depth ControlNet (our shell's depth) completes it face by face; seen pixels always win.
   Windows keep the real view; doors show the next room where photographed.
6. **Shell** (kept, retextured): walls, floor, ceiling from the panorama; openings cut; reveals, frames, glass, trim;
   outside billboards or 3D Tiles. Provenance per texel: photographed / generated.
7. **Live path** (product): shell with real textures in ~40 s, generated faces fade in over the next two minutes.
   Demo listings precomputed.

## Harness

Two tiers. Fast: geometry + segmentation + layout for every room of every fetched listing, ~1 min per room; outputs
polygon validity, area, wall count, opening count vs Claude's description, hold-out photo PSNR of the shell, plan and
panorama thumbnails on one sheet. Slow: panorama completion for demo rooms only.

## Known limits, accepted

Identical rooms cannot be told apart from photos. Walls nobody photographed are plausible, not true. Generated
regions may drift in style. Wide-angle perspective-corrected photos reduce pose accuracy; the fit absorbs some of it.

## Order

Segmentation + harness -> segmentation-driven layout -> panorama completion -> live path -> furnishing.

## Status, Oct 24 06:10

- Stage 3 done: `app/pipeline2/seg.py` (Mask2Former ADE20K on MPS, ~0.2 s/photo cached), all 12 listings segmented.
- Stage 4 first version: `layout2.py`: geometry from seg labels (`geometry.clean_room(seg=...)`), room cell = box carved behind
  every seen wall segment (a door-width past its pixels), closed at seen floor + cameras; floor evidence per camera capped at
  the first wall it faces (floor through a doorway is the next room); `polygon_from_cell` snaps edges to planes and only nudges
  vertices; openings from window/door masks projected onto their wall plane; door-based metric scale (2.03 m).
  Groups split by mutual consistency: 23 of 37 multi-photo groups had a photo without overlap and were split.
- Harness (`harness.py`): run 1 over 81 rooms / 12 listings: 81 ok, 0 crashes, 2.9 s median; median 8 walls, 69% of edges
  closure (not measured), windows found in 46 of 56 rooms Claude says have one, door median 1.82 m before rescale.
- Stage 5a done: `pano.py` cube-map of the shell from the room centre, photo colour only where the photo's own depth agrees
  with the shell (objects and through-door content never land on walls). Stage 5b/6 written: `complete.py` (SD 1.5 inpaint +
  depth ControlNet, 11 s per 512 face measured; pano -> wall/floor/ceiling textures -> polished GLB). Den test in flight.

## Status, Oct 24 06:50

- Harness runs 2 and 3 (81 rooms each, 0 crashes): closure edges 62%; windows found 38 then 40 of 56. Root cause found for
  the misses: the confidence mask dropped the 30% least confident pixels, which on flat walls are the walls themselves
  (one kitchen: 30,753 wall pixels, 4,562 kept, no wall plane at all). Now an absolute cutoff (conf > 1.1): that kitchen
  gets its planes and a 1.39 x 1.18 m window. Harness 4 running on this.
- Openings: the wall an opening sits on is now chosen by where its rays actually land (inside an edge's extent), not by
  the ring vote alone (the vote picked a short side edge when a window straddled a corner).
- Completion v2/v3 (`complete.py`): the four side faces are generated as ONE strip (colours and light agree around the
  room), with the room's own photos as IP-Adapter reference (scale 0.3), misprojected blobs removed first, pinholes
  filled, plain ceiling from the measured colour (diffusion invents texture there), floor generated with a wood prompt,
  door crops behind doorways. 139 s per room on this machine. Den result: consistent cream walls, baseboards, the real
  window; defects being fixed: speckle from the reference, mosaic in photographed areas.

## Status, Oct 24 06:25

- Data policy (user): rooms need >= 2 photos; listings must be empty (furniture pixels < 1%) and well covered. The first
  10 Craigslist rentals are empty (0-0.3%); the 8 added at 06:00 are staged (1-12%) and are skipped. `feasibility/filter_listings.py`
  fetches more and keeps only passing listings (KEEP / SKIP_* marker files); room graphs run only on kept ones.
- Layout: rectangle-first (`layout2.rect_room`): dominant axes from the strongest wall plane; each of 4 sides is a measured
  plane (facing outward, 0.4-8 m from the cameras) or an inferred extent (seen floor + cameras + margin); cameras always inside.
  Rectilinear prior (`strong_planes`): off-axis planes need >= 6% of wall pixels and >= 0.7 m; parallel planes within 0.4 m
  merge. Bays as polygon bumps: not yet re-added on top of the rectangle.
- Pairing: photos of a room are accepted together if they overlap, OR their floor levels agree and the cameras are < 7 m apart
  (VGGT places non-overlapping views of one room by context). Broadway kitchen: 3 photos, 3 measured sides, 24.6 m2.
- Completion: faces with < 15% photo coverage get flat measured paint per surface (SD invents plaster texture there);
  diffusion only continues photographed faces. Door crops behind doorways. No billboards; the city viewer loads the
  polished shell with glass windows (`site.html`, needs a real browser for 3D Tiles).

## Status, Oct 24 06:45

- VLM structure pass added (`pipeline2/vlm_structure.py`, Haiku ~$0.0006 per room, Opus for demo rooms): shape, width/depth,
  ceiling, walls clockwise with openings, colours, floor. Fused into `rect_room`: unmeasured sides = measured opposite + VLM
  dimension; measured span > 1.4 x VLM dimension -> the weaker side is moved to the VLM dimension (a plane seen through a
  door belongs to the next room). Also the no-fail fallback room for the live path (not yet wired into the viewer).
- Harness 8 (14 empty listings, 63 multi-photo rooms): 58 built, all rectangles, median area 26.7 m2 (was 37.9), 50% of
  rooms flagged measured/VLM area disagreement -> arbitration added, harness 9 running.
- Den completion v8: flat measured paint on all unseen texels, diffusion only harmonises (strength 0.45) on photographed
  faces, surfaces textured from their own cube faces. Result: clean flat walls, baseboard, sun patch, holes for openings.
  Room viewer got a sky backdrop; the city viewer shows the real exterior through the holes.
- Spend: Anthropic $0.30, Google $0.04.

## Project layout (after the Oct 24 clean-up)

- `app/pipeline2/`: the room pipeline. `seg.py` (segmentation), `layout2.py` (rectangle-first layout, openings), `vlm_structure.py`
  (Claude structure prior), `pano.py` (cube-map of the shell), `complete.py` (completion + textured shell export),
  `build_room2.py` (one room, fast tier), `harness.py` (all rooms of all kept listings), `holdout.py` (scoring).
- `app/pipeline/`: shared stages still used: `recon.py` (VGGT), `geometry.py` (gravity, planes, snapping), `layout.py`
  (edges, wall/floor textures), `fit.py` (analysis-by-synthesis), `export.py`, `export_layout.py`, `polish.py`,
  `polish_export.py` (shell GLB with reveals, frames, glass), `lama.py`, `roomgraph.py` (Claude room grouping), `fuse.py` (camera helper).
- `app/room.html` + `app/proxy.py`: the viewer and its static server (`python proxy.py`, then http://127.0.0.1:8765/room.html).
- `app/rooms/`: built rooms (`p2_*`), `app/harness/`: harness runs with plan sheets.
- `feasibility/`: Python env, model weights, listing photos + segmentation caches, `fetch_listings.py`, `filter_listings.py`.
- `archive/`: everything from the sunlight / city / exterior / splat / object phases, old docs and pipeline-1 rooms.

## Status, Oct 24 08:30: data from landlords' own sites, floor plans as ground truth
- Aggregators are closed to us: Apartments.com serves an "AI Agent Activity Detected" page to the Claude browser extension
  and its terms forbid automated access; Zillow's terms say the same; headed Playwright got Akamai-blocked. We do not
  work around site policy. `feasibility/scrape_plans.py` is kept only as a record.
- Landlord sites instead. Greystar (robots.txt allows everything but /api/*) lists 35 SF buildings with photos of actual
  EMPTY units at 1600 px, the room type encoded in the image id (LIV/KIT/BED/BTH/DNG), and floor-plan images, many with
  printed room dimensions (e.g. 1000 Green: Living 22'6" x 15'0"). `feasibility/scrape_greystar.py` (paced, resumable)
  writes them as ordinary listings: `feasibility/listings/gs-<id>/NN.jpg`, `plans/plan_NN.*`, `meta.json` with
  `photo_codes` and `floorplans`. Haul: 492 interior photos, 444 plan images. AvalonBay/UDR/Equity also allow crawling
  but show staged model units; not used.
- Building galleries mix units: BED1..BED6 are usually six different bedrooms. `roomgraph.py` gets the gallery codes and
  is told to merge photos only when the same windows/doors/closets visibly match (1000 Green: the two "living room" photos
  from different units are now two rooms). `filter_listings.py` minimum lowered to 6 photos.
- Floor plans -> dimensions: `plan_reader.py` (Claude, printed text verbatim, ft->m in code; 10k-token budget, the
  dimensioned plans need it). `plan_match.py` picks, for a photographed room, the plan room of the same type whose
  dimensions agree best with the measured rectangle (measured sides weigh 1, inferred 0.35, window-count penalty).
  Agreeing candidates -> `floor_plan` (cap 1.08, goal 1.0x); a lone pick among disagreeing plans -> `floor_plan_candidate`
  (cap 1.15, goal 1.05x). `build_room2.py` runs it after the first geometry pass when the listing has `plans/` and
  rebuilds; `ROOM_LABEL` env ("type: name") carries the room type from the queue (`proxy.py` sets it).
- `layout2.rect_room` cap rewritten: cameras are kept inside first, then an over-long span is pulled on its weaker side
  as far as the cameras allow, and if that side cannot move the MEASURED wall is pulled instead (VGGT puts far walls
  1.4-2x too far; with a printed dimension the wall is the thing that is wrong). 1000 Green living: 53 m2 -> 37 m2
  against a 35.7 m2 plan room. Axes now report `spans`, `axis_measured`, `dbg`.
- Gallery reality check (filter over the 35 buildings): big buildings show staged model units (1000 Chestnut, Fillmore
  Center, Telegraph Hill: 10-30% furniture pixels in most photos); small acquired buildings (240 Dolores, 2133 Stockton,
  1000 Green) are photographed empty. `filter_listings.py` now sets staged photos aside PER PHOTO for galleries
  (`NN.jpg.furnished`, furniture >= 2.5%), keeps a gallery with >= 1 twice-photographed room, and takes a prefix argument
  (`filter_listings.py gs-`). Haiku over-split galleries (same fireplace/ceiling from two angles became two rooms), so
  galleries use Sonnet for the room graph (~$0.04 per building) with a "merge on recurring distinctive features" prompt;
  room graph output budget raised to 8k tokens (24-photo galleries truncated at 3k).
- Craigslist listings archived (`archive/listings-craigslist`, `archive/rooms-craigslist`) at the user's request; the
  page shows landlord-sourced rooms only.
- Queue bug: room names used the first 6 characters of the listing id (fine for 22-char Craigslist ids, ambiguous for
  `gs-162xx`), the worker resolved the wrong listing, the thread died and the room sat in "rendering" forever. `proxy.py`
  now keeps landlord ids whole (`short()`, `listing_of()`), and a resolution failure is logged instead of killing the worker.
- Second landlord source: RentSFNow (Veritas's own leasing site; robots.txt allows everything, sitemaps list every unit
  page, no terms page restricting access). One page per vacant unit with 10-17 photos OF THAT UNIT at 2048 px (the image
  name carries address + unit number), square footage, beds/baths, price, neighbourhood. Virtually staged copies are
  watermarked and skipped by name. `feasibility/scrape_rentsfnow.py [since] [max]` -> `feasibility/listings/rsn-<slug>/`,
  391 unit pages modified since Aug 2026. These are single-unit listings, so the normal (Haiku) room graph and the
  two-multi-photo-rooms rule apply. Not rendered yet; they appear on the page as "not built".
- Rejected: AppFolio-hosted listing pages (robots disallow detail pages; AppFolio listing terms forbid automated access),
  Buildium (no robots served, same shape of terms), Equity (blocks plain fetches), Essex (rate-limits), Mosser (placeholder).

## Oct 24 09:30: the Greystar renders are grey boxes; two fixes race
- Diagnosis over 17 rendered rooms: measured area 1.2-7x the VLM estimate (median 1.6x). The analysis-by-synthesis
  fit moves walls back to VGGT's over-measured depth and undoes the rect_room cap (1000 Green: 37 m2 with FIT=0, 53 with
  FIT=1). Textures are projected only where the point cloud agrees with the shell, so a wrong box gets no texture.
  Windows found in 6/17 rooms (window cutting needs a measured plane). Kitchens lose their fixtures.
- Path A (edits layout2/build_room2/pano/complete/fit): fit constrained to the VLM/plan tolerance; measured sides kept
  only when they agree with the VLM within 15% (plans 10%), otherwise the box is VLM/plan-sized; every photo projected
  onto the box by ray casting with no agreement test, fixtures kept, windows cut from masks on the box wall. Outputs
  suffixed `_A`.
- Path B (new app/pipeline2/panob/): best photo -> SD1.5 outpainted 360 panorama -> HorizonNet/LGT-Net layout -> textured
  box GLB. Outputs suffixed `_B`.
- Same four test rooms (240 Dolores bedroom 5, 2133 Stockton living 5 and kitchen 0, 1000 Green living from photo 03
  with its dimensioned plans). `proxy.py` reports `variants`, the selector shows A/B buttons next to "open".

## Oct 24 10:30: decision, plans are the truth; photos say which wall and give textures
- A vs B verdict (user): A right-sized but a collage with seams; B pretty but invented (a kitchenette in a living room),
  a one-viewpoint panorama on a cube is not a room. Both dropped as methods. Kept from A: horizontal rescale insight,
  window cutting by rays, VARIANT suffixing. Kept from B: nothing but the lesson.
- New pipeline (plan-first, "wallwrap"): printed floor-plan dimensions size the room (then listing sqft, then VLM);
  each photo supplies perspective-corrected textures for the wall faces it shows via a homography from the face's quad
  (floor line, ceiling line, two corner lines) to the known wall rectangle; unseen walls flat measured paint + baseboard;
  windows/doors from the plan, rectangles refined from the photo masks; nothing generated. One photo per room is enough,
  so the two-photos-per-room rule is gone for plan-backed listings, which brings back 1000 Green (11 dimensioned plans).
- P1 (`plan_reader` v2 with per-wall openings, `plan_link.py`: photo -> plan -> room -> walls, Sonnet) and P2
  (`app/pipeline2/wallwrap/build.py`: box + homography textures + GLB/JSON) run in parallel on 1000 Green.
- Furnishing layer is live: `app/furnish/furnish.js` (drag/rotate/snap/fit checks, Path C), `place.py` (solver),
  `plan.py` (Claude picks from `catalog.json`, IKEA facts only: name, dims, price, URL, model URL; nothing re-hosted),
  `/api/furnish`, `/api/furnish/auto`. Viewer: variant names open, "inside" view, camera-side culling.
- Known later problem, accepted: fixtures are painted on the wall; fix later by extruding boxy fixtures from their
  floor-contact line, relief from monocular depth, catalogue models for appliances.

## Oct 24 11:30: plan-first pipeline is real ("plan3d")
- `app/plan3d/plan_engine.py`: raster plan -> layout JSON. Walls = thick strokes (per tone class: black / dark grey / light
  grey, filled blocks separated first); wall pieces = long axis-aligned components; gaps bridged along each piece's axis and
  classified by what fills them (window lines in the band, a door arc of radius ~gap off one end, or nothing); rooms = enclosed
  white regions; a second pass drops "doors" wider than 1.6x the typical door. Scale: printed room dimensions (plan_reader v2,
  matched to regions by image fraction) > the VLM's per-room size estimates (annotation) > median door gap = 0.86 m.
  One Sonnet call per plan (`vlm_annotate`, ~$0.02) names the numbered regions, places fixtures as fractional boxes (snapped to
  the room's wall), reads printed sqft and lists discrepancies (review loop input). Debug: `plan_engine.py <plan>` writes an
  overlay to the scratchpad; `plot_layout.py` draws a layout; `rooms_export.py` writes per-room JSON (`<unit>__<roomId>`) for
  the furnishing solver; `batch.py <listing...>` builds every plan of a building and `layouts/index.json`; `index.html` lists units.
- `app/plan3d/apartment.html` + `build.js` (worker): procedural apartment from the layout: walls with openings, doors with
  swing, windows with glass + sky, floors/ceilings/baseboards, parametric fixtures, PBR materials from `app/furnish/materials`
  (CC0, ambientCG/Poly Haven) with built-in defaults, PMREM + sun + per-room fill, dollhouse (section cut) and walk views.
- Known gaps: small rooms whose door arc is faint stay unenclosed (1000 Green bath/entry); fixture boxes from the VLM are
  +-10-20 cm; undimensioned plans are scaled from VLM size estimates (+-15%); SightMap plans are 350-470 px, so everything is
  +-2 px = +-5 cm. Spend: $2.4 of $5 before the batch.

## Oct 24 13:10: roadmap for the owner's nap, workers launched, repository created
- User set the 9-step autonomous roadmap (ROADMAP.md) and raised caps to $10 Anthropic / $5 Google. HOLD.md collects
  the decisions that need the owner (Visa starter pack, Coinbase x402 doc + CDP keys, IKEA assets, track framing).
- Parallel workers: full CC0 library download (Sonnet); render quality (coherent materials, photoreal lighting,
  adversarial screenshot review); photo facts (windows/doors/materials per photo -> layouts); IKEA catalogue expansion +
  local models (Sonnet); furniture agent v2 (budget, style, streaming placement with rejections, chat); checkout (card
  sandbox stopping before capture + x402 on Base Sepolia with a local mock facilitator, move-in scheduling).
- Coordinator (this log's author): geometry-only sweep over all 444 plan images (418 readable; 98 with fewer than 2
  rooms, 72 without doors, 130 without windows) to harden plan detection across drawing styles; documentation rewrite
  (README = concept and how to run, ARCHITECTURE = contracts, DEVLOG = history); git repository initialised and pushed.

## Oct 24 14:20: plan detection across all 444 plan images (ROADMAP step 1)
- `app/plan3d/sweep.py` runs the geometry-only engine over every plan and writes per-building contact sheets
  (`sweep/<lid>.jpg`) and `sweep/sweep.json`; `sweep_compare.py` diffs two runs (ok / rooms>=2 / doors>0 / windows>0).
- Styles found and handled: SightMap schematics (350-480 px, grey exterior walls, thin windows); architect marketing
  sheets with titles and footers (777 Tenn, 1000 Green, 1333 Gough with coloured room fills); marketing plans with heavy
  grey exterior wall fills and furniture drawn (Solaire, Alchemy, Jasper); off-white paper scans (33 8th); photos
  mislabelled as plans; 3D rendered "plans" (1177 Market, Nob Hill Tower), which are out of scope and rejected.
- Fixes this round: paper-tone normalisation; stroke thickness from LONG skeleton strokes only (titles no longer hijack
  it); two wall weights per tone class (thin interior + heavy exterior) with geometry parameters from the dominant one;
  elongated thick components are walls, compact ones are blocks; door reference width from confident arcs in an
  image-relative range (2.5-12% of the image) so title letters cannot set it; windows on long gaps need parallel lines
  and a blank outside; renders rejected by gradient softness (soft/hard ratio > 3), coloured fills allowed.
- Metric after v3 (strict rejection, before the colour relaxation): rooms>=2 320 -> 325, doors>0 346 -> 348, windows>0
  288 -> 304 of 418 readable plans; 777 Tenn went from 1/15 to 15/15. v4 running with coloured plans re-admitted.
- Still weak: tall narrow plans with large black exterior masses (Jasper), bathroom enclosure when the door arc is faint,
  entry corridors open to the front door, thin closet-back walls read as gaps.

## Oct 24 15:10: checkout and furniture agent delivered by workers
- `app/checkout/`: FastAPI :8766; cart from furnishing plans; budget enforcement; delivery/assembly scheduled before the
  move-in date; card rail (intent, tokenised test card, 3-D Secure, authorisation, server-enforced stop before capture,
  human Confirm); x402 rail with the official SDK middleware, real EIP-3009 signatures, local mock facilitator :8767
  (switches to the CDP facilitator when CDP keys exist; on-chain cap $1). Receipt and order JSON. HOLD.md 7-8.
- `app/furnish/agent.py` + `agent.js`: streaming planner (Haiku, ~$0.002 per room): shortlist within budget and style,
  one-by-one placement with earlier items pinned, door-passage test, honest rejections ("over budget by $249", "cannot pass
  the 0.76 m door"), summary with palette; chat edits (move/add/remove/swap) re-validated by the solver; top-down
  animation, red flash at the door for rejections, camera presets, 2x render download. `/api/agent/furnish` (SSE),
  `/api/agent/chat`. `--drama` makes the first pick a deliberate failure for the demo.
- Vendored three.js 0.170 + Draco + 3 CC0 HDRIs under app/vendor (fetch.sh) so the demo does not depend on CDNs.

## Oct 24 16:50: one scale rule for all plans (owner's call: doors are oversized, units came out tiny)
- `app/plan3d/rescale.py`: interior area must match known square footage: per-plan sqft from the listing when available
  > sqft printed on the plan (annotation) > SF bedroom-count prior (studio 42, 1BR 62, 2BR 88, 3BR 115 m2 gross, interior
  0.85 of gross). Door-width scale is only the initial guess. Printed-dimension plans keep their reader scale.
  Result: 1BR median interior 27 -> 53 m2, 2BR 39 -> 75 m2 over 277 rescaled layouts. Wired into batch.py.
- SightMap (Greystar's plan-image provider) exposes unit areas per floor plan, but Greystar pages do not embed the
  property's map key (the CDN asset key leads to unrelated properties), so no per-plan sqft for Greystar; the Greystar
  page has no sqft at all. `feasibility/sightmap_sqft.py` kept for buildings that do embed it.
- Walk physics (`app/plan3d/walk.js`, WALK.md): collisions with walls/furniture/fixtures, doors closed until opened with E
  (hinge animation, block while closed), crosshair, room HUD, bump feedback. Render pass: see app/plan3d/review/REPORT.md.

## Oct 24 18:20: map front door, screenshot sweep, spend
- `app/map/` (Opus worker): Leaflet with OSM tiles proxied and cached at /tiles (325 tiles pre-warmed for SF z12-15),
  104 listings with photo strips, plans, beds/baths, price (RentSFNow) or "pricing on request" (Greystar), filters,
  hover-synced pins/cards, detail drawer (gallery, plans, description, 3D units with Open 3D / Walk / Furnish / Checkout),
  compare tray for 3 units. RentSFNow geocoded via Google ($0.37, cached in geo.json). Data defects found: 27 RentSFNow
  units are Oakland/LA (scraper hard-coded "San Francisco"; fixed for future runs, map hides them), the neighbourhood
  field was a site-wide default, Greystar bodies are contact-form boilerplate, 276 of 289 units are on the bedroom
  prior for size and are labelled "typical size".
- Screenshot sweep (quality=low) over 288 units: 0 black frames, 9 headless screenshot timeouts (two units), no page errors.
- Anthropic spend $8.89 of $10 after annotating 68 units (reader + repair + annotation ~5 cents each); batch paused.
  Plan-engine leftovers are being fixed by an Opus worker against the saved sweep baseline and golden layouts.

## Oct 24 19:40: engine v2 applied; three "win" workstreams started (owner's brief, Opus agents)
- Engine v2 (Opus worker): leak repair (exterior gaps always closed, weak-arc interior doors when they enclose a room),
  single-line thin walls, region sanity (min 0.6 m2, merge across non-wall lines, cap 16 rooms), polygon validity and
  overlap trimming, wide openings kept as "opening". Sweep: rooms>=2 338->360, bath-sized rooms 250->295, >16-room
  plans 9->0, invalid polygons 21->0. Library rebuilt geometry-only for non-annotated units: 359 walkable units now
  (was 289). 93 annotated units kept their names/fixtures; 777 Tenn demo unit annotated and pre-furnished. Goldens
  regenerated. Spend $8.99 / $10.
- Started (Opus): (1) library to ~500 plan-backed units via AvalonBay (plans with true sqft) + on-demand Claude
  annotation button under the ledger; (2) honest side-by-side: listing photo | our render from the photo's camera |
  low-strength img2img polish with our depth as control; (3) metrics: breadth, plan-to-3D seconds, scale accuracy vs
  printed dims/sqft, CubiCasa5K sample if obtainable -> metrics/summary.json shown on the landing page.

## Oct 24 21:30: side-by-side, catalogue, metrics landed
- Side-by-side (`app/plan3d/polish/`, Opus): camera per photo from VGGT FOV + single-view metrology (wall x-ranges
  marked by hand where geom's corner split failed), render + depth from polishcam.js, SD1.5 img2img strength 0.35 with
  depth ControlNet 0.9 and IP-Adapter 0.5 on the listing photo. Six pairs; one demo-worthy (1000 Green corner living),
  one close, one fair, two weak, one poor (a plan-engine bug: jagged south wall + toilet in a bedroom, gs-20665 r0).
  Gallery polish.html with verdicts. The gap is mostly plan-vs-photo unit mismatch and plain materials, not the polish.
- Catalogue: 466 IKEA products, 383 local GLBs (507 MB), all images, style tags, variants. Materials: 2,927 CC0 done.
- Metrics (`app/plan3d/metrics/`): 444 plans / 26 buildings / 359 walkable units; plan -> layout 0.49 s median, page to
  first frame 3.8 s (SwiftShader); door-width scale vs printed dims 12.6% median error (n=41), room dims 11.3% (n=80);
  CubiCasa5K 100-plan sample: room IoU 27% vs the paper's trained 57%, out of domain, not for the landing page.

## Oct 24 22:40: library at 813 units / 58 buildings; on-demand annotation; metrics re-run
- AvalonBay rejected (terms forbid robots/scrapers, despite robots.txt); Essex, Equity, Tishman bot-walled; used UDR
  (no terms page, robots allow; per-plan sqft -> 82 true-size units) and Greystar's inner Bay Area properties (plans
  only). `feasibility/scrape_udr.py`, `scrape_greystar_bay.py`. Geometry built for all; 813 units, 134 true size.
- `app/plan3d/annotate_on_demand.py` + `POST /api/annotate` (ledger-checked, one at a time, keeps the old layout if
  the new one is not annotated, warns when rooms cover < half the listed sqft). Landing and map show the button.
- Landing hero: library counts, four metric tiles, "How we measured", side-by-side link. reindex.py now carries
  bedrooms/sqft/annotated per unit. Spend $9.07 / $10.
- Known: many new plans read poorly (13-16 small rooms, or only a bath found); the 444 -> 359 breadth tile predates the
  library growth and bench.py was re-run after it.

## Oct 24, evening: learned walls

The classical plan reader (thresholded ink) was judged fundamentally wrong on sight: windows on interior walls, baths and
closets dropped, 1333 Gough's wood textures read as 475 walls, its key plan built instead of the apartment. Zero-shot
CubiCasa5K (pretrained, no training) found walls far better on 23 test plans, so it now drives the engine:
- `cubi.py`: walls rescaled to ~12 px, 4-rotation TTA on MPS (~1 s/plan, 982 plans in 15 min); crop = convex hulls of
  the predicted wall groups >= 1/3 of the largest (drops key plans, logos, margin blotches; keeps both townhouse levels).
- `plan_engine.extract`: walls = model wall pixels with ink near them (keeps drawn door gaps, hairline walls, double-outline
  walls closed into one band); model windows/doors placed on their wall pieces; rooms close against the full model mask
  (diagonal and rotated walls no longer leak); diagonal walls fitted from the leftover mask; thin_walls skipped.
- `rebuild.py`: offline rebuild (Anthropic ledger is at $9.1 of $10: no paid calls); names, fixtures and materials carried
  over from the previous layout by pixel overlap; 792/813 rebuilt, 789 promoted (old ones in `layouts_ink/`), 5 units with
  saved furnishing plans left as they were.
- `room_names.py`: Apple Vision OCR of the printed labels names 2276 rooms; generic "Room N" names 4216 -> 1380.
- `labels.py`: 8 Sonnet subagents reviewed 320 plans (300 train, 20 held-out from 20 buildings) and flagged errors in
  percent coordinates; flags are snapped to the ink into wall/window/door labels for fine-tuning.

## Oct 25 00:40: taste tier (owner's direction)
- Owner: IKEA reads as cheap; the agent must show taste. Plan: a "Design" catalogue tier scraped from manufacturers'
  own sites (Vitra, Fritz Hansen, HAY, Muuto, Herman Miller, Knoll, &Tradition, Gubi, Carl Hansen, Cassina, B&B Italia,
  Poliform, Flexform, Minotti, Moroso, Audo, Normann, Ferm Living, String, Louis Poulsen, Flos, Artemide, Tom Dixon, Hem,
  Artek, Thonet, USM) with descriptions, dimensions, prices and buy links; OBJ/FBX/3DS converted to GLB and compressed.
  Owner's policy for this: public pages and public downloads only, polite pacing, no captchas or bot-wall tricks, no
  account creation by the agent (login-gated brands listed for the owner). Sonnet worker running.
- Also decided: budget tiers in the agent (Budget = IKEA, Standard = Amazon, Design = manufacturers); a path-traced
  or SD-polished "Render" step as the archviz finish (SDXL img2img with depth control is ~20-40 s on the M4);
  Google Earth / Street View outside the windows back on the list for tomorrow within the $5 Maps budget.
- Catalogue is model-only now (83 IKEA products without models removed); Amazon prices are estimates (IKEA category
  median x 1.5) labelled "est." in viewer, cart and receipt; dead Amazon links fall back to a search link (checker running).

## Oct 24, night: townhouses, stairs, jumping; fine-tune

- `levels.py`: a plan with two or more drawings is multi-level when it has stair labels (UP / DN) or level captions;
  "Typical / Alternate" drawings without them are variants and stay as they were (40). Levels ordered by UP vs DN and
  captions (ENTRY / LOWER / FIRST vs UPPER / SECOND / LOFT); upper levels aligned onto the lowest by template matching the
  predicted wall masks. Stairs: tread-length lines clustered from the label outwards give the stair compartment; a straight
  run climbs along its long side from the label's end; walls inside the compartment are cut. Footprint per level (flood
  fill of the closed wall mask) -> floor slab (above ground) and ceiling slab, minus the stairwell; "OPEN TO BELOW"
  mezzanines keep room floors only. 24 units stacked, 15 with stairs, 11 lofts / mezzanines.
- `build.js`: one group per level at its elevation; slabs; floors / ceilings with the stairwell cut; generated steps.
- `apartment.html`: level buttons (one level cut at the section height, or all lifted apart); furniture rides with its level.
- `walk.js`: feet height, gravity, Space jumps (~0.9 m), auto step-up 0.32 m (stairs), walls per level band, furniture /
  fixtures / steps are surfaces below step height and obstacles above it, the next level's slab is the ceiling except over
  the stairwell. Tested headless: up the 14 steps of gs-22226_plan_22 to the upper level and along its hall; jump arc;
  standing on a tub.
- Found: the app proxy's listen backlog (5) resets connections when the viewer imports ~40 modules on a loaded machine.
- `finetune.py`: CubiCasa model fine-tuned on the 300 reviewed training plans (BCE + Dice on p(wall), p(window),
  p(door), batch-norm frozen, 3000 iterations of 4 random 512 px crops, ~31 min on MPS); scored on the 20 held-out plans.

## Oct 24, late night: hybrid model live, no protected units

Fine-tune result on the 20 held-out plans (20 buildings): walls fix 74% of the reviewer-flagged pixels, wall precision
0.94 -> 0.98, 1.3% of already-right wall pixels broken; windows / doors slightly worse (tolerant F1 0.93 -> 0.89, 0.98 -> 0.95).
Pixel IoU fell (walls 0.90 -> 0.85) partly because the labels inherit the pretrained model's exact edges. Visually the
fine-tuned walls are cleaner (diagonal plans, counters, showers). So the engine now uses a hybrid (`cubi.WALLS_TAG = ft1`
walls + crop + levels, `ICONS_TAG = ''` pretrained windows + doors); `hybrid_run.sh` re-predicts, rebuilds every unit
(names / fixtures / materials carried from `layouts_ink/`, the original annotated layouts), promotes, renames from plan
text and re-stacks levels. The previous live set is in `layouts_zs/`. No protected units any more: furnishing is meant to
be made live on each click, so saved per-room plans of rebuilt units (their room ids change) moved to
`app/furnish/plans_archive/`.

## Oct 25 03:10: design tier live
- Manufacturer scrape (Sonnet): 3,268 designer pieces with compressed GLBs (10 GB -> 440 MB), 14 brands; ~550 priced
  (brand shops in EUR/GBP/USD converted, DWR matches for HAY/Muuto/Fritz Hansen); 544 flagged dims_mismatch. Catalogue:
  5,151 products, all with models. Tiers in planner/agent/UI: Budget (IKEA), Standard (+Amazon), Design (manufacturers,
  size-verified and priced first). First Design-tier run on the 1000 Green living room: HAY sofa, Alle coffee table,
  Dedal shelf, Artek floor light, Pocket armchair, Lolly side table, $14,329 of a $15,000 budget.

## Oct 24, late night: doors

Doors were drawn and read short (34% under 0.70 m, 21% under 0.60 m; not walkable) and their swings were near random
(four options evenly split). `doors.py` on every layout: widths by what the door opens into (entry 0.91, rooms 0.81, bath
0.76, closet 0.71; >= 1.0 m into a closet -> two-leaf bifold; >= 1.3 m in an exterior wall -> two-leaf glass; > 1.3 m
between ordinary rooms -> cased opening), widened around the drawn centre inside the wall and clear of neighbours;
duplicate doorways (same gap found 2-3 times on short parallel wall pieces) reduced to one (665). Swing: the four quarter
arcs of the drawn leaf tested against the plan ink (32% clear), else the rule (into the room it serves, hinge at the end
nearer the wall's end). Doors under 0.70 m: 2986 -> 171 (the rest sit in walls too short to widen). `door_styles.py`:
OWLv2 finds the doors in the listing photos, CLIP classifies the crops (21 listings have photos: 16 slab, 3 shaker,
1 panel, 1 wood; the rest default to shaker). `build.js` draws slab / shaker / six-panel / wood / glass / bifold leaves,
hinge knuckles, lever or knob; `walk.js` animates two-leaf doors. Tested: a door drawn 0.54 m (now 0.91 m) opens with E and
is walked through.

## Oct 25, early morning: the black slab was the bed
- The black footprint-shaped block in the primary bedroom was the Gubi Stay Bed: its manufacturer GLB has no vertex normals (814 of 3,363 designer files), GLTFLoader hides that with flat shading, and the material fallback (`_dressUntextured`) replaced the material and lost the flag, so the mesh lit black. Fix: compute normals before re-dressing. The ceiling guard added earlier was a wrong diagnosis (harmless, kept).
- Viewer's walking-path check now uses the solver's rule (small pieces such as nightstands, lamps, mirrors, rugs neither block nor need the 0.75 m corridor), so the panel no longer contradicts the agent.
- Designer meshes: 2,289 of 3,363 untextured, 190 ship a pure-black material (recoloured from catalogue words).
- Double-door "pair" error from the owner's console did not reproduce headless on gs-22612_plan_07; left as-is, watch for it on the real GPU.

## Oct 24, late night: townhouses without labels; walkable stairs

Admirals Cove "Meridian" (gs-16169_plan_00) has two drawings with stair treads but no UP / DN and no level captions, so it
was taken for two variants. `levels.py` now also finds stairs without labels (a cluster of tread-length lines holding a
run of >= 4 parallel lines 18-36 cm apart, ink threshold 220 for thin grey treads) and calls a plan multi-level when two
drawings have drawn stairs, or when exactly one drawing has the kitchen and the others only bedrooms / baths (ground =
the kitchen / entry drawing). Stair direction: the end that is open on its level (a wall along the chosen bottom or top
edge flips it). Passage guaranteed: upper-level walls over the stairwell and walls across the entry band (bottom) and exit
band (top) are cut, fixtures on the steps removed. `walk.js`: steps only block sideways when far above the feet (steep
stairs have 18 cm treads; the body overlapped two before standing on one). 38 multi-level units, 4 of them three storeys;
a headless harness walks every stair: 25 of 32 reach the next floor (failures: the second flight of the 3-storey
gs-20953 units is drawn as a switchback over the first, and 3 one-offs). Saved furniture of the upper rooms of
gs-16169_plan_00 shifted by the level offset.

## Oct 25, small hours: colour, orientation, templates
- Colour. Manufacturer files carry none (2,900 of 3,268 grey/white). Three layers now dress a model at load (`furnish.js _dressUntextured`): the brand's own texture pack where it exists and the mesh has UVs (Muuto, Hem, Carl Hansen: `designer/brand_textures.json`, 811 products, exact variant colours as texture means), else the hero photo read by Haiku subagents in Claude Code (49 batches of 50, `designer/palette/`, merged into `designer/palette.json`: 1,964 products with parts in size order, finish class, hex; 484 skipped because the photo was a line drawing, a blank, or a family shot without the product), else product words. Finish classes map to PBR (fabric normal maps from the CC0 library, lamp shades glow a little).
- Orientation. Catalogue dims had their axes mixed per scraper; `place.fix_item` canonicalises per category (rug thin, mirror thin in depth, bed longer than wide, wall pieces wider than deep) and repairs misfiled categories. The viewer fits a model into the listed box with the 90-degree rotation that distorts it least instead of stretching it. Chairs around a table and armchairs beside a sofa had their facing sign inverted; fixed. Opus subagent ran a geometric + CLIP orientation pass (`designer/orient.json`), integration pending.
- Templates. `agent.TEMPLATES`: layered slot lists per room type with minimum areas (core, companions, light, soft, decor), degrade from the end. Relations added: lamp on nightstand/side table (y_m), pendant above table/bed with a cord to the ceiling, bench at the bed's foot, side tables beside seating, corner-loving plants and lamps, wall-hung mirrors at eye height. Wall positions are scored by the open room in front of them (a sofa no longer sits at a corridor mouth). Design tier borrows IKEA/Amazon in categories with fewer than 20 designer models, labelled in the panel.
- Prices. 2,728 unpriced designer items got estimates (brand x category medians with width scaling, `designer/prices_estimate.py`), stored exactly like the Amazon estimates (`price_source: estimated`), labelled est. in the panel and checkout.
- Test unit gs-22612_plan_07, design tier: dining 13 items (table, 6 chairs facing it, pendant, rug under, cabinet, lamp, plant, mirror), bedroom 11, living 12. Spend cap raised to $20 by the owner; agent runs cost about half a cent each.

## Oct 24/25 night: real stairs, side-by-side overview, solid floors

User review: the overview must show the levels side by side as on the plan; walking stacks them; lower walls showed
through the upper floor; stairs were straight where the plans draw U / L shapes. Now:
- `build.js arrangeLevels('plan'|'stack')`: dollhouse = every level at ground height where its drawing sits on the plan
  (stairs included); walk = stacked. Upper levels sit at k x (ceiling + 0.30 m) on a solid extruded slab (footprint minus the
  stairwell; rooms on a mezzanine), between the white ceiling below and the room floors, so lower walls end inside it.
- `levels.py make_stair`: flights read from the drawn treads, upper level's drawing first (it shows the whole stair from
  above), lower drawing as a second source; detection = thin ink on the local background (fills too), walls removed,
  tread-length strokes per orientation, smeared into blocks, validated by even spacing 0.18-0.36 m (a Hough-line reader as
  fallback). Flight pieces merged; the stair = the subset (1-4 flights) whose risers match the height (~0.18 m), chained
  in walking order with landings (corner square for L, both widths for U, the gap for straight), continuous by
  construction. Walking order: among equally short chains (a U can turn at either end), the one whose first flight the
  lower drawing shows, with UP at the bottom and DN at the top. Arrival pad at the top. Steps solid near the floor,
  35 cm treads higher up (rooms under a stair keep their walls); the upper floor opens only where headroom needs it
  (steps >= 0.75 m); walls cut with their thickness, upper level only over the opening; search clamped to each level's own
  drawing. No legible treads -> no stair is invented (the levels still stack). Handrails on open flight sides.
- `walk.js`: edge guard (no stepping off a stair side or into the stairwell), walls under a stair ignored while on it,
  a stair overhead not in the way, steps from the layout.
- Result: 38 stacked units, 20 with stairs (10 U, 8 L, 6 straight); a headless harness walks every stair along its
  steps: 22 of 24 reach the next floor (gs-15582_plan_14, gs-22226_plan_03 still stop partway).

## Oct 25: thick exterior corners swallowed rooms

1333 Gough "C" (gs-18149_plan_02) had no kitchen / dining and no south or east wall there. `plan_engine.wall_rects` treated
compact blobs of thick ink as solid blocks (columns, fireplaces) by their bounding box only; two thick exterior walls
meeting in an L have a square box, so the box was filled in as wall and swallowed the kitchen and dining, and the walls
around a non-room were then dropped. A block must now fill >= 60% of its box. All units rebuilt in staging: 713 single-level
units unchanged, 26 regained substantial area (up to 3.9x: halves of apartments were missing), 3 lost a little; the 61
changed units were promoted (none had saved furniture) and renamed / leveled / doors redone.

## Oct 25, before dawn: gallery and lights
- `furnish/gallery.html`: every product in live 3D through the viewer's own addItem (model, dressing, orientation, fit), 100 per page, beside its hero photo; filters by source, brand, category, dressing source, orientation confidence; flip / rotate / flag per product saved through `POST /api/gallery_flags` to `furnish/gallery_flags.json`, and the viewer applies the owner's yaw fixes on load. The first HAY page exposed upholstered chair variants filed as "other" with height and depth swapped (lying on their backs): categories now inherit from a sibling product whose name is a prefix ("AAC 121" -> "AAC 121 Soft"), and chairs are forced taller than deep.
- Lights. `wall_lamp` and `ceiling_lamp` categories from names (wall / parete / sconce; ceiling / soffitto / recessed / spot); sconces hang at 1.75 m beside beds, nightstands and mirrors, never on glass; one ceiling fixture per room in the open middle of the ceiling, skipped when a pendant already lights a small room; lamp slots in every room template (kitchen, hallway, bathroom and laundry get a ceiling light). In the viewer every lamp carries a warm point light (a spot for downlights), a soft additive halo and a scalable shade glow; one pendant per room casts shadows outside low quality. The apartment page has an **evening** button (`?evening=1`): sun to the horizon, dusk sky, environment down, bloom up, the builder's generic per-room fill lights step back and the agent's lamps carry the room (`Furnish.setLampLevel`). Headless check: kitchen mean brightness 207 by day, 161 at dusk, warm pools under the pendant and the ceiling fixture.
