# Handoff brief (written Oct 25 2026, ~01:30 PDT, by the Fable session for the Opus session)

Judging is **today, Sun Oct 25, 10:30-12:30**. Solo hack, Cal Hacks 13.0. Read `README.md` (what it is, how to run), `DEMO.md`
(3-minute script), `ROADMAP.md`, `HOLD.md` (owner decisions), and the last three entries of `DEVLOG.md` (what happened tonight).
`ARCHITECTURE.md` has every data contract. The owner is at 99 percent of weekly usage: be economical, prefer Sonnet subagents
for mechanical work, do not spawn agents you do not need, and keep committing and pushing to `zMako/sunlit` (private; large data is
gitignored, see `.gitignore`).

## State in one paragraph
Plan to walkable 3D works for 813 units. Furnishing: `app/furnish/agent.py` streams an agent (Haiku picks, `place.py` solves,
viewer `furnish.js` renders real product GLBs) over layered room templates (`agent.TEMPLATES`) with relations (chairs face the
table, lamps on nightstands, pendants above tables with cords, benches at bed foot, sconces, ceiling lights). Catalogue: 5,151
products with models (IKEA 383, Amazon 1,500, designer 3,268 across 14 brands); dims and categories are repaired on load by
`place.fix_item`, never trust `catalog.json` raw. Colour: brand texture packs > Haiku photo palette (`designer/palette.json`) >
product words. Orientation: `designer/orient.json` (up axis + front), applied in the viewer with a 0.6 confidence floor, plus an
extents-based 90-degree fit. Owner corrections from `app/furnish/gallery.html` land in `app/furnish/gallery_flags.json`
(yaw fixes are applied by the viewer already; "wrong" flags are NOT yet excluded from the agent's pool: do that first, it is
ten lines in `agent.catalog()`). Lights: every lamp carries a point light, halo and glow; `apartment.html` has an **evening**
button. Checkout (`app/checkout/`) runs card-sandbox and x402 on testnet. Spend: `app/spend.json`, caps in `app/spend.py`
(Anthropic $20, used ~$9.3; Google $5). Test unit used all night: `gs-22612_plan_07` (rooms r0 living, r1 bedroom, r5 dining,
r9 kitchen); plans in `app/furnish/plans/`.

## Run and verify
```
cd app && set -a && . ../.env && set +a && nohup ../feasibility/.venv/bin/python proxy.py 8765 > proxy.log 2>&1 &
open "http://127.0.0.1:8765/plan3d/apartment.html?unit=gs-22612_plan_07&furn=r1"      # add &evening=1 or &quality=low
open "http://127.0.0.1:8765/furnish/gallery.html"                                      # catalogue, 100 per page
cd app/furnish && ../../feasibility/.venv/bin/python agent.py furnish gs-22612_plan_07__r1 --budget 12000 --style "warm scandinavian, oak, linen" --tier design
```
Restart the proxy after editing `proxy.py` (`kill $(lsof -ti tcp:8765)`, then the nohup line). Headless screenshots: Playwright
with `p.chromium.launch(channel="chrome", args=["--use-angle=swiftshader","--use-gl=angle","--enable-unsafe-swiftshader"])`;
the page exposes `window.__cam = {camera, orbit, scene, sun, hemi, renderer, layout()}`, `window.setWalk(roomId, yaw)`,
`window.setDoll()`, `window.setEvening(bool)`, `window.furnishByRoom`, `window.furnishInstances`. Software GL cannot do bloom
or high quality; use `quality=low` and judge glow on the owner's GPU. The owner's browser is the real test.
JS syntax check without a bundler: `node -e "new Function(require('fs').readFileSync('app/furnish/furnish.js','utf8').replace(/^import .*$/mg,'').replace(/^export /mg,'').replace(/await /g,''))"`.

## Conventions that bite
- Metres; x right, z down on the plan, y up. Item `rot_deg` is stored so that the viewer does `rotation.y = -rot_deg`; the
  solver's internal yaw is the negative (see `place.footprint`). Local +z of a model is its front.
- Plan item fields: `x, z, rot_deg, w_m, d_m, h_m, y_m (bottom height), floor:false (hung/carried), borrowed, price_source`.
- `place.SMALL` items neither block nor need the 0.75 m corridor; `feasible()` ignores items with `floor: false`.
- Viewer `addItem(spec)` is the single pipeline: model candidates (recorded path first), orientation record + owner yaw fix,
  extents permutation fit, `_dressUntextured` (brand texture / palette / words), lamp light, mattress on frame-only beds.
- Another Claude session of the owner edits `app/plan3d/apartment.html`, `build.js`, `home/*`, `landing.html` (levels, landing
  page, fonts). Pull before editing those; stage only your files; mention in the commit when you had to include their hunks.
- Never call the Anthropic API from scripts without going through `app/spend.py`; agent runs cost about half a cent each.

## Next task the owner asked for: the props kit (procedural decor)
Goal: rooms read as lived-in on renders. Procedural, not catalogue: rounded boxes with the CC0 fabric normal map
(`/furnish/materials/Fabric019/normal.jpg`, see `Furnish._bump`), thin boxes for books, planes for art, curtains from window
geometry. Colours from the room's palette: the agent writes `palette`, `wood`, `accent` into the plan JSON (`plans/<room>.json`),
fall back to the item's own finish. Implement in `furnish.js` as `_props(it)` called after `_lamp(it)` in `addItem`, children
of `it.obj` so they move with the piece, and a room-level `_roomProps()` for curtains and wall art (needs `this.meta`: polygon,
windows with edge/s0/s1/sill/height, ceiling_m; see `rooms_export.py` output in `app/rooms/`). Props carry
`userData.prop = true`, are skipped by `check()`, `_paths()`, raycast selection and the cart, and sit behind a **props** toggle in
the furniture panel (default on; `localStorage props`). Keep it restrained: one accent colour per room, matte fabrics, few items.
Per anchor:
- bed: duvet (rounded slab w-0.1 x 0.12 x d*0.7 from the foot, folded edge), 2-4 pillows (0.5 x 0.12 x 0.7, random tilt 3-8
  degrees, two rows for 160 cm+), a throw across the foot (thin slab, accent colour).
- sofa / armchair: 2-3 cushions (0.45 square, leaning on the back, slight yaw jitter), one throw over an arm.
- coffee_table / side_table / nightstand / dining_table: book stack (2-4 thin boxes, random heights 0.02-0.035, spines in two
  muted colours), one bowl or candle group (short cylinders), one small plant on side tables only.
- bookcase / tv_bench / dresser: runs of books (6-12 thin boxes, varied heights, gaps), two objects, one plant.
- walls: one framed piece above the sofa and above the bed (plane + thin frame, image from a generated gradient or a listing
  photo via `/listings/<lid>/NN.jpg`; the unit's lid is the part before `_plan`), centred, bottom at 1.25 m above seat height.
- windows: curtains, two sheer panels per window in the wall tone, from floor to 0.1 m under the ceiling, 0.08 m off the wall.
- floor: plants in corners already come from the catalogue (`plant_pot` slots); do not add fake ones.
Verify with headless shots of r0, r1, r5 (`roomcam.py`-style camera above the room), then commit. Then re-run DEMO rehearsal.

## Other open items, in priority order
1. Exclude `gallery_flags` "wrong" items from `agent.catalog()` (and the deterministic `plan.py`).
2. Props kit (above).
3. Real-GPU pass of the whole demo path by the owner; tune `Furnish.lampLevel` day/evening numbers and `base` candela per
   category if rooms look over-lit; `_lamp` is in `furnish.js`.
4. Second nightstand often finds no wall spot (door beside the bed): allow a nightstand 0.05 m into the door clearance or
   centre the bed on the wall segment away from the door (`place.py` wall candidates, nightstand branch).
5. Rug default variants from Muuto packs are dark; prefer the lightest variant when the style brief says warm/light
   (`furnish.js _dressUntextured`, brand texture branch; `brand_textures.json` has every variant's mean colour).
6. Tables lying on their side (orientation pass misses them; `orient/REPORT.md`): a "largest flat horizontal surface is up"
   rule in `designer/orient.py`, or flag them in the gallery.
7. 54 designer GLBs have no faces (points only) and need re-conversion; 820 designer items have no hero photo.
8. Docs: keep DEVLOG dated; HOLD items for the owner (Visa/Coinbase packs, CDP keys, track framing, login-gated brands).

## Do not
- Do not stretch models to the catalogue box without the orientation step; do not re-export the GLBs.
- Do not commit `catalog_fixed.json`, `palette/thumbs`, `palette/results`, `designer/textures`, `orient/cache` (gitignored).
- Do not bypass bot walls or create accounts; the owner does logins by hand (`designer/LOGIN_NEEDED.md`).
