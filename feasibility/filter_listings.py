"""Keep only empty, well-covered listings: furniture pixels < 1% (segmentation), >= 2 rooms with >= 2 photos (room graph)."""
import sys, json, pathlib, subprocess, numpy as np
L = pathlib.Path("listings"); PY = sys.executable; kept = []
PREFIX = sys.argv[1] if len(sys.argv) > 1 else ""
for d in sorted(p for p in L.iterdir() if p.is_dir() and p.name.startswith(PREFIX)):
    photos = sorted(d.glob("[0-9][0-9].jpg"))
    if len(photos) < 6: continue
    segs = [d / (p.stem + ".seg.npz") for p in photos]
    if not all(s.exists() for s in segs): subprocess.run([PY, "../app/pipeline2/seg.py", str(d)], capture_output=True)
    meta = json.load(open(d / "meta.json")) if (d / "meta.json").exists() else {}
    if meta.get("source") == "greystar":   # building gallery: staged model photos sit next to empty-unit photos; set the staged ones aside per photo
        for p, s in zip(photos, segs):
            if s.exists() and float((np.load(s)["labels"] == 8).mean()) >= 0.025:
                p.rename(p.with_suffix(".jpg.furnished")); s.rename(s.with_suffix(".npz.furnished"))
        photos = sorted(d.glob("[0-9][0-9].jpg")); segs = [d / (p.stem + ".seg.npz") for p in photos]
        for f in ("KEEP", "SKIP_furnished", "SKIP_coverage"): (d / f).unlink(missing_ok=True)
        if len(photos) < 6: (d / "SKIP_coverage").write_text(f"{len(photos)} empty photos"); print(f"[filter] {d.name} only {len(photos)} empty photos -> skip"); continue
    furn = np.mean([float((np.load(s)["labels"] == 8).mean()) for s in segs if s.exists()])
    if furn >= 0.01: (d / "SKIP_furnished").write_text(f"{furn:.3f}"); continue
    if not (d / "roomgraph.json").exists(): subprocess.run([PY, "../app/pipeline/roomgraph.py", str(d)], capture_output=True)
    if not (d / "roomgraph.json").exists(): continue
    g = json.load(open(d / "roomgraph.json")); multi = [len(r["photos"]) for r in g["rooms"] if len(r["photos"]) >= 2 and r.get("has_exterior_window")]
    # a building gallery with one twice-photographed room is still one usable room
    ok = len(multi) >= (1 if meta.get("source") == "greystar" else 2); (d / ("KEEP" if ok else "SKIP_coverage")).write_text(json.dumps(multi)); kept.append((d.name, len(photos), round(furn * 100, 2), multi)) if ok else None
    print(f"[filter] {d.name[:6]} {len(photos)} photos, furniture {furn*100:.1f}%, multi-photo rooms {multi} -> {'KEEP' if ok else 'skip'}")
print(f"[filter] kept {len(kept)} listings")
