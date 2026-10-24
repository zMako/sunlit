"""Link a building gallery's photos to floor-plan rooms and walls. Input: feasibility/listings/<lid>/ with NN.jpg empty-unit
photos, plans/plan_*.{jpg,png}, meta.json (photo_codes), roomgraph.json (same-room groups). The plans are read with
plan_reader v2 (dimensioned ones only); one Sonnet call sees labelled plan thumbnails, the numbered photos and the room lists,
and says for each photo which plan, which room and which wall(s) it faces. Output feasibility/listings/<lid>/plan_link.json:
  {"plans": {"plan_03.jpg": <v2 plan JSON>, ...},            # only plans actually used by some photo
   "photos": [{"index", "plan", "room", "facing_walls", "primary_wall", "confidence", "evidence", "code", "group"}],
   "rooms":  [{"plan", "room", "type", "photos": [...], "width_m", "depth_m", "dims_source", "walls": {...}, "rect_frac": [x0,y0,x1,y1], "name"}]}
Usage: plan_link.py <listing_dir> [--all-plans] [--model claude-sonnet-5-5]"""
import sys, io, re, json, base64, pathlib, argparse
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import claude_client as cc, spend, plan_reader, vlm_structure

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
  "photos": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
      "index": {"type": "integer"}, "plan": {"type": ["string", "null"]}, "room": {"type": ["string", "null"], "description": "room name exactly as listed for that plan"},
      "facing_walls": {"type": "array", "items": {"type": "string", "enum": ["N", "S", "E", "W"]}, "description": "walls visible in the photo, most prominent first"},
      "primary_wall": {"type": ["string", "null"], "description": "N, S, E or W: the wall the camera mostly faces; null if unknown"},
      "confidence": {"type": "number"}, "evidence": {"type": "string"}}, "required": ["index", "plan", "room", "facing_walls", "primary_wall", "confidence", "evidence"]}},
  "units_seen": {"type": "integer"}, "notes": {"type": "string"}}, "required": ["photos", "units_seen", "notes"]}

SYSTEM = """You match real-estate photos of EMPTY apartments to the building's floor plans. You get: the floor plans of the unit types
(labelled by file name, image-up is NORTH, with a list of their rooms, printed dimensions and which wall carries which window/door/closet),
and the photos (numbered, with the gallery code and a same-room group id from a previous grouping).
For each photo decide: which plan it was taken in, which room of that plan, which walls are visible (N/S/E/W of the plan), and the wall the
camera mostly faces. Evidence: number and position of windows (a corner room with windows on two walls; a window centred vs at one end),
door and closet positions, room proportions, what is visible through doorways (a bathroom beyond a bedroom door), kitchen layout (L vs galley).
Rules: photos in the same group MUST land on the same plan and room; a photo whose unit type has no plan among those given gets plan null;
corridors, closets and bathrooms count as rooms if the plan draws them; if two plans fit equally, pick the one with more rooms matching the
other photos of the same unit and lower the confidence. Use confidence 0..1 honestly."""


VLM_MODEL = "claude-sonnet-5-5"
ORDER = ["N", "E", "S", "W"]   # vlm_structure walks clockwise from the window wall; we call that wall N

def _wall_from_vlm(w, side):
    """vlm_structure opening positions run left->right facing the wall from inside; the contract runs W->E on N/S and N->S on E/W,
    which is the same direction for N and E and reversed for S and W."""
    ops = []
    for o in w.get("openings", []):
        L = max(float(w.get("length_m") or 1.0), 0.5); half = (float(o.get("width_m") or 0.9) / 2) / L
        a, b = o["position_frac"] - half, o["position_frac"] + half
        if side in ("S", "W"): a, b = 1 - b, 1 - a
        kind = {"passage": "opening"}.get(o["kind"], o["kind"])
        ops.append({"kind": kind, "from_frac": round(max(0.0, min(1.0, a)), 3), "to_frac": round(max(0.0, min(1.0, b)), 3), "width_m": o.get("width_m"), "height_m": o.get("height_m"), "sill_m": o.get("sill_m")})
    return {"exterior": bool(w.get("exterior")), "openings": ops, "label": w.get("label")}

def noplan_rooms(d, meta, rg_rooms, lid, model=VLM_MODEL):
    """rooms + photo entries for roomgraph rooms without a plan: walls and size from the VLM reading the photos,
    sizes scaled so the unit's rooms sum to meta sqft_total when present."""
    rooms, photos = [], []
    for k, r in rg_rooms:
        paths = [d / f"{i:02d}.jpg" for i in r["photos"] if (d / f"{i:02d}.jpg").exists()]
        if not paths: continue
        g = vlm_structure.structure(paths, f"{r['type']}: {r['name']}", model=model)
        if not g: continue
        walls = {}; vw = g.get("walls", [])
        for j, side in enumerate(ORDER): walls[side] = _wall_from_vlm(vw[j], side) if j < len(vw) else {"exterior": False, "openings": [], "label": None}
        rooms.append({"plan": None, "room": r["name"], "type": r["type"], "photos": list(r["photos"]), "width_m": float(g["width_m"]), "depth_m": float(g["depth_m"]), "ceiling_m": g.get("ceiling_m"),
                      "dims_source": "vlm", "size_confidence": g.get("size_confidence"), "walls": walls, "rect_frac": None, "name": f"p2_{lid}_{r['type']}_{k}", "roomgraph_index": k,
                      "wall_colour_rgb": g.get("wall_colour_rgb"), "floor_colour_rgb": g.get("floor_colour_rgb"), "floor_material": g.get("floor_material")})
        for n, i in enumerate([int(p.stem) for p in paths]):
            seen = [ORDER[j] for j, w in enumerate(vw[:4]) if n in (w.get("seen_in_photos") or [])]
            primary = "N" if "N" in seen else (seen[0] if seen else None)
            photos.append({"index": i, "plan": None, "room": r["name"], "facing_walls": seen, "primary_wall": primary, "confidence": float(g.get("size_confidence") or 0.5), "evidence": "vlm structure: " + (g.get("notes") or "")[:120]})
    sq = meta.get("sqft_total")
    if sq and len(rooms) >= 3:
        listed = sq * 0.0929; have = sum(rm["width_m"] * rm["depth_m"] for rm in rooms)
        if have > 0:
            s_ = max(0.75, min(1.3, (listed / have) ** 0.5))
            for rm in rooms: rm["width_m"] = round(rm["width_m"] * s_, 2); rm["depth_m"] = round(rm["depth_m"] * s_, 2); rm["dims_source"] = "sqft+vlm"; rm["sqft_scale"] = round(s_, 3)
    return rooms, photos

def thumb(path, max_px):
    im = Image.open(path).convert("RGB"); im.thumbnail((max_px, max_px)); b = io.BytesIO(); im.save(b, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(b.getvalue()).decode()}}

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]

def link(listing_dir, all_plans=False, model="claude-sonnet-5-5"):
    d = pathlib.Path(listing_dir); meta = json.load(open(d / "meta.json")); codes = {c["i"]: c["code"] for c in meta.get("photo_codes", [])}
    groups = {}
    if (d / "roomgraph.json").exists():
        for k, r in enumerate(json.load(open(d / "roomgraph.json"))["rooms"]):
            for i in r["photos"]: groups[i] = k
    photos = sorted(d.glob("[0-9][0-9].jpg"))
    plan_files = sorted(p for p in (d / "plans").glob("plan_*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    plans = {}
    for p in plan_files:
        try: g = plan_reader.read_plan(p, meta.get("sqft_total"))
        except Exception as e: print(f"[link] {p.name}: {type(e).__name__} {e}"); continue
        if all_plans or g.get("has_dimensions"): plans[p.name] = g
    rg = json.load(open(d / "roomgraph.json"))["rooms"] if (d / "roomgraph.json").exists() else []
    if not plans:
        rooms, phs = noplan_rooms(d, meta, list(enumerate(rg)), d.name)
        out = {"listing": d.name, "plans": {}, "photos": sorted(phs, key=lambda x: x["index"]), "rooms": rooms, "units_seen": 1 if meta.get("source") != "greystar" else None, "notes": "no dimensioned plan; walls and sizes from the VLM" + (", scaled to listed sqft" if any(r.get("sqft_scale") for r in rooms) else ""), "_model": VLM_MODEL}
        json.dump(out, open(d / "plan_link.json", "w"), indent=1); _report(out, len(photos), 0); return out
    content = [{"type": "text", "text": f"Building: {meta.get('title')}, {meta.get('address')}. {len(plans)} floor plans follow, then {len(photos)} photos."}]
    for name, g in plans.items():
        rooms = "; ".join(f"{r['name']} ({r['type']}, {r['width_m']}x{r['depth_m']} m, windows on " + (",".join(s for s in 'NSEW' if any(o['kind'] == 'window' for o in r['walls'][s]['openings'])) or "none") + ", doors on " + (",".join(s for s in 'NSEW' if any(o['kind'] == 'door' for o in r['walls'][s]['openings'])) or "none") + ")" for r in g["rooms"])
        content.append({"type": "text", "text": f"PLAN {name}" + (f" ({g.get('unit_label')})" if g.get("unit_label") else "") + f": {rooms}"}); content.append(thumb(d / "plans" / name, 900))
    for p in photos:
        i = int(p.stem); content.append({"type": "text", "text": f"PHOTO {i} (code {codes.get(i, '?')}, group {groups.get(i, '?')}):"}); content.append(thumb(p, 900))
    c = cc.client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, system=SYSTEM, messages=messages).input_tokens; spend.check("anthropic", spend.anthropic_estimate(model, n_in, 6000))
    r = c.messages.create(model=model, max_tokens=6000, system=SYSTEM, messages=messages, output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "high"})
    usd = spend.anthropic_charge(model, r.usage, note=f"plan_link {d.name}")
    txt = next((b.text for b in r.content if b.type == "text"), None)
    if txt is None: raise RuntimeError(f"plan_link: no JSON (stop {r.stop_reason})")
    j = json.loads(txt)
    for ph in j["photos"]: ph["code"] = codes.get(ph["index"]); ph["group"] = groups.get(ph["index"])
    # enforce: same group -> same plan/room (majority, highest confidence wins)
    by_group = {}
    for ph in j["photos"]:
        if ph["group"] is not None and ph["plan"]: by_group.setdefault(ph["group"], []).append(ph)
    for gk, phs in by_group.items():
        best = max(phs, key=lambda x: x["confidence"])
        for ph in phs:
            if (ph["plan"], ph["room"]) != (best["plan"], best["room"]): ph["plan"], ph["room"] = best["plan"], best["room"]; ph["evidence"] += " [aligned to its group]"
    rooms = {}
    for ph in j["photos"]:
        if not ph["plan"] or not ph["room"] or ph["plan"] not in plans: continue
        pr = next((r_ for r_ in plans[ph["plan"]]["rooms"] if r_["name"].lower() == ph["room"].lower()), None) or next((r_ for r_ in plans[ph["plan"]]["rooms"] if ph["room"].lower() in r_["name"].lower() or r_["name"].lower() in ph["room"].lower()), None)
        if pr is None: ph["evidence"] += " [room name not in plan]"; continue
        ph["room"] = pr["name"]; key = (ph["plan"], pr["name"])
        if key not in rooms:
            rooms[key] = {"plan": ph["plan"], "room": pr["name"], "type": pr["type"], "photos": [], "width_m": pr["width_m"], "depth_m": pr["depth_m"], "dims_source": pr.get("dims_source"), "walls": pr["walls"],
                          "rect_frac": [pr["x0_frac"], pr["y0_frac"], pr["x1_frac"], pr["y1_frac"]], "name": f"p2_{d.name}_{pr['type']}_{slug(pathlib.Path(ph['plan']).stem.replace('_', '') + '-' + pr['name'])}"}
        rooms[key]["photos"].append(ph["index"])
    used = {k[0] for k in rooms}; room_list = list(rooms.values()); photo_list = list(j["photos"])
    linked = {i for rm in room_list for i in rm["photos"]}
    leftover = [(k, r) for k, r in enumerate(rg) if any(i not in linked for i in r["photos"])]
    if leftover:   # photos of units whose plan is absent: VLM path for those roomgraph rooms
        extra_rooms, extra_photos = noplan_rooms(d, meta, [(k, dict(r, photos=[i for i in r["photos"] if i not in linked])) for k, r in leftover], d.name)
        room_list += extra_rooms; have = {p["index"]: p for p in extra_photos}
        photo_list = [have.get(p["index"], p) if p["index"] in have else p for p in photo_list]
        for p in photo_list:
            if p["index"] in have: p["code"] = codes.get(p["index"]); p["group"] = groups.get(p["index"])
    out = {"listing": d.name, "plans": {k: v for k, v in plans.items() if k in used}, "photos": sorted(photo_list, key=lambda x: x["index"]), "rooms": room_list, "units_seen": j.get("units_seen"), "notes": j.get("notes"), "_model": model, "_usd": round(usd, 4), "_in_tokens": n_in}
    json.dump(out, open(d / "plan_link.json", "w"), indent=1); _report(out, len(photos), len(plans)); return out

def _report(out, n_photos, n_plans):
    print(f"[link] {out['listing']}: {n_photos} photos, {n_plans} dimensioned plans, {len(out['rooms'])} rooms ({sum(1 for r in out['rooms'] if r['plan'])} from plans), units seen {out.get('units_seen')}, ${out.get('_usd', 0)}")
    for rm in out["rooms"]: print(f"  {rm['name']:58s} {rm['width_m']}x{rm['depth_m']} m [{rm['dims_source']}] photos {rm['photos']} walls " + " ".join(f"{s_}:{''.join(o['kind'][0].upper() for o in rm['walls'][s_]['openings'])}" for s_ in 'NSEW'))
    for ph in out["photos"]: print(f"  photo {ph['index']:2d} {str(ph.get('code')):5s} -> {ph['plan']} / {ph['room']} walls {ph['facing_walls']} primary {ph['primary_wall']} conf {ph['confidence']:.2f} | {ph['evidence'][:90]}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("listing_dir"); ap.add_argument("--all-plans", action="store_true"); ap.add_argument("--model", default="claude-sonnet-5-5")
    a = ap.parse_args(); link(a.listing_dir, a.all_plans, a.model)
