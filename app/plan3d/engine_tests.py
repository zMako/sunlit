"""Golden regression checks for the plan engine (geometry only: rooms, walls, openings; names/fixtures come from the VLM and
are not compared). For every app/plan3d/golden/<unit>.json:
  - room count within +-1, door count within +-1, window count within +-1
  - every golden room is matched (by its centroid) to a room whose area is within 10%; areas after rescale.py
Modes:
  engine_tests.py            compare against app/plan3d/layouts/<unit>.json (the pipeline's output, after rescale.py)
  engine_tests.py --fresh    run the engine geometry-only now (extract + metric_layout, no VLM) and put it on the golden's
                             scale (golden m_per_px; same pixel frame), so geometry is compared independently of the scale source
Exit status 1 when any check fails. Extra args: unit names to restrict to."""
import sys, json, glob, pathlib
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; sys.path.insert(0, str(HERE))
from shapely.geometry import Polygon, Point

def counts(L):
    return {t: sum(1 for o in L["openings"] if o["type"] == t) for t in ("door", "window", "opening")}

def fresh_layout(G):
    import plan_engine as pe
    p = pathlib.Path(G["plan_image"]); p = p if p.is_absolute() else ROOT / "feasibility/listings" / G["listing"] / "plans" / p.name
    if not p.exists(): p = ROOT / "feasibility/listings" / G["listing"] / "plans" / pathlib.Path(G["plan_image"]).name
    E = pe.extract(str(p)); L = pe.metric_layout(E, G["unit"], G["listing"], str(p))
    # same pixel frame as the golden (load_ink resizes identically): re-express on the golden's scale and origin
    k = G["scale"]["m_per_px"] / L["scale"]["m_per_px"]; gox, goy = G["scale"]["origin_px"]; ox, oy = L["scale"]["origin_px"]; g = G["scale"]["m_per_px"]
    def tr(x, z): return [round((x / L["scale"]["m_per_px"] + ox - gox) * g, 3), round((z / L["scale"]["m_per_px"] + oy - goy) * g, 3)]
    for r in L["rooms"]: r["polygon"] = [tr(x, z) for x, z in r["polygon"]]; r["area_m2"] = round(r["area_m2"] * k * k, 2)
    for o in L["openings"]: o["width_m"] = round(o["width_m"] * k, 3)
    L["scale"]["m_per_px"] = g; return L

def check(G, L):
    fails = []; nG, nL = len(G["rooms"]), len(L["rooms"])
    if abs(nG - nL) > 1: fails.append(f"rooms {nG} -> {nL}")
    cG, cL = counts(G), counts(L)
    for t in ("door", "window"):
        if abs(cG[t] - cL[t]) > 1: fails.append(f"{t}s {cG[t]} -> {cL[t]}")
    polys = []
    for r in L["rooms"]:
        try: P = Polygon(r["polygon"]); polys.append((r, P if P.is_valid else P.buffer(0)))
        except Exception: pass
    for gr in G["rooms"]:
        try: c = Polygon(gr["polygon"]).buffer(0).representative_point()
        except Exception: continue
        hit = [r for r, P in polys if P.contains(c)]
        if not hit:
            near = sorted(polys, key=lambda rp: rp[1].distance(c))
            hit = [near[0][0]] if near and near[0][1].distance(c) < 1.0 else []
        if not hit: fails.append(f"{gr['id']} ({gr.get('name')}, {gr['area_m2']} m2) unmatched"); continue
        a = hit[0]["area_m2"]
        if abs(a - gr["area_m2"]) > 0.10 * gr["area_m2"]: fails.append(f"{gr['id']} ({gr.get('name')}) area {gr['area_m2']} -> {a} m2")
    return fails, {"rooms": (nG, nL), "doors": (cG["door"], cL["door"]), "windows": (cG["window"], cL["window"])}

def main():
    fresh = "--fresh" in sys.argv; only = [a for a in sys.argv[1:] if not a.startswith("--")]; bad = 0; n = 0
    for f in sorted(glob.glob(str(HERE / "golden" / "*.json"))):
        G = json.load(open(f)); unit = G["unit"]
        if only and unit not in only: continue
        n += 1
        if fresh:
            try: L = fresh_layout(G)
            except Exception as e: print(f"FAIL {unit}: engine error {type(e).__name__}: {e}"); bad += 1; continue
        else:
            lf = HERE / "layouts" / f"{unit}.json"
            if not lf.exists(): print(f"SKIP {unit}: no layouts/{unit}.json"); continue
            L = json.load(open(lf))
        fails, s = check(G, L)
        tag = "ok  " if not fails else "FAIL"; bad += bool(fails)
        print(f"{tag} {unit}: rooms {s['rooms'][0]}->{s['rooms'][1]}, doors {s['doors'][0]}->{s['doors'][1]}, windows {s['windows'][0]}->{s['windows'][1]}")
        for x in fails: print(f"       - {x}")
    print(f"{n - bad}/{n} golden layouts pass ({'fresh geometry' if fresh else 'layouts/'})")
    sys.exit(1 if bad else 0)

if __name__ == "__main__": main()
