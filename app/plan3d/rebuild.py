"""Rebuild layouts with the learned walls (cubi.py masks in plan_engine.extract), offline: no paid calls. Room names, types,
fixtures and materials are carried over from the previous layout of the same plan by overlap in plan pixels; rooms the
previous layout never had are named from the cached plan reading, else from the model's room class.

  rebuild.py [--out DIR] [units ...]   build into DIR (default layouts_cubi/), every unit of layouts/index.json if none given
  rebuild.py --promote [units ...]     back up layouts/<unit>.json to layouts_ink/, copy the staged layout in, run
                                       rescale.py + rooms_export.py, refresh layouts/index.json (protected units are skipped)"""
import sys, json, pathlib, shutil, subprocess, time, traceback
import numpy as np
from shapely.geometry import Polygon, Point
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")
sys.path.insert(0, str(HERE))
import plan_engine, cubi

# units with saved furnishing plans keyed by room id (app/furnish/plans/<unit>__<room>.json): a rebuild renumbers rooms
PROTECTED = {p.name.split("__")[0] for p in (HERE.parent / "furnish" / "plans").glob("*__*.json")}
MODEL_TYPE = {3: ("kitchen", "Kitchen"), 4: ("living", "Living Room"), 5: ("bedroom", "Bedroom"), 6: ("bathroom", "Bath"), 7: ("hallway", "Entry"), 9: ("closet", "Closet"), 10: ("other", "Garage"), 11: ("other", "Room")}

def to_px(L):
    """metres -> original image pixels for this layout's scale"""
    sc = L["scale"]; m, (ox, oy), s = sc["m_per_px"], sc["origin_px"], sc.get("image_scale", 1) or 1
    return lambda x, z: ((x / m + ox) / s, (z / m + oy) / s)

def to_m(L):
    sc = L["scale"]; m, (ox, oy), s = sc["m_per_px"], sc["origin_px"], sc.get("image_scale", 1) or 1
    return lambda px, py: (round((px * s - ox) * m, 3), round((py * s - oy) * m, 3))

def poly_px(L, r):
    f = to_px(L); P = Polygon([f(x, z) for x, z in r["polygon"]])
    return P if P.is_valid else P.buffer(0)

def generic(name): return not name or name.startswith("Room ")

def transfer(new, old, plan_path):
    """Names/types/fixtures/materials from `old` onto `new` (both layouts of the same plan image)."""
    newP = [poly_px(new, r) for r in new["rooms"]]; oldP = [poly_px(old, r) for r in old["rooms"]] if old else []
    P = cubi.load(plan_path); k = P["k"] if P else None
    match = {}
    for i, (r, A) in enumerate(zip(new["rooms"], newP)):
        best, bi = 0.0, None
        for j, B in enumerate(oldP):
            if A.area <= 0 or B.area <= 0: continue
            inter = A.intersection(B).area; sc = min(inter / A.area, inter / B.area)   # 1:1 correspondence, not containment
            if sc > best: best, bi = sc, j
        old_r = old["rooms"][bi] if bi is not None else None
        if old_r is not None and best >= 0.45 and not generic(old_r["name"]):
            r["name"], r["type"] = old_r["name"], old_r["type"]; r["named_from"] = "previous layout"; match[r["id"]] = old_r["id"]
        elif not generic(r["name"]): r["named_from"] = "plan reading (cached)"
        elif P is not None:   # the model's room class under the polygon
            from PIL import Image, ImageDraw
            m = Image.new("L", (P["rooms"].shape[1], P["rooms"].shape[0]), 0); ImageDraw.Draw(m).polygon([(x * k, y * k) for x, y in A.exterior.coords], fill=1)
            cls = P["rooms"][np.asarray(m) > 0]; cls = cls[np.isin(cls, list(MODEL_TYPE))]
            if cls.size: t, nm = MODEL_TYPE[int(np.bincount(cls).argmax())]; r["type"], r["name"], r["named_from"] = t, nm, "model room class"
        if r["id"] not in match and old_r is not None and best >= 0.2: match[r["id"]] = old_r["id"]   # materials still follow a partial overlap
    # same names twice ("Bedroom", "Bedroom") -> numbered
    seen = {}
    for r in new["rooms"]:
        seen.setdefault(r["name"], []).append(r)
    for nm, rs in seen.items():
        gen = [r for r in rs if r.get("named_from") == "model room class"]
        if len(rs) > 1 and gen:
            for n, r in enumerate(gen, 1): r["name"] = f"{nm} {n}"
    # fixtures: old metres -> plan px -> new metres, into the new room that holds the centre
    if old and old.get("fixtures"):
        fo, tn = to_px(old), to_m(new)   # metres per ORIGINAL image px = m_per_px * image_scale
        s_old = old["scale"]["m_per_px"] * (old["scale"].get("image_scale", 1) or 1); s_new = new["scale"]["m_per_px"] * (new["scale"].get("image_scale", 1) or 1)
        fx = []
        for f in old["fixtures"]:
            R = f["rect"]; cx, cy = fo(R["x"], R["z"]); x, z = tn(cx, cy)
            hit = next(((nr["id"], A) for nr, A in zip(new["rooms"], newP) if A.contains(Point(cx, cy))), None)
            if hit is None: continue
            # the footprint must sit mostly inside that room (an old misplaced counter would poke through a wall)
            hw, hd = R["w"] / 2 / s_old, R["d"] / 2 / s_old; from shapely.geometry import box as sbox
            from shapely import affinity; fp = affinity.rotate(sbox(cx - hw, cy - hd, cx + hw, cy + hd), R.get("rot_deg", 0), origin=(cx, cy))
            if fp.area > 0 and fp.intersection(hit[1]).area / fp.area < 0.8: continue
            g = s_new / s_old; fx.append(dict(f, rect=dict(R, x=x, z=z, w=round(R["w"] * g, 3), d=round(R["d"] * g, 3)), room=hit[0]))
        new["fixtures"] = fx
    if old and old.get("materials"):
        M = {}
        for key, v in old["materials"].items():
            if isinstance(v, dict): M[key] = {nid: v[oid] for nid, oid in match.items() if oid in v}
            else: M[key] = v
        new["materials"] = M
    new["review"] = {"rounds": 0, "rebuilt": "cubi offline", "named": {k: sum(1 for r in new["rooms"] if r.get("named_from") == k) for k in ("previous layout", "plan reading (cached)", "model room class")}}
    return new

def build(unit, out_dir):
    old_f = HERE / "layouts" / f"{unit}.json"; old = json.load(open(old_f)) if old_f.exists() else None
    pth = pathlib.Path(old["plan_image"]) if old else None
    if pth and not pth.is_absolute(): pth = ROOT / pth
    L, out = plan_engine.run(pth, old["listing"], unit, out_dir, offline=True)
    L["plan_image"] = old["plan_image"]   # keep the original string (other tools key on it)
    L = transfer(L, old, str(pth)); json.dump(L, open(out, "w"), indent=1); return L

def promote(units):
    bak = HERE / "layouts_ink"; bak.mkdir(exist_ok=True); stage = HERE / "layouts_cubi"; done = []
    for u in units:
        if u in PROTECTED: print(f"[promote] {u}: protected (saved furnishing plans), kept"); continue
        src = stage / f"{u}.json"
        if not src.exists(): continue
        cur = HERE / "layouts" / f"{u}.json"
        if cur.exists() and not (bak / f"{u}.json").exists(): shutil.copy2(cur, bak / f"{u}.json")
        shutil.copy2(src, cur)
        subprocess.run([PY, str(HERE / "rescale.py"), u], capture_output=True, text=True, cwd=str(ROOT))
        subprocess.run([PY, str(HERE / "rooms_export.py"), u], capture_output=True, text=True, cwd=str(ROOT)); done.append(u)
    # refresh the index entries of promoted units (rooms, area, fixtures) without touching the rest
    idx_f = HERE / "layouts" / "index.json"; idx = json.load(open(idx_f)); by = {d["unit"]: d for d in idx}
    for u in done:
        L = json.load(open(HERE / "layouts" / f"{u}.json")); d = by.get(u)
        if not d: continue
        d["rooms"] = [{"id": r["id"], "name": r["name"], "type": r["type"], "area_m2": r["area_m2"]} for r in L["rooms"]]
        d["area_m2"] = round(sum(r["area_m2"] for r in L["rooms"]), 1); d["n_fixtures"] = len(L["fixtures"]); d["scale_from"] = L["scale"]["from"]
        d["bedrooms"] = sum(1 for r in L["rooms"] if r["type"] == "bedroom"); d["walls_from"] = L.get("walls_from")
    json.dump(idx, open(idx_f, "w"), indent=1); print(f"[promote] {len(done)} promoted, backups in {bak}")

if __name__ == "__main__":
    a = sys.argv[1:]; out = HERE / "layouts_cubi"
    if "--out" in a: out = pathlib.Path(a[a.index("--out") + 1]); a = [x for x in a if x not in ("--out", str(out))]
    units = [x for x in a if not x.startswith("--")] or [d["unit"] for d in json.load(open(HERE / "layouts" / "index.json"))]
    if "--promote" in a: promote(units); sys.exit()
    out.mkdir(exist_ok=True); t0 = time.time(); ok = fail = 0
    for i, u in enumerate(units):
        try:
            L = build(u, out); ok += 1
            print(f"[rebuild] {u}: {len(L['rooms'])} rooms {len(L['walls'])} walls {len(L['openings'])} openings, walls {L.get('walls_from')}, named {L['review']['named']}", flush=True)
        except Exception as e:
            fail += 1; print(f"[rebuild] {u} FAILED: {type(e).__name__} {e}", flush=True)
            if "--trace" in a: traceback.print_exc()
    print(f"[rebuild] {ok} built, {fail} failed in {time.time() - t0:.0f}s -> {out}")
