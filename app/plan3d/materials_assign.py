"""Pick library materials for a unit's rooms from the listing's photos: photos linked to a plan room (plan_link.json) decide
that room; every other room takes the building-level pick for its room kind (kitchen/bath from kitchen/bath photos, the rest
from living/bedroom photos). Writes layout["materials"]. Usage: materials_assign.py <unit> [<unit> ...]"""
import sys, json, pathlib, collections
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; sys.path.insert(0, str(ROOT / "app/furnish")); import matmatch
WET = {"kitchen", "bathroom", "laundry"}

def photo_matches(listing_dir, idx, cache):
    key = f"{listing_dir.name}:{idx}"
    if key not in cache:
        try: r, _ = matmatch.match(str(listing_dir), str(idx)); cache[key] = r
        except Exception as e: cache[key] = {"error": str(e)}
    return cache[key]

def assign(unit, cache):
    L = json.load(open(HERE / "layouts" / f"{unit}.json")); lid = L["listing"]; ldir = ROOT / "feasibility/listings" / lid
    meta = json.load(open(ldir / "meta.json")); plan_file = pathlib.Path(L["plan_image"]).name
    link = json.load(open(ldir / "plan_link.json")) if (ldir / "plan_link.json").exists() else None
    rg = json.load(open(ldir / "roomgraph.json")) if (ldir / "roomgraph.json").exists() else None
    photo_type = {}
    if rg:
        for r in rg["rooms"]:
            for i in r["photos"]: photo_type[i] = r["type"]
    photos = sorted(int(p.stem) for p in ldir.glob("[0-9][0-9].jpg"))
    # per-room photos from the link (same plan file, room name)
    room_photos = collections.defaultdict(list)
    if link:
        for ph in link.get("photos", []):
            if ph.get("plan") == plan_file and ph.get("room"):
                for r in L["rooms"]:
                    if r["name"].lower() == ph["room"].lower(): room_photos[r["id"]].append(ph["index"])
    # building-level picks per kind
    def best(surface, idxs):
        votes = collections.Counter(); scores = {}
        for i in idxs:
            m = photo_matches(ldir, i, cache)
            for c in (m.get(surface) or [])[:1]: votes[c["id"]] += 1; scores[c["id"]] = max(scores.get(c["id"], 0), c["score"])
        return votes.most_common(1)[0][0] if votes else None
    wet_idx = [i for i in photos if photo_type.get(i) in WET]; dry_idx = [i for i in photos if photo_type.get(i) not in WET]
    bld = {"dry": {s: best(s, dry_idx[:8]) for s in ("floor", "wall")}, "wet": {s: best(s, wet_idx[:6]) for s in ("floor", "wall")}}
    mats = {"floor": {}, "wall": {}, "ceiling": None, "door": None, "cabinet": None, "counter": None, "baseboard": None}
    for r in L["rooms"]:
        own = room_photos.get(r["id"], []); kind = "wet" if r["type"] in WET else "dry"
        fl = best("floor", own) if own else None; wa = best("wall", own) if own else None
        mats["floor"][r["id"]] = fl or bld[kind]["floor"] or bld["dry"]["floor"]; mats["wall"][r["id"]] = wa or bld[kind]["wall"] or bld["dry"]["wall"]
        r["material_source"] = "room photos" if own else f"building {kind}"
    kit = [i for i in photos if photo_type.get(i) == "kitchen"]
    if kit:
        m = photo_matches(ldir, kit[0], cache); fx = (m.get("fixture") or [])[:1]
        if fx: mats["cabinet"] = fx[0]["id"]
    L["materials"] = {k: v for k, v in mats.items() if v}; json.dump(L, open(HERE / "layouts" / f"{unit}.json", "w"), indent=1)
    return {"unit": unit, "floor": mats["floor"], "wall": {k: v for k, v in mats["wall"].items() if v}, "linked_rooms": {k: v for k, v in room_photos.items()}, "cabinet": mats["cabinet"]}

if __name__ == "__main__":
    cache = {}
    for u in sys.argv[1:]: print(json.dumps(assign(u, cache)))
