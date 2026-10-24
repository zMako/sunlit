"""Which floor-plan room is this photographed room? A listing may carry several unit-type plans (e.g. a building's A/B/C
layouts) whose photos come from different units. Candidates = plan rooms of the same type with printed dimensions; the pick
minimises the dimension disagreement with the measured rectangle (measured sides count fully, inferred sides weakly), with a
small penalty on window count. Agreeing candidates -> ground truth ('floor_plan'); a lone best among disagreeing ones ->
'floor_plan_candidate' (looser cap in layout2)."""
import json, math, pathlib
import plan_reader

TYPE_ALIASES = {"living": {"living", "dining"}, "dining": {"dining", "living"}, "bedroom": {"bedroom", "office"}, "kitchen": {"kitchen"},
                "bathroom": {"bathroom"}, "office": {"office", "bedroom"}, "hallway": {"hallway", "entry"}, "other": set()}

def candidates(listing_dir, room_type, sqft_total=None):
    d = pathlib.Path(listing_dir) / "plans"; out = []
    if not d.exists(): return out
    for p in sorted(x for x in d.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        try: g = plan_reader.read_plan(p, sqft_total)
        except Exception as e: print(f"[plan] {p.name}: {type(e).__name__} {e}"); continue
        if not g or not g.get("has_dimensions"): continue
        for r in g["rooms"]:
            if r["type"] in TYPE_ALIASES.get(room_type, {room_type}) and r.get("width_m") and r.get("depth_m"):
                out.append({"plan": p.name, "room": r["name"], "type": r["type"], "w": float(r["width_m"]), "d": float(r["depth_m"]), "windows": r.get("windows"), "shape": r.get("shape", "rectangle")})
    return out

def match(cands, span_u, span_v, meas_u, meas_v, n_windows=None):
    """span_u/span_v: measured rectangle extents along the two axes; meas_u/meas_v: True when both sides of that axis were measured."""
    if not cands: return None
    def score(c, w, dd):
        s = 0.0
        for span, dim, m in ((span_u, w, meas_u), (span_v, dd, meas_v)):
            if span and span > 0: s += (1.0 if m else 0.35) * abs(math.log(dim / span))
        if n_windows is not None and c.get("windows") is not None: s += 0.15 * min(abs(n_windows - c["windows"]), 3)
        return s
    scored = []
    for c in cands:
        a, b = score(c, c["w"], c["d"]), score(c, c["d"], c["w"])
        scored.append((min(a, b), c, a <= b))     # third: True when plan width runs along u
    scored.sort(key=lambda t: t[0]); best_s, best, along_u = scored[0]
    areas = [c["w"] * c["d"] for c in cands]; agree = max(areas) / min(areas) <= 1.3 if areas else False
    source = "floor_plan" if (agree or len(cands) == 1) else "floor_plan_candidate"
    if len(scored) > 1 and not agree and scored[1][0] - best_s < 0.08: source = "floor_plan_candidate"
    return {"shape": "rectangle" if best["shape"] == "rectangle" else best["shape"], "width_m": best["w"], "depth_m": best["d"], "ceiling_m": None, "size_confidence": 1.0 if source == "floor_plan" else 0.7,
            "source": source, "plan": best["plan"], "plan_room": best["room"], "score": round(best_s, 3), "n_candidates": len(cands), "width_along_u": along_u}

if __name__ == "__main__":
    import sys
    c = candidates(sys.argv[1], sys.argv[2]); print(len(c), "candidates"); [print(" ", x) for x in c]
