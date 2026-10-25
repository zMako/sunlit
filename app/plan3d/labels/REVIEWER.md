# Floor-plan prediction review (instructions for the reviewing agent)

You are reviewing an automatic floor-plan wall detector so its mistakes can be turned into training labels. A program snaps
every flag you give to the drawn lines at pixel precision, so your job is to say WHAT is wrong and roughly WHERE; you do not
need pixel accuracy.

What each image shows: a floor plan, lightened, with the detector's prediction painted on top.
- RED = predicted wall. BLUE = predicted window. GREEN = predicted door (the opening in the wall line).
- Anything drawn on the plan that is NOT painted is something the detector did not mark (it stays grey/black).
- A blue grid gives coordinates in PERCENT of the image: x from 0 (left) to 100 (right), y from 0 (top) to 100 (bottom).
  Grid lines every 5%, numbered every 10% on all four edges.

Check every room boundary (rooms, closets, baths, halls, the exterior outline) and flag only clear errors:
- missing_walls: a wall drawn in the plan (solid, heavy, grey, or drawn as two parallel lines; includes thin walls around
  closets and baths) that is not painted red, or only partly painted. Give a straight segment [x0, y0, x1, y1] along the
  wall's centre line covering the unpainted part. Split L-shapes into separate straight segments.
- extra_walls: red paint on something that is not a wall: counters, cabinets, appliances, furniture, tubs, text, floor
  texture, door swing lines, balcony railings. Box [x0, y0, x1, y1] (top-left, bottom-right) around the wrong paint.
- missing_windows: a window in a wall (usually thin parallel lines across a gap in an exterior wall, or a glazed panel) that
  is not painted blue. Segment along the wall over the window's length.
- extra_windows: blue on something that is not a window (an interior wall, a door, a counter). Box.
- missing_doors: a doorway (a gap in a wall with a swing arc, sliding or bifold doors, including closet and entry doors)
  whose opening in the wall line is not painted green. Segment along the wall line across the opening, jamb to jamb.
- extra_doors: green where there is no doorway. Box.
- exclude: anything painted that is not part of the apartment drawing (title, logo, legend, key plan, compass, notes). Box.
- usable: false only if the image is not a 2D floor plan (a photo, a 3D rendering, a blank page) or is too unclear to judge.

Rules:
- Do NOT flag as walls: furniture, appliances, counters, cabinets, fixtures, door swing arcs, dashed lines (shelves,
  overhead cabinets), text, dimension lines, balcony railings.
- Small misalignments of the paint (a few pixels too thick or offset) are not errors. Flag missing or wrong things, not
  imperfect edges.
- Coordinates within about 1-2% are fine. When two walls are close together, make sure the segment is on the intended one.
- Prefer completeness for missing walls (look at every closet, bath and hallway), and be conservative with extra_* (only
  clear mistakes).

For each image write a JSON file next to it with the same name and a .json extension (for example
.../review/gs-22612_plan_05.json), using the Write tool, with exactly these keys:
{"usable": true, "missing_walls": [], "extra_walls": [], "missing_windows": [], "extra_windows": [], "missing_doors": [],
 "extra_doors": [], "exclude": [], "notes": "one short sentence"}
Each list holds [x0, y0, x1, y1] number arrays in percent. Empty lists when nothing is wrong. If a .json for an image
already exists, skip that image.

Do not modify any other files.
