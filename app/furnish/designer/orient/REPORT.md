# Designer GLB orientation (orient.json)

`app/furnish/designer/orient.json` has one entry for each of the 3,268 designer models (`dsg-*`). The GLBs and catalog.json were not changed. Code is in `app/furnish/designer/orient.py`, run in the stages pts, feat, decide, clip, final and sheets. Renders come from `orient/render.html`. Caches are in `orient/cache/`, which is gitignored.

```json
"dsg-...": {"up": "-z", "front_yaw_deg": 270, "method": "up:clip_tiebreak; front:seat_backrest_mass", "confidence": 0.62,
            "up_confidence": 0.7, "front_confidence": 0.62, "flags": [...], "dims_after_m": [w, d, h]}
```

## Rotation maths (apply at load, before the bbox/stretch code in furnish.js)

- `up` names the axis of the current file (models_opt and models have the same frame) that must point to +Y.
- `front_yaw_deg` is a yaw about +Y, applied after the up-fix. It brings the model's front (the sitting side, the foot end of a bed, the door side) to local +Z.

| up | up-fix rotation (single axis, three.js right-handed) |
|---|---|
| y  | identity |
| -y | rotateX(180 deg) |
| z  | rotateX(-90 deg) |
| -z | rotateX(+90 deg) |
| x  | rotateZ(+90 deg) |
| -x | rotateZ(-90 deg) |

```js
const UP_EULER = { y:[0,0,0], '-y':[180,0,0], z:[-90,0,0], '-z':[90,0,0], x:[0,0,90], '-x':[0,0,-90] };   // degrees
const e = UP_EULER[o.up], D = Math.PI / 180;
const qUp = new THREE.Quaternion().setFromEuler(new THREE.Euler(e[0]*D, e[1]*D, e[2]*D));
const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0), o.front_yaw_deg*D).multiply(qUp);  // yaw AFTER up-fix
m.quaternion.premultiply(q);   // or wrap gl.scene in a Group with this quaternion, then run the existing Box3/centre/stretch code
```

This is the same matrix as `R_full(up, yaw) = Ry(yaw) @ R_up(up)` in orient.py, and orient/render.html renders with exactly this quaternion. As a check: front vector -x after the up-fix with yaw 90 gives +z.

Two notes on integration:
- The viewer stretches the model to catalogue (w along x, h along y, d along z). For symmetric items the yaw is chosen so that the long horizontal side lands on x.
- 350 items are flagged `catalog_dims_from_old_bbox`. Their up axis changed, but their catalogue w/d/h were measured from the old, wrongly oriented bbox (`dims_source: glb_bbox`). For these, use `dims_after_m` ([width x, depth z, height y] in metres after the rotation). Otherwise the stretch squashes the corrected model back into the wrong box.

## Method
1. **Geometry (orient.py `decide`).** 24k area-weighted surface samples per model, taken from `models/<id>.glb` (point-cloud-only GLBs fall back to their vertices). The up score for each of the 6 signed axes is:
   - Source prior. y = +1. Then z or -z by the converter history: if `zup` was applied (`models/<id>.json`), a wrongly rotated Y-up source now has its up on -z; if it was not applied, a Z-up source has its up on +z. x and -x get -0.5; -y gets -0.7.
   - Mirror symmetry of a 48^3 occupancy grid. The best mirror axis is the width axis, so it is penalised as up. If the two other axes are both symmetric (round lamps, tables), the remaining axis gets a bonus.
   - Category aspect prior (ASPECT from common.py).
   - Thin base (occupancy of the bottom 10% slice against 40-60%) and a stability test (the centroid lies inside the hull of the bottom 3% slice).
   - Pendant rule: thin cord or canopy at the top, wide shade at the bottom.
   - Rug and mirror thin-axis rules.

   Confidence = 0.35 + 0.5 x (top-1 minus top-2 score). The listed catalogue dims were not used: almost all of them are circular, measured from the GLB itself (`dims_source: glb_bbox` on 2,107 items, and the Moroso/Poliform "listed" dims are "measured from the 3D file"), so they always agree with the current axis.
2. **Front.**
   - Seats (sofa, armchair, chairs, bench, bed, ottoman, bar stool, plus "other" items with a strong signal): the back is the horizontal side holding the mass above 55% of the height (backrest or headboard).
   - Bookcase, dresser, wardrobe, tv_bench, nightstand: the back is the fuller outermost 2% face (a flat panel; handles make the front slab sparse). If the two faces are within 0.08 of each other, the item is flagged `symmetric` with confidence 0.3.
   - Tables, lamps, stools and other symmetric items: flagged `symmetric`, long side on x. Mirrors: thin side is depth.
   - Desks: long side on x, flagged `front_unknown`.
3. **CLIP tie-break (`clip`, `final`).** ViT-B-32 laion2b, loaded as in matmatch.py. Runs on 1,403 items: those with up confidence < 0.7 (the geometric top-2 ups x 4 yaws) or front confidence < 0.7 (4 yaws). That is 8.7k renders at 192 px: grey flat-shaded material, white background, three-quarter camera 35 deg off +z and 18 deg up, rendered with headless Chrome and SwiftShader (needs `--use-angle=swiftshader --use-gl=angle`; plain `--use-gl=swiftshader` loses the WebGL context).
   - Score = cos(render, hero thumb) + 0.5 x cos(render, "a photo of a <category>"). Items without a hero use text only: method `clip_tiebreak_text`.
   - For up, CLIP picks between the geometric top-2 when the gap is > 0.01.
   - For front, CLIP is not allowed to flip a backrest-mass decision. Eyeballing showed those flips were mostly wrong, because grey renders of the front and the back of a sofa look alike to CLIP. When CLIP disagrees it only lowers the confidence (flag `front_clip_disagrees`). The exception is weak backrest signals (thin shell chairs), where CLIP was right on the sheets and is allowed to flip (34 items).

## Counts
- Up: y 2,860 (unchanged), -z 275, z 121, x 8, -y 3, -x 1. **408 models change their up axis.**
- Up method: geometry 2,499; geometry, then CLIP agreed 363; CLIP tie-break with hero 222; CLIP tie-break, text only 57; CLIP undecided, geometry kept 127.
- Front method: symmetric_long_x 1,505; seat_backrest_mass 1,240 (190 with CLIP agreeing, 135 with CLIP disagreeing, so lower confidence); seat_no_backrest_long_x 160; seat_backrest_mass_weak 106 (34 flipped by CLIP); case_flat_back 85; case_symmetric 115; desk 35; mirror 22.
- Overall confidence below 0.5: 509 items.

| brand | n | up != y | up by CLIP | conf >=0.8 | 0.6-0.8 | 0.4-0.6 | <0.4 |
|---|---|---|---|---|---|---|---|
| HAY | 820 | 83 | 35 | 425 | 203 | 87 | 105 |
| Muuto | 728 | 125 | 83 | 361 | 234 | 76 | 57 |
| Moroso | 421 | 38 | 33 | 214 | 132 | 31 | 44 |
| Poliform | 259 | 4 | 6 | 155 | 40 | 8 | 56 |
| Fritz Hansen | 257 | 35 | 38 | 111 | 85 | 38 | 23 |
| Artemide | 212 | 59 | 43 | 156 | 39 | 13 | 4 |
| Carl Hansen & Son | 128 | 12 | 5 | 75 | 25 | 8 | 20 |
| Hem | 119 | 10 | 12 | 64 | 29 | 7 | 19 |
| Louis Poulsen | 111 | 0 | 0 | 110 | 1 | 0 | 0 |
| GUBI | 73 | 13 | 8 | 52 | 10 | 5 | 6 |
| String | 65 | 22 | 10 | 35 | 13 | 14 | 3 |
| Artek | 40 | 4 | 3 | 25 | 5 | 3 | 7 |
| Tom Dixon | 28 | 3 | 3 | 24 | 2 | 1 | 1 |
| Flos | 7 | 0 | 0 | 7 | 0 | 0 | 0 |

Flags:

| flag | items |
|---|---|
| symmetric | 1,642 |
| no_hero_photo | 820 |
| catalog_dims_from_old_bbox | 350 |
| category_other | 185 |
| front_clip_disagrees | 176 |
| no_backrest_signal | 160 |
| weak_backrest_signal | 106 |
| points_only_model | 54 (faces lost in conversion, so these render as nothing) |
| front_unknown | 35 |
| mirror_face_unknown | 22 |

## Contact sheets (`orient/sheets/`)
Each cell shows the hero photo, then the current file rendered as is (before), then the render with orient.json applied (after). The camera looks at the +z front from the right.

| sheets | contents |
|---|---|
| `random_01..04.png` | 40 random items (seed 7) |
| `up_changed_01..02.png` | 20 random items whose up changed |
| `front_clip_flip_01..02.png` | 20 random items where CLIP flipped a weak front |

## Eyeballed accuracy (honest)
**40 random items (random_01..04):**
- 33 are right in up and front.
- 4 are certainly wrong:
  - 2 HAY tables (cph-deux-210, boa-table) are still lying on their side. CLIP agreed with the wrong up.
  - 1 sofa module (hay-mags-soft-modules) faces away.
  - 1 coat rack (muuto-coil) has an ambiguous up.
- 2 are doubtful: fritz-hansen-taburet-cm210 (possibly upside down) and moroso-arco-ar2091 (the render does not resemble the photo).
- 2 have broken source models, where orientation is moot (muuto-connect-corner renders empty; muuto-linear-steel-chair is a single panel).
- **Estimated error rate: about 10-15% of items still wrong in up or front.** The 95% interval is wide, roughly 5-25%. Before this work, about 17% of the same 40 were wrong in up alone (6-7 of 40); fronts were never set.

**Changed-up sample (up_changed, 20 items):** about 17 of 20 are clearly improved, for example lamps hanging cord-up, chairs and sofas no longer lying on their back, trestle tables upright. The regressions:
- moroso-shanghai-tip side table was correct and is now on its side.
- 2 items are unclear: muuto-in-situ corner and moroso-serpentine.

**Front sample:**
- Backrest-mass fronts on clearly shaped seats were right in every case I looked at (Carl Hansen, Fritz Hansen and Muuto sofas and chairs).
- Weak-signal seats with a CLIP flip: 8 of the 10 chairs are now right. hay-aac-50 is wrong (back to camera), and moroso-gentry-pouf is on its side.

## Unresolved / known limitations
- **Tables lying on their side** (HAY cph-deux, boa) are not caught. A rule such as "tables: up = the normal of the largest flat horizontal slab" would fix most of them but is not implemented.
- **Front is unknown** for desks (35), symmetric cases (115) and seats with no backrest signal (160, mostly poufs and stools, where it is irrelevant).
- **54 point-cloud-only GLBs** have no faces, so their orientation is a guess. They need re-conversion.
- **820 items have no hero photo**, so their CLIP decisions use text only and are weaker.
- **Wrong categories** (for example "floor_lamp" on muuto-connect-soft sofa modules) weaken the category priors.
- **One CLIP view per run.** The CLIP up decision uses one three-quarter view per yaw. A side-view tie-break, or a stronger model, would help the remaining low-confidence items. Re-run with `orient.py decide && orient.py clip && orient.py final && orient.py sheets`, with a static server rooted at app/ on `ORIENT_BASE` (default http://127.0.0.1:8798; proxy.py on 8765 works too).
