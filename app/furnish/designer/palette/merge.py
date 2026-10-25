"""Merge palette/results/*.jsonl (Haiku's reading of each hero photo) into palette.json {id: {parts, dominant, accent, sheen}}.
Re-run whenever more batches land. Skipped products are listed under "_skipped"."""
import json, glob, pathlib, collections
H = pathlib.Path(__file__).parent; out = {}; skipped = {}; bad = 0
FIN = {"fabric", "boucle", "velvet", "leather", "wood_light", "wood_mid", "wood_dark", "wood_black", "metal_chrome", "metal_black", "metal_brass", "metal_white", "metal_painted", "plastic", "glass", "glass_opal", "marble", "stone", "concrete", "ceramic", "lacquer", "paper", "rattan", "cork", "rubber"}
for f in sorted(glob.glob(str(H / "results" / "*.jsonl"))):
    for line in open(f):
        line = line.strip()
        if not line: continue
        try: r = json.loads(line)
        except Exception: bad += 1; continue
        if not r.get("id"): bad += 1; continue
        if r.get("skip"): skipped[r["id"]] = r["skip"]; continue
        parts = [p for p in (r.get("parts") or []) if p.get("finish") in FIN and isinstance(p.get("hex"), str) and len(p["hex"]) == 7]
        if not parts: bad += 1; continue
        out[r["id"]] = {"parts": parts[:4], "dominant": r.get("dominant"), "accent": r.get("accent"), "sheen": r.get("sheen"), "note": r.get("note")}
json.dump(dict(out, _skipped=skipped), open(H.parent / "palette.json", "w"))
print(f"palette.json: {len(out)} products, {len(skipped)} skipped, {bad} bad lines; finishes: {collections.Counter(p['finish'] for v in out.values() for p in v['parts']).most_common(8)}")
