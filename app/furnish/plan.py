"""Furnish a room: pick products from the IKEA facts catalogue for the room type, size and budget (Claude chooses; a
deterministic picker is the fallback), place them with place.py, write app/furnish/plans/<room>.json.
    plan.py <room_name> [--budget N] [--style "..."] [--model haiku|sonnet|opus]      (room JSON: app/rooms/<room>.json)"""
import sys, re, json, math, pathlib, argparse
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import place

SETS = {"bedroom": ["bed", "nightstand", "nightstand", "dresser", "rug", "floor_lamp"], "living": ["sofa", "coffee_table", "tv_bench", "rug", "bookcase", "floor_lamp", "armchair"],
        "dining": ["dining_table", "dining_chair", "dining_chair", "dining_chair", "dining_chair"], "kitchen": ["dining_table", "dining_chair", "dining_chair"],
        "office": ["desk", "desk_chair", "bookcase", "floor_lamp"], "other": ["sofa", "coffee_table", "rug"]}
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}

def room_info(R):
    xs = [p[0] for p in R["polygon"]]; zs = [p[1] for p in R["polygon"]]
    bw, bd = (max(xs) - min(xs)), (max(zs) - min(zs))   # bounding box, not edge lengths: notched polygons have tiny edges
    return {"area_m2": R.get("area_m2"), "long_m": round(max(bw, bd), 2), "short_m": round(min(bw, bd), 2),
            "ceiling_m": R.get("ceiling_m"), "n_windows": len(R.get("windows", [])), "n_doors": len([d for d in R.get("doors", []) if d.get("width_m", 0) >= 0.55]),
            "wall_colour": (R.get("vlm") or {}).get("wall_colour"), "floor": (R.get("vlm") or {}).get("floor_material")}

def fits(item, info):
    w, d = item.get("width_m"), item.get("depth_m")
    if not w or not d or not info.get("long_m") or not info.get("short_m"): return bool(w and d)
    return min(w, d) <= info["short_m"] - 0.6 and max(w, d) <= info["long_m"] - 0.3

def pick_deterministic(cat_items, wanted, info, budget):
    chosen = []; spent = 0.0
    for cat in wanted:
        opts = sorted([i for i in cat_items.get(cat, []) if fits(i, info) and i.get("price_usd")], key=lambda i: i["price_usd"])
        if not opts: continue
        mid = opts[len(opts) // 2] if budget is None or spent + opts[len(opts) // 2]["price_usd"] <= budget * 0.9 else opts[0]
        chosen.append(mid); spent += mid["price_usd"]
    return chosen, "deterministic (median price per category that fits)"

def pick_claude(cat_items, wanted, info, budget, style, model, room_type, listing_hint):
    import claude_client as cc
    short = []
    for cat in sorted(set(wanted)):
        for i in cat_items.get(cat, []):
            if fits(i, info): short.append({"id": i["id"], "cat": cat, "name": i["name"][:60], "w": i["width_m"], "d": i["depth_m"], "h": i["height_m"], "usd": i.get("price_usd"), "color": i.get("color")})
    if not short: return None, "no candidates"
    system = ("You are an interior planner furnishing an EMPTY rental room with real products from a catalogue. Choose one product per requested slot "
              "(the same product may fill repeated slots, e.g. two nightstands), respecting the budget, the room size, and a coherent style (matching colours/wood). "
              "Reply with JSON only: {\"items\": [{\"id\": str, \"slot\": str, \"why\": str (at most 12 words)}], \"palette\": str (one line), \"notes\": str (one sentence)}.")
    text = (f"Room type: {room_type}. Room: {json.dumps(info)}. Listing hint: {listing_hint[:300]}\nBudget USD: {budget or 'none'}. Style: {style or 'calm, modern, light'}.\n"
            f"Slots to fill: {wanted}\nCatalogue (facts from IKEA US product pages):\n" + "\n".join(json.dumps(s) for s in short))
    schema = {"type": "object", "additionalProperties": False, "properties": {"items": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "string"}, "slot": {"type": "string"}, "why": {"type": "string"}}, "required": ["id", "slot", "why"]}}, "palette": {"type": "string"}, "notes": {"type": "string"}}, "required": ["items", "palette", "notes"]}
    import spend as sp
    c = cc.client(); messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    n_in = c.messages.count_tokens(model=model, system=system, messages=messages).input_tokens; sp.check("anthropic", sp.anthropic_estimate(model, n_in, 4000))
    r = c.messages.create(model=model, max_tokens=4000, system=system, messages=messages, output_config={"format": {"type": "json_schema", "schema": schema}, "effort": "medium"})
    usd = sp.anthropic_charge(model, r.usage, note=f"furnish {room_type}"); out = "".join(b.text for b in r.content if b.type == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if not m: return None, f"claude returned no JSON (${usd:.4f})"
    try: j = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        (HERE / "plans" / "_last_bad_response.txt").write_text(out); return None, f"claude JSON unparsable at {e.pos} (${usd:.4f}); raw saved; deterministic picks used"
    by_id = {i["id"]: i for c in cat_items.values() for i in c}
    chosen = [dict(by_id[x["id"]], slot=x.get("slot"), why=x.get("why")) for x in j.get("items", []) if x.get("id") in by_id]
    return chosen, f"claude {model} ${usd:.4f}; palette: {j.get('palette')}; {j.get('notes', '')[:200]}"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("room"); ap.add_argument("--budget", type=float); ap.add_argument("--style", default=""); ap.add_argument("--model", default="haiku"); ap.add_argument("--no-claude", action="store_true")
    a = ap.parse_args(); R = place.normalize(json.load(open(ROOT / "rooms" / f"{a.room}.json"))); info = room_info(R)
    m = re.match(r"p2_(.+?)_([a-z_]+)_(\d+)(?:_[AB])?$", a.room); room_type = R.get("type") or (m.group(2) if m else "other")   # plan-engine rooms carry their type; legacy names encode it
    listing_hint = ""
    if m:
        lid = m.group(1); d = ROOT.parent / "feasibility" / "listings"
        cand = [p for p in d.iterdir() if p.name.startswith(lid)] if d.exists() else []
        if cand and (cand[0] / "meta.json").exists(): meta = json.load(open(cand[0] / "meta.json")); listing_hint = f"{meta.get('title', '')}. {meta.get('body', '')[:200]}"
    cat = json.load(open(HERE / "catalog.json")); cat_items = {}
    for i in cat["items"]: cat_items.setdefault(i["category"], []).append(i)
    for k, v in cat_items.items():   # prefer products with a real 3D model; keep model-less ones only where a category has no modelled product
        with_model = [i for i in v if i.get("model_glb")]
        if with_model: cat_items[k] = with_model
    wanted = SETS.get(room_type, SETS["other"])
    chosen, how = (None, "skipped") if a.no_claude else pick_claude(cat_items, wanted, info, a.budget, a.style, MODELS.get(a.model, a.model), room_type, listing_hint)
    if not chosen: chosen, how = pick_deterministic(cat_items, wanted, info, a.budget)
    items = [{"id": c["id"] + (f"#{k}" if sum(1 for x in chosen[:k] if x["id"] == c["id"]) else ""), "name": c["name"], "category": c["category"], "w_m": c["width_m"], "d_m": c["depth_m"], "h_m": c["height_m"],
              "price_usd": c.get("price_usd"), "product_url": c["product_url"], "image": c.get("image"), "model_glb_url": c.get("model_glb_url"), "model_glb": c.get("model_glb"), "why": c.get("why")} for k, c in enumerate(chosen)]
    placed, walkable = place.place(R, items)
    plan = {"room": a.room, "room_type": room_type, "items": placed, "total_usd": round(sum(i.get("price_usd") or 0 for i in placed if "x" in i), 2), "walkable": walkable, "picker": how, "room_info": info}
    (HERE / "plans").mkdir(exist_ok=True); json.dump(plan, open(HERE / "plans" / f"{a.room}.json", "w"), indent=1)
    print(json.dumps({"room": a.room, "items": len(placed), "placed": sum(1 for i in placed if "x" in i), "total_usd": plan["total_usd"], "walkable": walkable, "picker": how[:120]}))

if __name__ == "__main__": main()
