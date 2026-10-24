"""Push photo facts into the layouts: per room material ids (floor/wall/ceiling/door/cabinet/counter/baseboard), paint
colours, window specs (sill/head/style) and plank direction. Rooms with linked photos use them; the rest take the
building-level pick for their kind (kitchen/bath from wet-room photos, others from dry-room photos).
Source: <listing>/photo_facts.json (made by photo_facts.py; built here if missing). Usage: materials_assign.py <unit> [...]"""
import sys, json, pathlib, collections
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; sys.path.insert(0, str(HERE))
WET = {"kitchen", "bathroom", "laundry"}

def facts_for(lid):
    f = ROOT / "feasibility/listings" / lid / "photo_facts.json"
    if not f.exists():
        import photo_facts; photo_facts.run(ROOT / "feasibility/listings" / lid)
    return json.load(open(f))

def vote(photos, getter):
    c = collections.Counter()
    for ph in photos:
        v = getter(ph)
        if v: c[v] += 1
    return c.most_common(1)[0][0] if c else None

def median(vals):
    vals = [v for v in vals if v is not None]
    return round(sorted(vals)[len(vals) // 2], 2) if vals else None

def plank_axis(ph):
    """Plank direction in room axes (EW or NS) from the photo's direction relative to the wall it faces."""
    d = ph.get("floor_direction"); w = ph.get("primary_wall") or (ph.get("facing_walls") or [None])[0]
    if d in (None, "unknown") or not w: return None
    along_wall = d == "along_photo_x"
    return ("EW" if along_wall else "NS") if w in ("N", "S") else ("NS" if along_wall else "EW")

def assign(unit):
    L = json.load(open(HERE / "layouts" / f"{unit}.json")); lid = L["listing"]; F = facts_for(lid); plan_file = pathlib.Path(L["plan_image"]).name
    photos = [p for p in F["photos"] if "error" not in p]; S = F["unit_summary"]
    per_room = collections.defaultdict(list)
    for ph in photos:
        if ph.get("plan") == plan_file and ph.get("plan_room"):
            for r in L["rooms"]:
                if r["name"].lower() == ph["plan_room"].lower(): per_room[r["id"]].append(ph)
    mats = {"floor": {}, "wall": {}, "ceiling": {}, "door": {}, "wall_rgb": {}, "ceiling_rgb": {}, "trim_rgb": {}, "cabinet": None, "counter": None, "baseboard": None}
    def pick(ph_list, kind_summary, surf):
        v = vote(ph_list, lambda ph: (ph.get("materials", {}).get(surf) or [None])[0]) if ph_list else None
        return v or kind_summary.get(surf) or S["dry"].get(surf) or S["building"].get(surf)
    for r in L["rooms"]:
        own = per_room.get(r["id"], []); kind = "wet" if r["type"] in WET else "dry"; KS = S.get(kind) or S["building"]; TS = (S.get("by_room_type") or {}).get(r["type"]) or {}
        base = {**KS, **{k: v for k, v in TS.items() if v}}
        mats["floor"][r["id"]] = pick(own, base, "floor"); mats["wall"][r["id"]] = pick(own, base, "wall"); mats["door"][r["id"]] = pick(own, base, "door")
        for col in ("wall_rgb", "ceiling_rgb", "trim_rgb"):
            v = None
            if own:
                vals = [ph["colours"].get(col) for ph in own if ph.get("colours", {}).get(col)]
                if vals: v = [int(sum(x[i] for x in vals) / len(vals)) for i in range(3)]
            mats[col][r["id"]] = v or base.get(col) or S["building"].get(col)
        ws = {"sill_m": median([w.get("sill_m") for ph in own for w in ph.get("windows", []) if w.get("sill_m") and 0.1 <= w["sill_m"] <= 1.6]),
              "head_m": median([w.get("head_m") for ph in own for w in ph.get("windows", []) if w.get("head_m") and 1.5 <= w["head_m"] <= 2.9]),
              "style": vote(own, lambda ph: next((w.get("style") for w in ph.get("windows", []) if w.get("style") not in (None, "unknown")), None)) if own else None}
        bw = base.get("window") or {}
        r["window_specs"] = {"sill_m": ws["sill_m"] or bw.get("sill_m") or 0.9, "head_m": ws["head_m"] or bw.get("head_m") or 2.2, "style": ws["style"] or bw.get("style") or "double-hung", "source": "room photos" if own and (ws["sill_m"] or ws["style"]) else ("building photos" if bw.get("sill_m") else "default")}
        r["floor_direction"] = vote(own, plank_axis) if own else None
        if not r["floor_direction"]:   # default: planks along the room's long axis
            xs = [p[0] for p in r["polygon"]]; zs = [p[1] for p in r["polygon"]]; r["floor_direction"] = "EW" if (max(xs) - min(xs)) >= (max(zs) - min(zs)) else "NS"; r["floor_direction_source"] = "long axis"
        else: r["floor_direction_source"] = "photo"
        r["material_source"] = "room photos" if own else f"building {kind}"
        if own: r["photos"] = [ph["index"] for ph in own]
    kit = [ph for ph in photos if ph.get("room_type") == "kitchen"]
    mats["cabinet"] = vote(kit, lambda ph: (ph.get("materials", {}).get("cabinet") or [None])[0]) if kit else None
    mats["counter"] = vote(kit, lambda ph: (ph.get("materials", {}).get("counter") or [None])[0]) if kit else None
    L["materials"] = {k: v for k, v in mats.items() if v}
    ceils = [ph.get("ceiling_m") for ph in photos if ph.get("ceiling_m")]
    if ceils: L["ceiling_m"] = round(sorted(ceils)[len(ceils) // 2], 2); L["ceiling_source"] = "photo structure"
    json.dump(L, open(HERE / "layouts" / f"{unit}.json", "w"), indent=1)
    return {"unit": unit, "linked_rooms": {k: [p["index"] for p in v] for k, v in per_room.items()}, "floor": mats["floor"], "wall": {k: v for k, v in mats["wall"].items()}, "windows": {r["id"]: r["window_specs"] for r in L["rooms"]}, "planks": {r["id"]: r["floor_direction"] for r in L["rooms"]}, "ceiling_m": L["ceiling_m"]}

if __name__ == "__main__":
    for u in sys.argv[1:]: print(json.dumps(assign(u)))
