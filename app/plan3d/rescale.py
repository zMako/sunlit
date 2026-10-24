"""One scale rule for every layout: interior area must match the unit's known square footage.
Priority of the area source: (1) per-plan square footage from the listing (meta floorplans[].sqft, filled by
feasibility/sightmap_sqft.py), (2) square footage printed on the plan (annotation sqft_printed / plan_reader
total_sqft_printed), (3) a bedroom-count prior for SF rentals. Listed square footage is gross (to the outside of the walls);
the sum of room polygons is net interior, taken as 0.85 of gross. Plans whose scale came from PRINTED room dimensions are
left alone unless --all. Usage: rescale.py [--all] [unit ...]"""
import sys, json, glob, pathlib, math
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]
PRIOR_GROSS_M2 = {0: 42.0, 1: 62.0, 2: 88.0, 3: 115.0, 4: 140.0}   # SF rental medians by bedroom count (gross)
NET_OF_GROSS = 0.85

def target_area(L, meta):
    pimg = pathlib.Path(L["plan_image"]).name; fp = next((p for p in meta.get("floorplans", []) if p.get("file", "").endswith(pimg)), {})
    if fp.get("sqft"): return fp["sqft"] * 0.092903 * NET_OF_GROSS, f"listing sqft {fp['sqft']}"
    sp = L["scale"].get("sqft_printed") or L["scale"].get("sqft_listed")
    if sp: return float(sp) * 0.092903 * NET_OF_GROSS, f"printed sqft {sp}"
    beds = fp.get("bedrooms")
    if beds is None: beds = sum(1 for r in L["rooms"] if r["type"] == "bedroom")
    return PRIOR_GROSS_M2.get(min(int(beds), 4), 62.0) * NET_OF_GROSS, f"prior {beds} bedroom(s)"

def rescale(L, k):
    def sc(v): return round(v * k, 3)
    for w in L["walls"]: w["a"] = [sc(w["a"][0]), sc(w["a"][1])]; w["b"] = [sc(w["b"][0]), sc(w["b"][1])]; w["thickness_m"] = sc(w["thickness_m"])
    for o in L["openings"]: o["s0"], o["s1"], o["width_m"] = sc(o["s0"]), sc(o["s1"]), sc(o["width_m"])
    for r in L["rooms"]: r["polygon"] = [[sc(x), sc(z)] for x, z in r["polygon"]]; r["area_m2"] = round(r["area_m2"] * k * k, 2)
    for f in L["fixtures"]: f["rect"].update({"x": sc(f["rect"]["x"]), "z": sc(f["rect"]["z"]), "w": sc(f["rect"]["w"]), "d": sc(f["rect"]["d"])})
    L["scale"]["m_per_px"] = round(L["scale"]["m_per_px"] * k, 5)

def main():
    force = "--all" in sys.argv; units = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = [HERE / "layouts" / f"{u}.json" for u in units] if units else [pathlib.Path(f) for f in glob.glob(str(HERE / "layouts" / "*.json")) if not f.endswith(("index.json", "test_unit.json"))]
    for f in files:
        L = json.load(open(f)); src = (L["scale"]["from"] or ["none"])[0]
        if src.startswith("reader_dims+printed") and not force: print(f"[rescale] {L['unit']}: keep (printed dims)"); continue
        meta = json.load(open(ROOT / "feasibility/listings" / L["listing"] / "meta.json"))
        tgt, why = target_area(L, meta); cur = sum(r["area_m2"] for r in L["rooms"])
        if cur <= 0: continue
        k = math.sqrt(tgt / cur)
        if 0.6 <= k <= 1.67 or force or not src.startswith("reader"):
            rescale(L, k); L["scale"]["from"] = [f"area:{why}"] + [s for s in L["scale"]["from"] if not s.startswith("area:")]; L["scale"]["rescale_k"] = round(k, 3)
            json.dump(L, open(f, "w"), indent=1); print(f"[rescale] {L['unit']}: {cur:.1f} -> {tgt:.1f} m2 (k {k:.2f}, {why})")
        else: print(f"[rescale] {L['unit']}: skip, k {k:.2f} out of range ({why})")

if __name__ == "__main__": main()
