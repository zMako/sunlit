# Walk mode physics (`app/plan3d/walk.js`)

Loaded by `apartment.html` after `build.js`/`agent.js`. Active whenever the "walk" button is on; dollhouse mode is untouched.

## What it does
- **Player**: disc radius 0.30 m, eye 1.60 m, velocity with acceleration/friction (1.7 m/s, Shift 3.2 m/s), gentle head bob
  while moving, a short downward nudge + click (WebAudio oscillator, no asset) when you bump into something.
- **Collisions**: every wall of the layout as an oriented box (centreline + thickness), closed doors and all windows as
  blockers across their span, open doors carve a passable gap out of any wall collider they overlap (layouts may either
  run the wall through the opening or leave it gapped), the open leaf itself blocks, furniture footprints from every
  per-room `Furnish` instance (rotated, rugs excluded) and layout fixtures (counters, tub...) block. Per-axis sweep
  (x then z) with a 3-pass push-out, so you slide along walls. A soft bound keeps you within the unit box + 2.5 m
  (balconies are outside the walls).
- **Doors**: start closed; within 1.2 m and facing one the HUD shows `E · open the door` (or closet); `E` or a click
  toggles; the builder's leaf pivot (`userData.kind === 'door'`) is driven with an eased 0.5 s swing on its hinge, in the
  layout's swing direction; cased openings are always free.
- **HUD**: crosshair (builder's), bottom line with the current room (point-in-polygon on `layout.rooms`) and the action.

## API (`window.walk`)
`player` (pos Vector2 x,z · vel · room · prompt), `doors` (Map id -> state), `toggleDoor(id)`, `nearestDoor()`,
`doorList()`, `roomAt(x,z)`, `teleport(x,z)`, `look(yawDeg)`, `lookAt(x,z)`, `setEnabled(bool)`, `manual` (when true the
loop does not move the player), `step(dt, keys)` (one physics step with `{KeyW, KeyA, KeyS, KeyD, ShiftLeft}`),
`colliders()`, `near(x,z,r)` (debug: colliders near a point).

## Verified headless (gs-22612_plan_03, SwiftShader, `q=low`)
- Closed balcony door o6: walking straight at it stops at 0.43 m from the wall centreline (0.13 half wall + 0.30 radius).
- After `toggleDoor`: the player passes through and continues outside until the soft bound 2.5 m past the wall.
- From the living-room centre, 8 directions at run speed: never leaves the living room; stops 0.56 m from each wall.
- Walking into a 1.8 m loveseat stops at its edge (1.58 m from its centre with the 0.3 m radius).
Test scripts: `scratchpad/walk_shots.py`, `walk_test2.py` (session scratchpad). Screenshots: `test_walk_door_closed.png`,
`test_walk_door_open.png`.

## Known limits
- Collisions are 2D footprints at any height: you cannot duck under a table or step onto a rug's edge differently.
- Door leaves are driven only when the builder's pivot exists; layouts whose openings fall outside their wall's extent
  (the plan engine sometimes emits that) still block correctly because the blocker uses the opening's own span.
- The HUD room name uses the layout polygons; where the plan engine's polygons overlap, the first match wins.
- The headless renderer loses its WebGL context under load from parallel screenshot jobs; the test scripts retry the load.
