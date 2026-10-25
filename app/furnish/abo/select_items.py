"""Step 2: classify candidates into planner categories, dedupe by 3D model, pick balanced set -> raw/selected.json (ranked, with spares)."""
import json, csv, gzip, re, collections, pathlib, random
H = pathlib.Path(__file__).resolve().parent; random.seed(7)
C = json.load(open(H / "raw/cand.json"))
M = {r["3dmodel_id"]: r for r in csv.DictReader(gzip.open(H / "raw/3dmodels.csv.gz", "rt"))}
def has(t, *ws): return any(re.search(w, t) for w in ws)
def classify(o):
    n = (o["name"] + " " + " ".join(o["node"] or [])).lower(); pt = o["pt"]; nm = o["name"].lower()
    if has(nm, r"\bcover\b", r"slipcover", r"\bpillow", r"cushion", r"replacement", r"\bkit\b", r"\bset of \d+ (chairs|stools)"): pass
    if pt == "RUG": return "rug"
    if pt == "HOME_MIRROR": return "mirror"
    if pt == "PLANTER": return "plant_pot"
    if pt in ("BED", "BED_FRAME"): return "bed" if not has(nm, r"headboard") else None
    if pt == "SOFA": return "sofa" if not has(nm, r"sofa (bed )?cover") else None
    if pt in ("LAMP", "LIGHT_FIXTURE", "HOME_LIGHTING_AND_LAMPS"):
        if has(nm, r"floor lamp", r"torchiere", r"arc lamp", r"tripod lamp", r"standing lamp", r"floor light", r"pole lamp"): return "floor_lamp"
        if has(nm, r"table lamp", r"desk lamp", r"bedside lamp", r"accent lamp", r"night ?stand lamp", r"buffet lamp", r"task lamp", r"reading lamp"): return "table_lamp"
        if pt == "LAMP" and has(nm, r"\blamp\b") and not has(nm, r"wall|pendant|ceiling|chandelier|string|shade only|replacement"): return "table_lamp"
        return None
    if pt in ("CHAIR", "STOOL_SEATING", "BEAN_BAG_CHAIR"):
        if has(nm, r"bar stool", r"counter stool", r"barstool", r"counter height", r"bar height", r"swivel stool", r"bar chair"): return "bar_stool"
        if has(nm, r"office chair", r"desk chair", r"task chair", r"computer chair", r"gaming chair", r"executive chair", r"ergonomic", r"swivel chair", r"drafting"): return "desk_chair"
        if has(nm, r"dining", r"kitchen chair", r"side chair", r"parsons", r"windsor"): return "dining_chair"
        if has(nm, r"accent chair", r"armchair", r"arm chair", r"recliner", r"club chair", r"lounge", r"wingback", r"wing chair", r"barrel", r"papasan", r"rocker|rocking", r"slipper chair", r"chaise", r"tub chair", r"sofa chair", r"upholstered chair", r"egg chair"): return "armchair"
        if pt == "CHAIR": return "dining_chair" if has(nm, r"\bchairs?\b") and has(nm, r"wood|dining|leg|metal|set of") else None
        return None
    if pt == "DESK": return "desk"
    if pt == "DRESSER": return "dresser"
    if pt == "SHELF": return "bookcase" if has(nm, r"book", r"shelf|shelves|shelving|etagere|\brack\b|\bstand\b|storage") else None
    if pt == "BENCH" or pt == "OTTOMAN":
        return "other" if has(nm, r"\bbench\b", r"ottoman", r"pouf", r"footstool") and not has(nm, r"cover") else None
    if pt in ("TABLE", "CABINET", "HOME_FURNITURE_AND_DECOR", "HOME", "FURNITURE", "STORAGE_RACK", "CLOTHES_RACK", "STORAGE_DRAWER"):
        if has(nm, r"nightstand", r"night stand", r"bedside table", r"bedside cabinet"): return "nightstand"
        if has(nm, r"tv stand", r"tv console", r"media console", r"entertainment center", r"tv cabinet", r"tv unit", r"media center", r"tv bench"): return "tv_bench"
        if has(nm, r"wardrobe", r"armoire", r"closet"): return "wardrobe"
        if has(nm, r"bookcase", r"bookshelf", r"book shelf", r"etagere", r"shelving unit", r"display shelf", r"ladder shelf", r"storage shelf"): return "bookcase"
        if has(nm, r"dresser", r"chest of drawers", r"chest"): return "dresser"
        if has(nm, r"coffee table", r"cocktail table"): return "coffee_table"
        if has(nm, r"dining table", r"kitchen table", r"dinette", r"dining set", r"pub table"): return "dining_table"
        if has(nm, r"end table", r"side table", r"accent table", r"console table", r"sofa table", r"nesting table", r"plant stand"): return "side_table"
        if has(nm, r"\bdesk\b", r"writing table", r"computer table"): return "desk"
        if has(nm, r"mirror") and not has(nm, r"frame only"): return "mirror"
        if has(nm, r"floor lamp"): return "floor_lamp"
        if has(nm, r"table lamp"): return "table_lamp"
        if pt == "TABLE": return "side_table" if has(nm, r"\btable\b") and not has(nm, r"tablecloth|runner|top only|cover|pad|bed table|folding|massage|picnic|camping|\bgame\b|pool|ping") else None
        if pt == "CABINET": return "other" if has(nm, r"cabinet|sideboard|buffet|credenza|console") else None
        return None
    return None
def inch(d):
    try:
        out = {}
        for k in ("height", "width", "length"):
            nv = d[k].get("normalized_value") or d[k]; v = nv["value"]; u = nv["unit"]
            out[k] = v * {"inches": .0254, "feet": .3048, "centimeters": .01, "meters": 1, "millimeters": .001, "yards": .9144}.get(u, float("nan"))
        return out
    except Exception: return None
by = collections.defaultdict(list); seen = set()
for o in C:
    m = M.get(o["model"]); 
    if not m or o["model"] in seen: continue
    cat = classify(o)
    if not cat: continue
    ex = sorted([float(m["extent_x"]), float(m["extent_y"]), float(m["extent_z"])])
    if ex[0] < .01 or ex[2] > 4.5: continue
    ld = inch(o["dims"]) if o["dims"] else None
    ok = None
    if ld and all(v == v for v in ld.values()):
        ls = sorted(ld.values()); ok = max(abs(a / b - 1) for a, b in zip(ex, ls) if b > 0) if min(ls) > 0 else None
    seen.add(o["model"])
    score = (2 if ld else 0) + (1 if o["brand"] else 0) + (1 if ok is not None and ok < .25 else 0) + (1 if o["color"] else 0) + random.random()
    if ok is not None and ok > .6: score -= 3     # listed dims disagree with model scale
    if int(m["vertices"]) > 400000: score -= 2
    o.update(category=cat, extent=[float(m["extent_x"]), float(m["extent_y"]), float(m["extent_z"])], listed_m=ld, dim_err=ok, score=score, mpath=m["path"], verts=int(m["vertices"]))
    by[cat].append(o)
print("available (unique model):", {k: len(v) for k, v in sorted(by.items())})
T = {"floor_lamp": 40, "table_lamp": 40, "mirror": 35, "desk_chair": 40, "bookcase": 35, "desk": 35, "armchair": 40, "bed": 15, "sofa": 20, "coffee_table": 15, "side_table": 15,
     "dining_table": 10, "dining_chair": 15, "wardrobe": 6, "dresser": 10, "nightstand": 10, "rug": 8, "tv_bench": 8, "plant_pot": 8, "bar_stool": 8, "other": 5}
sel = []; short = 0
for c, t in T.items():
    L = sorted(by.get(c, []), key=lambda o: -o["score"]); take = L[:t]; short += t - len(take)
    for i, o in enumerate(L[:int(t * 1.6) + 3]): o["rank"] = i; o["spare"] = i >= t; sel.append(o)
json.dump(sel, open(H / "raw/selected.json", "w"))
print("targets:", sum(T.values()), "shortfall:", short); print("selected counts:", collections.Counter(o["category"] for o in sel if not o["spare"]))
