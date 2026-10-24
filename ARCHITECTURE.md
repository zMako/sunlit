# Architecture and data contracts

Coordinate conventions: metres; x to the right of the plan image (east), z down the image (south), y up; image-up is north.
Rotation `rot_deg` is yaw about +y with three.js `rotation.y = -rot_deg` (furnish.js, build.js, place.py all agree).

## Listing folder: `feasibility/listings/<lid>/`
- `NN.jpg` interior photos (staged ones renamed `NN.jpg.furnished`), `NN.seg.npz` (`labels`: 0 OTHER, 1 FLOOR, 2 CEIL,
  3 WALL, 4 WINDOW, 5 DOOR, 6 MIRROR, 7 FIXTURE, 8 FURNITURE), `meta.json` (title, address, sqft_total, photo_codes for
  galleries, floorplans), `plans/plan_NN.*` plan images, `roomgraph.json` (rooms: name, type, photos[], windows),
  `plan_link.json` (photos -> plan -> room -> facing_walls; rooms with walls N/S/E/W and openings as fractions),
  `photo_facts.json` (per photo: windows sill/head/style, doors, materials top-3, colours, floor direction),
  `KEEP` / `SKIP_*` markers from `filter_listings.py`.
- `lid` prefixes: `gs-<id>` Greystar building (gallery: photos from several units), `rsn-<slug>` RentSFNow unit.

## Layout JSON: `app/plan3d/layouts/<unit>.json` (`unit` = `<lid>_<plan stem>`), see `app/plan3d/LAYOUT_CONTRACT.md`
- `scale {m_per_px, from[], sqft_listed, agreement, door_ref_px, origin_px}`; `from[0]` is the governing source:
  `reader_dims+printed` > `annotation_dims` (VLM estimates) > `door_width`.
- `walls[] {id, a, b, thickness_m, exterior}`; `openings[] {id, wall, type door|window|opening, s0, s1, width_m, sill_m,
  height_m, swing in|out_left|right}`; `rooms[] {id, name, type, polygon CCW, area_m2}`; `fixtures[] {id, type, rect
  {x,z,w,d,rot_deg}, room, against_wall, height_m}`; `materials {floor{room}, wall{room}, ceiling, door, cabinet, counter,
  baseboard}` = ids in `app/furnish/materials/index.json`; `review {issues[], usd}`.
- `layouts/index.json`: one entry per unit for `plan3d/index.html` (building, plan image, rooms, area, issues).

## Room JSON: `app/rooms/<unit>__<roomId>.json` (made by `rooms_export.py`)
`polygon` (CCW), `edges[] {a,b,dir,n outward,len}`, `windows[]`/`doors[] {edge, s0, s1, sill_m, height_m, width_m,
center, normal}`, `ceiling_m`, `bounds`, `fixtures[]`, `type`, `label`. Consumed by `place.py`/`plan.py`/`agent.py`
and the viewer. Older photo-reconstruction rooms (`p2_*`) use the same shape plus cameras/planes.

## Furnishing plan: `app/furnish/plans/<room>.json`
`{room, items[] {id, name, category, w_m, d_m, h_m, x, z, rot_deg, price_usd, product_url, image, model_glb_url,
model_glb?, why}, total_usd, walkable, picker, room_type}`. Served by `GET/POST /api/furnish?room=`; auto-arranged by
`GET /api/furnish/auto?room=&budget=&style=` (runs `plan.py`); agent stream at `GET /api/agent/furnish?...` (SSE) and
`POST /api/agent/chat`.

## Catalogue: `app/furnish/catalog.json`
`items[] {id ikea-<article>, name, category, width_m, depth_m, height_m, price_usd, product_url, image, model_glb_url,
model_glb (local), description, color, style_tags[], type_name}`. Built by `catalog.py` from IKEA US product pages
(robots allow product and category pages; search/filter URLs are never used).

## Material library: `app/furnish/materials/<id>/{color,normal,roughness,thumb}.jpg` + `index.json`
`[{id, name, category wood_floor|tile|carpet|plaster|paint|concrete|brick|metal|fabric|stone|laminate|other, source,
license CC0, url, mean_rgb, clip[], size_m}]`. `matmatch.py <listing_dir> <photo>` -> top-3 per surface.

## Servers
- `app/proxy.py` :8765 static files + `/api/status`, `/api/render` (old queue), `/api/furnish*`, `/api/agent/*`,
  `/api/img?u=` (ikea.com image cache), `/api/model?u=` (ikea.com GLB cache), `/listings/<lid>/<f>`.
- `app/checkout/server.py` :8766 FastAPI: cart, agent checkout (SSE), card-sandbox adapter, x402 merchant endpoint,
  mock facilitator fallback; UI `app/checkout/checkout.html`.

## Spend
`app/spend.py`: every Claude call estimates cost with count_tokens, checks `CAPS`, charges real usage into `spend.json`.
Models: Haiku for cheap steps (room graph of single units, furnishing picks), Sonnet for plan reading/annotation/gallery
room graphs/style pass, Opus reserved for the demo.
