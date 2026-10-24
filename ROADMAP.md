# Roadmap set by the user on Oct 24 ~12:45 (user napping until ~17:15; work autonomously in this order)

Budget: Anthropic $10, Google Maps $5 (app/spend.py CAPS). Google Maps "out of the window" is the LAST step and is NOT to be
implemented while the user sleeps.

1. **Plan detection works for all plan styles.** Every building draws plans differently (SightMap schematic, architect
   marketing sheets, 777 Tenn style...). Run the engine over every plan image we have (feasibility/listings/*/plans), fix
   failure modes until walls/doors/windows/rooms come out right across styles. Geometry-only sweeps are free; VLM
   annotation only for units we show.
2. **Reliable three.js scenes from every layout** (no photo comparison yet): batch build + headless screenshots, fix crashes
   and visual breakage.
3. **Download ALL CC0 textures** (ambientCG full library, Poly Haven textures) so matching has the closest possible material.
4. **Photos -> data points**: window height/structure, exact door locations, textures of wall/ceiling/doors/floor/windows,
   per photo, linked to plan rooms (plan_link.json). Store per listing (photo_facts.json).
5. **Apply materials coherently** to the three.js model: plank direction along the room, consistent palette per unit,
   everything coherent, as close to real as possible.
6. **Shaders and lighting**: sun through windows, shadows, ambient occlusion, exposure/tone mapping. Goal: photoreal-feeling
   renders even if not identical to the photo. Verify by screenshots + adversarial review loop.
7. **Furniture**: download as many IKEA (and Amazon, if feasible without bot walls) models as possible, locally, with
   prices, descriptions, links. AI agent plans a room with those items (coherent style, right placement, within a USER
   BUDGET). Top-view animation (ceiling off) of items streaming in as the agent places them; a "rejection" animation
   when e.g. a sofa cannot pass the door. Movable objects with an easy UI (exists); chat with the agent to change the
   design live. Camera-preset renders (optional SD polish only if cheap).
8. **Partner tracks** (13.0 Hacker Guide.pdf): Visa and Coinbase tracks -> agentic checkout for the chosen items;
   budget input; checkout screen; order for a move-in date; sandbox-connected so it is demoable. Include any other track
   that fits. Anything needing the user's accounts/keys/calls: prepare everything, list it in HOLD.md, do not block.
9. Last and not now: Google Maps / Street View out of the windows.

Reporting: keep README.md status sections updated; put decisions needing the user in HOLD.md.
