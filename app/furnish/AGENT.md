# Furnishing agent (app/furnish/agent.py + agent.js)

**Backend** `agent.py furnish <room> --budget N --style "..." [--drama]` streams one JSON event per line:
`start` → `shortlist` (palette/wood/accent/notes) → per slot: `consider` → `place` (item with x,z,rot_deg, why, spent) or
`reject` (reason: over budget / cannot pass the N m door / no wall position fits / blocks the walking path / no room next
to its anchor) → `skip` when both picks fail → `summary` (total, saved vs budget, palette). Haiku picks 2 ranked products
per slot from a size-filtered, price-spread catalogue sample (~$0.002 per room); placement is deterministic (place.py,
earlier items pinned as obstacles, fixtures and door swings respected). `--drama`: the main slot first tries the
bulkiest/priciest real product so the audience sees a genuine rejection. Rugs/textiles skip the door check (they roll).
`agent.py chat <room>` with stdin `{message, plan, budget, style}` → Haiku turns the request into ops (move/rotate/remove/
swap/add/set_budget/set_style), applies them, re-validates with the solver, saves the plan, returns `{reply, ops, plan}`.

**Endpoints (proxy.py)** `GET /api/agent/furnish?room=<unit>__<rid>&budget=&style=[&drama=1]` → text/event-stream;
`POST /api/agent/chat` JSON → JSON. Plans persist in app/furnish/plans/<room>.json as before.

**Frontend** agent.js (loaded by apartment.html): "Design with AI" panel (budget, style, Furnish this room / Whole
apartment / Stop), top-down camera over the room, items drop in from the door one by one (0.65 s), rejected items flash
red at the door with a toast and fly out, running budget bar, summary card, chat box (diff-animated moves/adds/removals),
camera presets (overview / from door / window corner / sofa view), Render 2× (PNG download).
URL params for demos: `?agent=<rid>&budget=3500&style=...&drama=1&nolock=1` auto-starts.
Furnish instances are exposed as `window.furnishByRoom[<unit>__<rid>]` (furnish.js) with `setPlan(plan)` and `itemById(id)`.
