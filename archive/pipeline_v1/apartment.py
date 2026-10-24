"""Phase 5/6 assembly: for every exterior room in the room graph, build the room, orient it with facade candidates + sun cue
(+ Claude's side judgement as a tie-break), compute year sun hours, and write app/apartments/<listing>.json with verdicts."""
import sys, json, re, pathlib, subprocess, os
ROOT = pathlib.Path(__file__).resolve().parents[1]; PY = str(ROOT.parent / "feasibility/.venv/bin/python"); HERE = pathlib.Path(__file__).parent
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def slug(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:24]

def verdict(per_month):
    h = [per_month[str(m)] if str(m) in per_month else per_month[m] for m in range(1, 13)]
    dark = [MONTHS[i] for i in range(12) if h[i] < 0.5]
    if len(dark) == 12: return "no direct sun at any time of year"
    if not dark: return f"direct sun every month; {min(h):.1f} to {max(h):.1f} h/day"
    # contiguous dark run around winter
    runs = []; cur = []
    for i in range(12):
        if h[i] < 0.5: cur.append(MONTHS[i])
        elif cur: runs.append(cur); cur = []
    if cur: runs.append(cur)
    if len(runs) == 2 and runs[0][0] == "Jan" and runs[-1][-1] == "Dec": runs = [runs[-1] + runs[0]]
    r = max(runs, key=len); span = f"{r[0]} to {r[-1]}" if len(r) > 1 else r[0]
    return f"{h[11]:.1f} h/day in Dec, {h[5]:.1f} h/day in Jun; 0 h {span}"

def main(listing_id, ceil_m="2.6", fit="1"):
    ldir = ROOT.parent / "feasibility/listings" / listing_id; g = json.load(open(ldir / "roomgraph.json")); meta = json.load(open(ldir / "meta.json"))
    site = json.load(open(ROOT / "sites" / listing_id / "site.json"))
    out = {"listing": listing_id, "title": meta["title"], "address": site["address"], "lat": site["lat"], "lon": site["lon"], "floor": site["floor"] or g["unit"]["floor"],
           "rooms": [], "graph_model": g.get("_model"), "graph_usd": g.get("_usd")}
    if out["floor"] and site["floor"] != out["floor"]: site["floor"] = out["floor"]; json.dump(site, open(ROOT / "sites" / listing_id / "site.json", "w"))
    for k, r in enumerate(g["rooms"]):
        if not r["has_exterior_window"] or not r["photos"]: continue
        name = f"{listing_id[:6]}_{slug(r['type'])}_{k}"; photos = ",".join(f"{i:02d}.jpg" for i in r["photos"])
        env = dict(os.environ, FIT=fit)
        b = subprocess.run([PY, str(HERE / "build_room.py"), str(ldir), name, photos, ceil_m], capture_output=True, text=True, env=env)
        lay = [l for l in b.stdout.splitlines() if l.startswith("[layout]")]
        if b.returncode != 0 or not lay: print(f"[apt] {name}: build failed: {b.stderr.strip().splitlines()[-1] if b.stderr.strip() else b.stdout[-200:]}"); continue
        wj = ROOT / "rooms" / f"{name}_world.json"
        if wj.exists(): wj.unlink()   # never reuse a stale placement
        mj = ROOT / "rooms" / f"{name}.json"; mm = json.load(open(mj)); mm["claude_side"] = r["likely_facade"]; json.dump(mm, open(mj, "w"), indent=1)
        o = subprocess.run([PY, str(HERE / "orient.py"), name, listing_id], capture_output=True, text=True)
        if o.returncode != 0: print(f"[apt] {name}: orient failed: {o.stderr.strip().splitlines()[-1]}"); 
        w = json.load(open(ROOT / "rooms" / f"{name}_world.json")) if (ROOT / "rooms" / f"{name}_world.json").exists() else None
        room = {"name": name, "label": r["name"], "type": r["type"], "photos": r["photos"], "claude_side": r["likely_facade"], "claude_sun": r["direct_sun_visible_in_photos"], "window_description": r["window_description"]}
        if w and w.get("undetermined"):
            room.update({"how": w["how"], "verdict": "orientation not determined from photos (no sun patch, side room)"}); print(f"[apt] {name} ({r['name']}): {w['how']}")
        elif w:
            pm = {str(m): max(s_["per_month_hours"][str(m)] for s_ in w["sun"]) for m in range(1, 13)} if w["sun"] else {str(m): 0.0 for m in range(1, 13)}
            room.update({"facing": w["facade"]["bearing"], "facade_street": w["facade"].get("street"), "how": w["how"], "windows": [{"w": s_["width_m"], "h": s_["height_m"], "sill": s_["sill_m"], "bearing": s_["bearing"], "annual_hours": s_["annual_hours"]} for s_ in w["sun"]],
                         "per_month_hours": pm, "annual_hours": max([s_["annual_hours"] for s_ in w["sun"]] or [0]), "verdict": verdict(pm), "scores": w.get("scores")})
            print(f"[apt] {name} ({r['name']}): facing {w['facade']['bearing']}° via {w['how']} | {room['verdict']}")
        else: print(f"[apt] {name}: no placement")
        out["rooms"].append(room)
    (ROOT / "apartments").mkdir(exist_ok=True); json.dump(out, open(ROOT / "apartments" / f"{listing_id}.json", "w"), indent=1)
    print(f"[apt] wrote apartments/{listing_id}.json with {len(out['rooms'])} rooms")

if __name__ == "__main__": main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "2.6")
