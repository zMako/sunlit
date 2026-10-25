"""Furnishing agent: shops a room within a budget and a style, places items one by one (streaming JSON events), rejects
what cannot pass the door / fit / afford, and edits a plan from chat.

    agent.py furnish <room> --budget 3500 --style "warm scandinavian"      # one JSON event per stdout line
    agent.py chat <room>   (stdin JSON {"message": str, "plan": {...}, "budget": N, "style": str}) -> JSON {"reply", "plan", "ops"}

Events: {"event":"start"} {"event":"shortlist",...} {"event":"consider",item} {"event":"place",item,x,z,rot_deg,why}
        {"event":"reject",item,reason} {"event":"skip",slot,reason} {"event":"summary",total_usd,budget,saved_usd,palette,notes,walkable}
Room JSON: app/rooms/<room>.json (polygon, edges, doors, windows, fixtures, type). Catalogue: app/furnish/catalog.json (read fresh)."""
import sys, re, json, math, pathlib, argparse, time
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import place

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
SLOTS = {"living": ["sofa", "coffee_table", "tv_bench", "rug", "bookcase", "floor_lamp", "armchair", "side_table"],
         "bedroom": ["bed", "nightstand", "nightstand", "dresser", "rug", "floor_lamp", "mirror"],
         "dining": ["dining_table", "dining_chair", "dining_chair", "dining_chair", "dining_chair", "sideboard", "floor_lamp"],
         "kitchen": ["dining_table", "dining_chair", "dining_chair", "bar_stool", "bar_stool"],
         "office": ["desk", "desk_chair", "bookcase", "floor_lamp", "armchair"], "other": ["sofa", "coffee_table", "rug", "floor_lamp"]}
DOOR_W_DEFAULT, DOOR_H = 0.86, 2.03

def emit(ev, **kw):
    kw["event"] = ev; kw["t"] = round(time.time(), 3); sys.stdout.write(json.dumps(kw) + "\n"); sys.stdout.flush()

def load_room(room):
    return place.normalize(json.load(open(ROOT / "rooms" / f"{room}.json")))

def room_info(R):
    xs = [p[0] for p in R["polygon"]]; zs = [p[1] for p in R["polygon"]]; lens = sorted((e["len"] for e in R.get("edges", [])), reverse=True)
    doors = [d for d in R.get("doors", []) if 0.55 <= d.get("width_m", 0) <= 1.5]
    return {"type": R.get("type") or "other", "area_m2": R.get("area_m2"), "long_m": round(max(max(xs) - min(xs), max(zs) - min(zs)), 2), "short_m": round(min(max(xs) - min(xs), max(zs) - min(zs)), 2),   # bounding box: notched polygons have tiny edges
            "ceiling_m": R.get("ceiling_m") or 2.6, "n_windows": len(R.get("windows", [])), "n_doors": len(doors), "door_w": round(max((d["width_m"] for d in doors if d.get("width_m", 0) >= 0.7), default=DOOR_W_DEFAULT), 2),   # the door you carry furniture through: the widest real door (closet doors are narrower)
            "fixtures": [f.get("type") for f in R.get("fixtures", []) or []]}

def catalog():
    c = json.load(open(HERE / "catalog.json")); by = {}
    for i in c["items"]:
        if i.get("width_m") and i.get("depth_m") and i.get("height_m"): by.setdefault(i["category"], []).append(i)
    for k, v in by.items():   # prefer products with a real 3D model; model-less ones only where the category has no modelled product
        with_model = [i for i in v if i.get("model_glb")]
        if with_model: by[k] = with_model
    return by

def fits_room(i, info):
    return min(i["width_m"], i["depth_m"]) <= info["short_m"] - 0.5 and max(i["width_m"], i["depth_m"]) <= info["long_m"] - 0.3

def passes_door(i, door_w):
    """The item's two smallest dimensions must fit the door opening (width, height); the third goes through lengthwise."""
    a, b, c = sorted([i["width_m"], i["depth_m"], i["height_m"]])
    return a <= door_w + 0.02 and b <= DOOR_H

def to_item(c, k, why=None):
    return {"id": c["id"] + (f"#{k}" if k else ""), "name": c["name"], "category": c["category"], "w_m": c["width_m"], "d_m": c["depth_m"], "h_m": c["height_m"],
            "price_usd": c.get("price_usd"), "product_url": c.get("product_url"), "image": c.get("image"), "model_glb_url": c.get("model_glb_url"), "model_glb": c.get("model_glb"), "why": why,
            "color": c.get("color"), "style_tags": c.get("style_tags")}

def claude_json(system, text, schema, model, max_tokens, note):
    import claude_client as cc, spend as sp
    c = cc.client(); messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    n_in = c.messages.count_tokens(model=model, system=system, messages=messages).input_tokens; sp.check("anthropic", sp.anthropic_estimate(model, n_in, max_tokens))
    r = c.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages, output_config={"format": {"type": "json_schema", "schema": schema}, "effort": "medium"})
    usd = sp.anthropic_charge(model, r.usage, note=note); out = "".join(b.text for b in r.content if b.type == "text")
    if r.stop_reason == "max_tokens": raise RuntimeError(f"{note}: output truncated at {max_tokens} tokens")
    m = re.search(r"\{.*\}", out, re.S)
    return (json.loads(m.group(0)) if m else {}), usd

SHORTLIST_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "palette": {"type": "string"}, "wood": {"type": "string"}, "accent": {"type": "string"}, "notes": {"type": "string"},
    "slots": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"slot": {"type": "string"}, "category": {"type": "string"},
        "picks": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "string"}, "why": {"type": "string"}}, "required": ["id", "why"]}}}, "required": ["slot", "category", "picks"]}}},
    "required": ["palette", "wood", "accent", "notes", "slots"]}

def shortlist(info, budget, style, by, wanted, hint=""):
    cands = []
    for cat in dict.fromkeys(wanted):
        opts = [i for i in by.get(cat, []) if fits_room(i, info) and i.get("price_usd") and (budget is None or i["price_usd"] <= budget)]
        opts.sort(key=lambda i: i["price_usd"]); step = max(1, len(opts) // 14)
        for i in opts[::step][:14]:
            cands.append({"id": i["id"], "cat": cat, "name": i["name"][:70], "w": i["width_m"], "d": i["depth_m"], "h": i["height_m"], "usd": i["price_usd"], "color": i.get("color"), "tags": i.get("style_tags"), "desc": (i.get("description") or "")[:120]})
    system = ("You are a senior interior designer furnishing an EMPTY rental room with real catalogue products. Fill the requested slots within the TOTAL budget "
              "(sum of your first picks must be <= budget; leave 5-10% slack), in ONE coherent style: one wood tone, one accent colour, matching textiles. "
              "For each slot give 2 picks ranked: the ideal piece first, a safer/cheaper alternative second (different id). Repeated slots (two nightstands, four chairs) use the same product. "
              "Skip a slot (empty picks) if nothing suits. Keep every 'why' under 12 words. Reply JSON only.")
    text = f"Room: {json.dumps(info)}. {hint}\nBudget USD: {budget or 'none'}. Style brief: {style or 'calm, modern, light'}.\nSlots: {wanted}\nCatalogue:\n" + "\n".join(json.dumps(c) for c in cands)
    j, usd = claude_json(system, text, SHORTLIST_SCHEMA, HAIKU, 6000, f"agent shortlist {info['type']}")
    return j, usd, {c["id"]: c for cat in by.values() for c in cat}

def run_furnish(room, budget, style, drama=False):
    R = load_room(room); info = room_info(R); by = catalog(); wanted = [s for s in SLOTS.get(info["type"], SLOTS["other"]) if s in by]
    emit("start", room=room, type=info["type"], budget=budget, style=style, slots=wanted, door_w=info["door_w"])
    sl, usd, by_id = shortlist(info, budget, style, by, wanted)
    if drama and sl.get("slots"):   # demo mode: the agent first reaches for the showpiece of the main slot (the bulkiest or priciest real product);
        # the real door / fit / budget checks then decide, so the rejection the audience sees is genuine
        main = sl["slots"][0]; cat = main.get("category") or wanted[0]; opts = list(by.get(cat, []))
        doorfail = [c for c in opts if not passes_door(c, info["door_w"])]; pricey = [c for c in opts if budget and (c.get("price_usd") or 0) > budget]
        bulky = (max(doorfail, key=lambda c: c.get("price_usd") or 0) if doorfail else max(pricey, key=lambda c: c.get("price_usd") or 0) if pricey
                 else max(opts, key=lambda c: (sorted([c["width_m"], c["depth_m"], c["height_m"]])[0], c.get("price_usd") or 0), default=None))
        if bulky and all(p.get("id") != bulky["id"] for p in main.get("picks", [])): main["picks"] = [{"id": bulky["id"], "why": "the statement piece for this room"}] + main.get("picks", [])
    emit("shortlist", palette=sl.get("palette"), wood=sl.get("wood"), accent=sl.get("accent"), notes=sl.get("notes"), n_slots=len(sl.get("slots", [])), usd=round(usd, 4))
    placed = []; spent = 0.0; k = 0; log = []
    for slot in sl.get("slots", []):
        picks = [p for p in slot.get("picks", []) if p.get("id") in by_id]
        if not picks: emit("skip", slot=slot.get("slot"), reason="nothing in the catalogue suits this slot"); continue
        done = False
        for p in picks:
            if any(x["category"] == (slot.get("category") or "") for x in placed) and p is not picks[0]: break   # repeated slot: one try is enough
            c = by_id[p["id"]]; k += 1; it = to_item(c, k, p.get("why")); it["slot"] = slot.get("slot")
            emit("consider", item=it)
            price = c.get("price_usd") or 0
            if budget and spent + price > budget:
                emit("reject", item=it, reason=f"over budget by ${spent + price - budget:.0f} (spent ${spent:.0f} of ${budget:.0f})"); continue
            if c["category"] not in ("rug", "curtain", "mattress") and not passes_door(c, info["door_w"]):   # textiles roll up
                a, b, _ = sorted([c["width_m"], c["depth_m"], c["height_m"]])
                emit("reject", item=it, reason=f"{c['name'].split(' - ')[0]} is {a:.2f} m thick and {b:.2f} m tall at its smallest; it cannot pass the {info['door_w']:.2f} m door"); continue
            pinned = [dict(x, pinned=True) for x in placed]
            res, walk = place.place(R, pinned + [dict(it)])
            new = next((r for r in res if r["id"] == it["id"]), None)
            if new is None or new.get("x") is None:
                emit("reject", item=it, reason=(new or {}).get("unplaced") or "no position fits"); continue
            if not walk:
                emit("reject", item=it, reason="blocks the walking path from the door"); continue
            rec = {kk: v for kk, v in new.items() if kk not in ("pinned", "unplaced")}; placed.append(rec); spent += price
            emit("place", item=rec, x=rec["x"], z=rec["z"], rot_deg=rec["rot_deg"], why=p.get("why"), spent=round(spent, 2)); done = True; break
        repeated = any(x["category"] == (slot.get("category") or "") for x in placed)   # a 3rd/4th chair that found no spot: do not churn through the catalogue
        if not done and not repeated:   # last resort for the slot: the cheapest in-budget product of the category that fits the room and the door
            cat = slot.get("category") or ""; tried = {p["id"] for p in picks}; remaining = (budget - spent) if budget else None
            fb = sorted([c for c in by.get(cat, []) if c["id"] not in tried and fits_room(c, info) and (remaining is None or (c.get("price_usd") or 0) <= remaining) and (cat in ("rug",) or passes_door(c, info["door_w"]))], key=lambda c: c.get("price_usd") or 0)
            for c in fb[:2]:
                k += 1; it = to_item(c, k, "practical fallback that fits"); it["slot"] = slot.get("slot"); emit("consider", item=it)
                res, walk = place.place(R, [dict(x, pinned=True) for x in placed] + [dict(it)]); new = next((r for r in res if r["id"] == it["id"]), None)
                if new is None or new.get("x") is None or not walk: emit("reject", item=it, reason=(new or {}).get("unplaced") or "blocks the walking path from the door"); continue
                rec = {kk: v for kk, v in new.items() if kk not in ("pinned", "unplaced")}; placed.append(rec); spent += c.get("price_usd") or 0
                emit("place", item=rec, x=rec["x"], z=rec["z"], rot_deg=rec["rot_deg"], why="practical fallback that fits", spent=round(spent, 2)); done = True; break
        if not done: emit("skip", slot=slot.get("slot"), reason="no free spot left for another one" if repeated else "no candidate could be placed")
    plan = {"room": room, "room_type": info["type"], "items": placed, "total_usd": round(spent, 2), "budget": budget, "style": style, "palette": sl.get("palette"), "notes": sl.get("notes"), "walkable": True, "picker": f"agent haiku ${usd:.4f}"}
    (HERE / "plans").mkdir(exist_ok=True); json.dump(plan, open(HERE / "plans" / f"{room}.json", "w"), indent=1)
    emit("summary", total_usd=round(spent, 2), budget=budget, saved_usd=round((budget or spent) - spent, 2), n_items=len(placed), palette=sl.get("palette"), wood=sl.get("wood"), accent=sl.get("accent"), notes=sl.get("notes"), usd=round(usd, 4))

CHAT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "reply": {"type": "string"},
    "ops": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "op": {"type": "string", "enum": ["move", "rotate", "remove", "swap", "add", "set_budget", "set_style", "none"]},
        "id": {"type": "string", "description": "item id for move/rotate/remove/swap, else empty"},
        "x": {"type": "number"}, "z": {"type": "number"}, "rot_deg": {"type": "number"},
        "category": {"type": "string", "description": "for add/swap: catalogue category"}, "query": {"type": "string", "description": "for add/swap: what to look for (colour, size, price, style)"},
        "budget": {"type": "number"}, "style": {"type": "string"}}, "required": ["op", "id", "x", "z", "rot_deg", "category", "query", "budget", "style"]}}},
    "required": ["reply", "ops"]}

def run_chat(room, message, plan, budget, style):
    R = load_room(room); info = room_info(R); by = catalog(); by_id = {c["id"]: c for cat in by.values() for c in cat}
    items = plan.get("items", [])
    summary = [{"id": i["id"], "name": i["name"][:50], "cat": i["category"], "x": i.get("x"), "z": i.get("z"), "rot": i.get("rot_deg"), "usd": i.get("price_usd"), "w": i["w_m"], "d": i["d_m"]} for i in items]
    walls = [{"i": k, "a": e["a"], "b": e["b"]} for k, e in enumerate(R.get("edges", []))]
    system = ("You edit a furniture plan for one room from a user's chat message. Room coordinates are metres, x right, z down on the plan; items have centre x,z and rot_deg. "
              "Translate the request into operations: move (give new x,z), rotate (rot_deg), remove, swap (same slot, different product: give category and a query), add (category + query), "
              "set_budget, set_style. Keep items inside the room polygon and off the door swings; 'by the window' means against a wall that has a window. Reply in one friendly sentence. JSON only.")
    text = f"Room: {json.dumps(info)}\nPolygon: {R['polygon']}\nWalls: {walls}\nWindows (edge index, s0-s1 m): {[(w['edge'], w['s0'], w['s1']) for w in R.get('windows', [])]}\nDoors: {[(d['edge'], d['s0'], d['s1']) for d in R.get('doors', [])]}\n" \
           f"Current items: {json.dumps(summary)}\nBudget: {budget} spent: {plan.get('total_usd')} Style: {style}\nUser: {message}"
    j, usd = claude_json(system, text, CHAT_SCHEMA, HAIKU, 3000, "agent chat")
    ops = j.get("ops", []); notes = []
    for op in ops:
        kind = op.get("op")
        if kind == "remove": items = [i for i in items if i["id"] != op["id"]]
        elif kind in ("move", "rotate"):
            for i in items:
                if i["id"] == op["id"]:
                    if kind == "move": i["x"], i["z"] = op["x"], op["z"]
                    else: i["rot_deg"] = op["rot_deg"] % 360
        elif kind in ("add", "swap"):
            cat = op.get("category") or ""; q = (op.get("query") or "").lower(); opts = [c for c in by.get(cat, []) if fits_room(c, info)]
            if not opts: notes.append(f"no {cat} fits this room"); continue
            def score(c):
                txt = f"{c.get('name', '')} {c.get('color', '')} {c.get('description', '')} {' '.join(c.get('style_tags') or [])}".lower(); s = sum(1 for w in q.split() if len(w) > 2 and w in txt)
                m = re.search(r"under \$?(\d+)", q); s -= 5 if m and (c.get("price_usd") or 0) > float(m.group(1)) else 0; return s
            opts.sort(key=lambda c: (-score(c), c.get("price_usd") or 0)); c = opts[0]
            old = next((i for i in items if i["id"] == op.get("id")), None) if kind == "swap" else None
            new = to_item(c, len(items) + 1, f"chat: {message[:60]}")
            if old is not None: new.update({"x": old.get("x"), "z": old.get("z"), "rot_deg": old.get("rot_deg")}); items = [new if i is old else i for i in items]
            else: items.append(new)
        elif kind == "set_budget": budget = op.get("budget") or budget
        elif kind == "set_style": style = op.get("style") or style
    # re-validate: pinned everything that has a position, let the solver place anything without one or whose spot is now invalid
    pinned = [dict(i, pinned=True) if i.get("x") is not None else dict(i) for i in items]
    res, walk = place.place(R, pinned)
    out = [{k: v for k, v in r.items() if k not in ("pinned",)} for r in res]
    total = round(sum((i.get("price_usd") or 0) for i in out if i.get("x") is not None), 2)
    plan = dict(plan, room=room, items=out, total_usd=total, budget=budget, style=style, walkable=walk, picker=(plan.get("picker") or "") + f"; chat ${usd:.4f}")
    json.dump(plan, open(HERE / "plans" / f"{room}.json", "w"), indent=1)
    return {"reply": j.get("reply", "Done."), "ops": ops, "notes": notes, "plan": plan, "usd": round(usd, 4)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["furnish", "chat"]); ap.add_argument("room"); ap.add_argument("--budget", type=float); ap.add_argument("--style", default=""); ap.add_argument("--drama", action="store_true")
    a = ap.parse_args()
    if a.mode == "furnish":
        try: run_furnish(a.room, a.budget, a.style, drama=a.drama)
        except Exception as e: emit("error", message=f"{type(e).__name__}: {e}")
    else:
        req = json.loads(sys.stdin.read() or "{}")
        try: print(json.dumps(run_chat(a.room, req.get("message", ""), req.get("plan") or {}, req.get("budget") or a.budget, req.get("style") or a.style)))
        except Exception as e: print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
