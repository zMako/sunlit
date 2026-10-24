"""Fast-tier harness: every room of every listing with a room graph, no per-listing settings. Writes harness/<ts>/results.json
and a sheet of plan images. Usage: harness.py [listing ids...]"""
import sys, json, time, pathlib, traceback
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import build_room2
LIST = HERE.parents[1] / "feasibility/listings"; OUT = HERE.parents[0] / "harness"
def main(ids):
    ts = time.strftime("%m%d_%H%M"); out = OUT / ts; out.mkdir(parents=True, exist_ok=True); results = []
    for lid in ids:
        d = LIST / lid; g = d / "roomgraph.json"
        if not g.exists(): print(f"[harness] {lid}: no roomgraph, skipped"); continue
        if (d / "SKIP_furnished").exists(): print(f"[harness] {lid}: furnished, skipped"); continue
        graph = json.load(open(g)); meta = json.load(open(d / "meta.json"))
        for k, r in enumerate(graph["rooms"]):
            if len(r["photos"]) < 2: continue   # single-photo rooms are out of scope: not enough data to plan furniture
            name = f"p2_{lid[:6]}_{r['type']}_{k}"; photos = ",".join(f"{i:02d}.jpg" for i in r["photos"])
            try:
                res = build_room2.build(d, name, photos, 2.6, room_label=f"{r['type']}: {r['name']}")
                if res.get("ok") and res.get("n_photos", 0) < 2: res["ok"] = False; res["error"] = "only one photo survived the overlap check"
            except Exception as e: res = {"name": name, "ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-600:]}; print(f"[p2] {name}: FAILED {res['error']}")
            res.update({"listing": lid, "title": meta["title"][:40], "room": r["name"], "claude_windows": r.get("has_exterior_window"), "n_photos_graph": len(r["photos"])}); results.append(res)
            json.dump(results, open(out / "results.json", "w"), indent=1)
    # sheet of plans
    from PIL import Image, ImageDraw
    thumbs = []
    for res in results:
        p = HERE.parents[0] / "rooms" / f"{res['name']}_plan.png"
        im = Image.open(p).convert("RGB").resize((360, 360)) if p.exists() else Image.new("RGB", (360, 360), (40, 0, 0))
        dr = ImageDraw.Draw(im); dr.rectangle([0, 0, 360, 34], fill=(0, 0, 0)); dr.text((4, 2), f"{res['name'][3:]} {'OK' if res.get('ok') else 'FAIL'} {res.get('n_photos', res.get('n_photos_graph'))}ph", fill=(255, 255, 255))
        dr.text((4, 18), (f"{res['area_m2']}m2 w{res['n_walls']} i{res['n_inferred']} win{res['n_windows']} door{res['n_doors']} {res['s']}s" if res.get("ok") else str(res.get("error"))[:60]), fill=(255, 255, 0)); thumbs.append(im)
    cols = 6; rows = (len(thumbs) + cols - 1) // cols; sheet = Image.new("RGB", (cols * 360, max(1, rows) * 360))
    for i, im in enumerate(thumbs): sheet.paste(im, ((i % cols) * 360, (i // cols) * 360))
    sheet.save(out / "sheet.png"); ok = sum(1 for r in results if r.get("ok"))
    print(f"[harness] {ok}/{len(results)} rooms ok -> {out}")
if __name__ == "__main__": main(sys.argv[1:] or [p.name for p in LIST.iterdir() if (p / "roomgraph.json").exists()])
