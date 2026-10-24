# Layout JSON contract (plan -> 3D)

File: app/plan3d/layouts/<unit>.json, unit = "<listing id>_<plan stem>" (e.g. gs-20665_plan_00).
Coordinates: metres, x to the right (plan image east), z down the image (plan image south), y up. Origin = top-left of the
unit's bounding box. Image-up is north.

{
 "unit": "gs-20665_plan_00", "listing": "gs-20665", "plan_image": "plans/plan_00.jpg",
 "scale": {"m_per_px": 0.0123, "from": ["door_width", "sqft"], "sqft_listed": 650, "agreement": 0.97},
 "ceiling_m": 2.6,                                   # default 2.6; photos may refine per unit
 "walls":    [{"id": "w0", "a": [x,z], "b": [x,z], "thickness_m": 0.15, "exterior": true}],   # centreline segments, axis-aligned unless the plan is not
 "openings": [{"id": "o0", "wall": "w0", "type": "door|window|opening|closet_door", "s0": 1.2, "s1": 2.1,   # metres along the wall from a
               "swing": "in_left|in_right|out_left|out_right|null", "sill_m": 0.9, "height_m": 1.3, "width_m": 0.9}],   # sill/height: windows (defaults 0.9/1.3), doors 0/2.03
 "rooms":    [{"id": "r0", "name": "Living Room", "type": "living|bedroom|kitchen|bathroom|dining|hallway|closet|office|other",
               "polygon": [[x,z],...] (CCW, interior face of the walls), "area_m2": 20.1, "walls": ["w0","w3",...]}],
 "fixtures": [{"id": "f0", "type": "counter|sink|stove|fridge|dishwasher|tub|shower|toilet|vanity|closet_rod|fireplace|island|washer",
               "rect": {"x": .., "z": .., "w": .., "d": .., "rot_deg": 0}, "room": "r1", "against_wall": "w5"|null, "height_m": 0.9}],
 "materials": {"floor": {"r0": "<material id>", ...}, "wall": {"r0": "<material id>"}, "ceiling": "<id>", "door": "<id>", "cabinet": "<id>", "counter": "<id>", "baseboard": "<id>"},
   # material ids refer to app/furnish/materials/index.json (CC0 PBR library); filled by the matcher, builder falls back to defaults when absent
 "photos":   [{"index": 3, "room": "r0", "facing_walls": ["w0","w1"]}],   # optional, from plan_link
 "review":   {"rounds": 1, "discrepancies_fixed": [...]} 
}

Material library: app/furnish/materials/<id>/ with color.jpg (1K), normal.jpg, roughness.jpg (where available), thumb.jpg,
and app/furnish/materials/index.json = [{"id", "name", "category": "wood_floor|tile|carpet|plaster|paint|concrete|brick|
metal|fabric|stone|glass|laminate", "source": "ambientcg|polyhaven", "license": "CC0", "url", "mean_rgb": [r,g,b], "clip": [..] (optional)}].
