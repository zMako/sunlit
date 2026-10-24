"""Scale-accuracy raw data for every unit in layouts/index.json (the walkable units). Re-runs the geometry only
(plan_engine.extract + metric_layout with sqft=None, no review extras, no VLM, no rescale.py) to get the engine's INTRINSIC
door-width scale, then collects ground truth already on disk:
  - printed room dimensions transcribed by plan_reader v2 (cached JSON next to the plan, `_file` = plan image name; only rooms
    with dims_source 'printed' and both width_text and depth_text are ground truth),
  - unit square footage: listing meta floorplans[].sqft, else the layout's scale.sqft_listed / sqft_printed, else plan_reader
    total_sqft_printed (all are square footage printed by the landlord on the plan or the listing).
Reader rooms are matched to extracted regions the way plan_engine.reader_anchor does (biggest region whose centroid lies in
the reader's rectangle +-3%). Writes data/gs_accuracy.json. Usage: gs_accuracy.py [n_workers=6]"""
import sys, json, glob, pathlib, multiprocessing as mp
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; P3 = HERE.parent; ROOT = P3.parents[1]; sys.path.insert(0, str(P3))
W_SRC = {"printed": 1.0, "scaled_from_plan": 0.6, "estimated": 0.3}

def reader_cache(plan):
    best = None
    for f in glob.glob(str(plan.parent / "plan_*.json")):
        try: g = json.load(open(f))
        except Exception: continue
        if g.get("_file") == plan.name and g.get("_schema") == 2 and (best is None or pathlib.Path(f).stat().st_mtime > best[0]): best = (pathlib.Path(f).stat().st_mtime, g)
    return best[1] if best else None

def one(unit):
    import plan_engine as pe
    L = json.load(open(P3 / "layouts" / f"{unit}.json")); lid = L["listing"]; plan = ROOT / "feasibility/listings" / lid / "plans" / pathlib.Path(L["plan_image"]).name
    out = {"unit": unit, "listing": lid, "scale_from": L["scale"]["from"], "final_area_m2": round(sum(r["area_m2"] for r in L["rooms"]), 2)}
    meta = json.load(open(ROOT / "feasibility/listings" / lid / "meta.json")); fp = next((p for p in meta.get("floorplans", []) if p.get("file", "").endswith(plan.name)), {})
    R = reader_cache(plan)
    sq = fp.get("sqft") or L["scale"].get("sqft_listed") or L["scale"].get("sqft_printed") or (R or {}).get("total_sqft_printed")
    out["sqft_gt"] = float(sq) if sq else None
    out["sqft_src"] = "listing" if fp.get("sqft") else ("layout" if (L["scale"].get("sqft_listed") or L["scale"].get("sqft_printed")) else ("reader" if sq else None))
    try:
        E = pe.extract(str(plan)); L0 = pe.metric_layout(E, unit, lid, str(plan), sqft=None)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:100]}"; return out
    has_door = "door_width" in L0["scale"]["from"]; mpp = L0["scale"]["m_per_px"]
    out.update(has_door_scale=has_door, door_mpp=mpp, door_area_m2=round(sum(r["area_m2"] for r in L0["rooms"]), 2), area_px=float(sum(r["area_m2"] for r in L0["rooms"]) / mpp ** 2))
    if R:
        H, W = E["room_labels"].shape; regions = []
        for r in E["rooms"]:
            ys, xs = np.where(E["room_labels"] == r["label"])
            regions.append({"label": int(r["label"]), "cx": xs.mean() / W, "cy": ys.mean() / H, "w_px": int(xs.max() - xs.min() + 1), "h_px": int(ys.max() - ys.min() + 1), "area_px": int(xs.size)})
        pairs = []
        for k, rr in enumerate(R.get("rooms", [])):
            fr = [rr.get(q) for q in ("x0_frac", "y0_frac", "x1_frac", "y1_frac")]
            if any(v is None for v in fr): continue
            inside = [g for g in regions if fr[0] - 0.03 <= g["cx"] <= fr[2] + 0.03 and fr[1] - 0.03 <= g["cy"] <= fr[3] + 0.03]
            if not inside: continue
            g = max(inside, key=lambda q: q["w_px"] * q["h_px"]); src = rr.get("dims_source") or "estimated"
            pairs.append({"k": k, "name": rr.get("name"), "type": rr.get("type"), "shape": rr.get("shape"), "src": src, "printed": src == "printed" and bool(rr.get("width_text")) and bool(rr.get("depth_text")),
                          "width_m": rr.get("width_m"), "depth_m": rr.get("depth_m"), "w_px": g["w_px"], "h_px": g["h_px"], "area_px": g["area_px"], "label": g["label"]})
        out["reader_has_dimensions"] = bool(R.get("has_dimensions")); out["pairs"] = pairs
    return out

if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    units = [e["unit"] for e in json.load(open(P3 / "layouts" / "index.json"))]
    with mp.Pool(nw) as pool: res = pool.map(one, units)
    (HERE / "data").mkdir(exist_ok=True); json.dump(res, open(HERE / "data" / "gs_accuracy.json", "w"), indent=1)
    print(f"[gs_accuracy] {len(res)} units, errors {sum(1 for r in res if 'error' in r)}")
