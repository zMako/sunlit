# Sunlit build plan

Oct 23, 2026, 23:50 · phases are run one at a time, each ends with a test you look at before the next starts.

## Ground rules

- **Hard spend cap: $5 total across Google Maps Platform and Anthropic.** Everything below is designed to stay inside free tiers; the cap is the backstop, not the budget.
- **Keys never leave this machine and never enter the browser.** `.env` is git-ignored. The viewer talks to a local proxy that adds the Google key server-side; the HTML never contains it. Anthropic calls run only from Python scripts.
- **Every paid call goes through one ledger** (`app/spend.json`): counts root-tile requests, geocodes, Street View fetches, and Anthropic tokens with an estimated dollar value. Each wrapper refuses to call when its line would cross its sub-cap. Sub-caps: Google $2.00, Anthropic $2.50, $0.50 reserve.
- **Nothing in the demo depends on a live paid call.** Three listings plus the Cal Hacks block are precomputed and cached on disk; the live "judge's address" path uses only city data and local models unless the exterior tiles are already cached for that block.
- **Exterior tiles load on a button, not on page load.** Every page load of a Photorealistic 3D Tiles scene is one billable root-tile request. 1,000 are free per month; dev reloads burn them fast.
- **Console quotas set by you (Oct 23):** Map Tiles 500/day per SKU, Geocoding 500/day, Street View Static 500/day. All sit inside the monthly free tiers, so Google spend is $0 unless a quota is raised. No Solar API use: Data Layers is roof-level shade at $75 per 1,000 and adds nothing over the LiDAR footprints and 3D Tiles we already use.
- **Local models first.** VGGT, MapAnything, OWLv2 and the geometry pipeline are local and free. Claude is used only where judgment is needed (room graph, floor-plan parsing), with Haiku 5.5 during development and Opus 5.5 for the final precompute.

## Pricing basis (checked Oct 23, 2026)

| Service | Free per month | Then |
| --- | --- | --- |
| Map Tiles API, Photorealistic 3D Tiles (per root-tile request) | 1,000 | $6.00 / 1,000 |
| Street View Static API | 10,000 | $7.00 / 1,000 |
| Street View Tiles | 100,000 | $2.00 / 1,000 |
| Geocoding API | 10,000 | $5.00 / 1,000 |
| Claude Opus 5.5 | none | $4 in / $20 out per MTok |
| Claude Haiku 5.5 | none | $0.10 in / $0.50 per MTok |

A room-graph call with 15 listing photos is roughly 25k input tokens: about $0.10 on Opus 5.5, under a cent on Haiku 5.5. Twenty dev calls on Haiku plus three final Opus calls is under $1. The only way to hit $5 is reloading a 3D Tiles page a thousand times, so that is the thing the ledger watches hardest. You should also set a daily quota on the Map Tiles API and a billing alert in the Google Cloud console; I cannot do that with an API key alone.

## Phase 0: guardrails (30 min)

Spend ledger, key proxy, wrappers for every external call, a `make test` that proves the keys are absent from everything under `app/` that the browser can fetch.

Test: ledger increments on a dry run, a wrapper refuses past its cap, grep finds no key strings in served files.

## Phase 1: clean room geometry (2 to 3 h)

Automatic room clustering from the cross-view consistency graph, so photos like the floating hallway are excluded instead of hand-picked. Classify every pixel by its normal: floor, ceiling, wall, other. Snap floor and ceiling to planes, walls to fitted planes. Rotate to Manhattan axes from the wall-normal histogram. Replace the rubber-sheet faces with a two-tier mesh: exact for photo views, clipped for free orbit.

Test: the three rooms re-exported. Walls flat, no fans, no floating fragments, camera heights within 10 cm of each other inside a room.

## Phase 2: floor plan from free space (2 to 3 h)

Status: Phase 0 and 1 passed user test Oct 24 (photo views exact, proportions right, nothing floating). Carry-over: walls that got no fitted plane stay curved (Nob Hill living photo 2); fix here by snapping wall pixels to carved wall segments.

Every camera-to-surface ray is known empty space. Rasterize those into a top-down occupancy grid, take the boundary of the free region, regularize into an axis-aligned rectilinear polygon with the ceiling height. Snap window and door detections onto the nearest wall segment as openings with width, height and sill. Project each photo onto the walls it saw; unseen wall gets the wall's median colour.

Test: closed polygons for all three rooms, areas plausible for the listing type, openings on exterior walls, a clean "walls+floor" view that reads as architecture.

## Phase 3: analysis-by-synthesis fit (3 to 4 h, start only if Phase 2 is done by 14:00 Saturday)

Parameterize the room (polygon vertices, height, openings, camera poses). Depth along a ray to a plane is closed-form, so render predicted depth, normals and wall/floor/ceiling masks per photo without a rasterizer. Optimize all parameters jointly against the network predictions. This is one consistent model per room, with poses refined in the same loop.

Test: reprojection error drops versus Phase 2, dimensions stable across random restarts, no photo worse than before.

## Phase 4: exterior and orientation (3 h)

Status Oct 24: Phase 3 passed (fit converges; one Broadway wall ambiguous by 25 cm where cabinets are). Phase 4 built: `pipeline/sitectx.py` (geocode via proxy, SF footprints, OSM streets with mirrors+cache, building sides as facades, party walls excluded, floor from unit number), `pipeline/suncue.py` (sun patches on the floor -> sun direction per candidate facade, scored against the local sun envelope), `pipeline/orient.py` (window wall -> facade, world placement, year sun hours per window), `site.html` (block + rooms + counted 3D Tiles button).

Photorealistic 3D Tiles for the block through the proxy, loaded on demand and counted. Ray cast sun hours against the tile meshes instead of extruded footprints. Orientation from two independent cues: interior window sizes and spacing matched to the window grid visible on the facade texture, and the sun patch on the floor in photos. Street View Static as a third cue if cheap (within the 500/day quota). Fall back to the user picking the facade.

Test: the block renders with fewer than 10 root-tile requests spent; for two listings with a known facade, estimated facing within 30°, floor within one.

## Phase 5b (done Oct 24): terrain heightfield from LiDAR ground heights inside the block (drawn and ray-marched), horizon profile to 8 km from Open-Meteo elevation (free, cached), window openings cut into layout walls, fitted room loaded into the site viewer at its placed pose inside a see-through target building.

## Phase 5: whole apartment (2 h)

Claude reads the listing text, the photos and any floor-plan image: assigns photos to rooms, labels them, parses the plan into polygons, says which rooms touch the facade. Register per-room models to the plan by shape and label. Haiku 5.5 during development, Opus 5.5 once per final listing, prompt caching on the fixed instructions.

Test: on a listing with a floor plan, rooms placed in the right adjacency; ledger shows under $1 total Anthropic spend.

## Phase 6: sun simulation and demo (3 h)

Sun hours and the moving light patch computed on the Phase 2 or 3 model: per room, per month, with the one-line verdict. Year slider, 10-second loop, "your address" path. Ground-truth check against your own room at a known time.

Test: your room's predicted sun-patch time within 30 min of observed; the 30-second demo loop runs offline from cache.

## Phase 7: stretch, precompute only (if Saturday night is free)

In order of appeal: novel-view generation to close rooms, feed-forward Gaussian splats for a photoreal fly-through of the bay window, Radiance illuminance instead of hours. Each runs against the three cached listings and ships only if the output is clearly better. None may touch the live path.

## Phase 8: ship (Saturday night, Sunday morning)

Precompute three listings plus the Cal Hacks block. Devpost draft. Pitch rehearsed ten times. Submit before 9:00 AM Sunday.

## Kill rules

- Behind schedule at 14:00 Saturday: skip Phase 3, go straight to 4.
- Behind at 19:00 Saturday: skip 5 and 7, demo single rooms.
- Any phase that breaks the demo loop gets reverted, not fixed, after 22:00 Saturday.
