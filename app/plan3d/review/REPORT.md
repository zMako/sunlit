# Render quality report (render worker, Oct 24 ~16:10)

Final screenshots: `<unit>_<view>.png` for gs-22612_plan_03, gs-20665_plan_00, gs-22612_plan_01, gs-18149_plan_00 (dollhouse
+ 3 walk views each) and `gs-22612_plan_03_doll_quality-low.png`; iterations in `before/`, `r1..r6`; Sonnet critiques in
`critique_r3.txt`, `critique_r6.txt` ($0.06 of the $1 allowance).

## Done
- Materials: per-category tile size/roughness, anisotropy 16; planks along the photo direction (else the room's long
  axis) with per-room UV phase; per-wall UV phase with continuous U across openings (no seams); walls = photo-matched id
  + desaturated tint (chroma <= 0.08, lightness >= 0.9, listing photos are tungsten-lit); paint/plaster entries rendered
  as flat paint from the swatch tone; ceilings white; one trim colour per unit.
- Geometry: windows with reveal lining, 55 mm sash, 35 mm mullions, transom on tall windows, projecting stool + apron,
  room-side architrave; doors with architraves both faces, panelled leaf, knobs, 9 deg ajar; cabinet seams/drawer line,
  fridge handles; flush ceiling fixture per room; walls overshoot the ceiling 3 cm (no sky leak); dollhouse section by
  scaling wall pieces (solid caps) instead of clipping.
- Lighting: sun through the exterior wall with the most window width (38 deg elevation, 22 deg off-axis), fitted shadow
  camera, 4096 PCFSoft; neutral RoomEnvironment PMREM 0.62 + hemisphere 0.45; ACES, exposure 1.05 walk / 0.92 dollhouse;
  GTAO (r 0.35, blend 0.7) + light bloom + OutputPass; transmission glass; furniture labels occluded in walk view.
- Plumbing: vendored import map (/vendor/three), `?quality=low` (no post, plain glass, 1024 shadows, pixelRatio 1), WebGL
  context-loss handler, index_slim.json first, agent.js/walk.js include lines preserved, photo facts consumed
  (window_specs sill/head per room, floor_direction, wall/trim tints, per-room door material, cabinet/counter ids).
  HDRIs opt-in via `?env=studio|sky|photostudio` (they tint white walls).

## Not done / known fakes
- Exterior behind glass is a sky shader + ground disc (no horizon/buildings); trim profiles are boxes; appliances, toilet
  and tub are primitives; flat ceilings; floor saturation not normalised across rooms; coloured accent walls lost by the
  tint desaturation; some layouts show sky through walls the plan engine left open (plan-engine issue); 60 fps on the
  M4 not measured headless.
