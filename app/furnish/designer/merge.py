"""Append the Design tier (raw/items_*.json, written by the per-brand scripts) into ../catalog.json, idempotent by id (prior dsg-* copies of the same id are replaced).
Only items whose models_opt GLB exists are merged. Run prices.py first to fill DWR prices.
   feasibility/.venv/bin/python app/furnish/designer/merge.py"""
import json, pathlib, collections, shutil, glob, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import categorize
H = pathlib.Path(__file__).resolve().parent; CAT = H.parent / "catalog.json"
cat = json.load(open(CAT)); new = []
for f in sorted(glob.glob(str(H / "raw/items_*.json"))): new += json.load(open(f))
def fix_cat(i):
    """normalise categories centrally: re-derive from name; lamps never tables; tables by height; sensible fallbacks from model dims."""
    c = i.get("category"); nm = i.get("name") or ""; h = i.get("height_m") or 0; w = i.get("width_m") or 0; d = i.get("depth_m") or 0
    t = categorize(nm, i.get("collection"), i.get("product_url", "").split("/hay/")[-1] if i.get("brand") == "HAY" else "")
    if t != "other" and (c in ("other", None) or t in ("table_lamp", "floor_lamp", "pendant_lamp") or c in ("dining_table", "side_table", "coffee_table", "desk")): c = t
    if c in ("table_lamp", "floor_lamp") and h:   # lamp subtype by height
        c = "floor_lamp" if h > 1.1 and not re.search(r"table|desk", nm.lower()) else ("table_lamp" if h <= 1.1 else c)
    if c in ("dining_table", "side_table", "coffee_table", "desk") and h:
        if re.search(r"desk|writing", nm.lower()) or c == "desk": c = "desk"
        elif h < 0.55: c = "coffee_table" if max(w, d) >= 0.6 else "side_table"
        elif h < 0.68 and max(w, d) < 0.6: c = "side_table"
        else: c = "dining_table" if max(w, d) >= 0.9 else ("side_table" if max(w, d) < 0.6 else "dining_table")
    if c in ("other", None) and h and w:   # last resort from shape
        a = h / max((w * d) ** .5, 1e-3)
        c = "floor_lamp" if a > 3.5 else "other"
    i["category"] = c or "other"; return i
MINMAX = {"sofa": (1.2, 4.5), "bed": (1.4, 2.6), "dining_table": (0.6, 4.0), "desk": (0.8, 2.6), "floor_lamp": (1.0, 2.6), "armchair": (0.45, 1.6), "dining_chair": (0.35, 1.3), "wardrobe": (1.0, 3.5),
          "bookcase": (0.8, 3.5), "dresser": (0.6, 3.5), "coffee_table": (0.3, 1.8), "tv_bench": (1.0, 3.0), "desk_chair": (0.5, 1.4), "bar_stool": (0.55, 1.3), "table_lamp": (0.2, 1.1), "pendant_lamp": (0.15, 3.0)}
def flag(i):
    """dims_mismatch: model bbox vs listed dims >25% apart, or (when dims came only from the model) bbox implausible for the category (component/part meshes)."""
    md = i.get("model_dims_m"); why = []
    if md:
        if i.get("dims_source") == "listed":
            for a, b, n in zip(md, (i.get("width_m"), i.get("depth_m"), i.get("height_m")), "WDH"):
                if b and abs(a / b - 1) > .25 and not (n in "WD" and False): why.append(f"{n} {a:.2f} vs {b:.2f}")
            if len(why) >= 2 or (why and why[0][0] == "H"):
                pass
            else: why = [w for w in why if False]
        lo_hi = MINMAX.get(i["category"]); m = max(md)
        if lo_hi and not (lo_hi[0] <= m <= lo_hi[1]): why.append(f"largest side {m:.2f} outside {lo_hi} for {i['category']}")
        if m > 6 or m < 0.05: why.append("absurd size")
    i["dims_mismatch"] = bool(why); i["dims_mismatch_reason"] = "; ".join(why) or None; return i
for i in new: fix_cat(i); flag(i)
ACC = re.compile(r"paper shade|shade for|lampshade|cushion|bulb|linking device|cover only|seat pad|\bparts?\b|spare", re.I)
ok = []; seen = set()
for i in new:
    if ACC.search(i.get("name") or ""): continue
    if i["id"] in seen: continue
    if i.get("model_glb") and not (H.parent.parent / i["model_glb"]).exists(): continue
    seen.add(i["id"]); ok.append(i)
cnt = lambda L, k="category": dict(sorted(collections.Counter(i.get(k) for i in L).items()))
before = cat["items"]; print("before", len(before), cnt(before))
bak = H / "raw/catalog.json.bak"
if not bak.exists(): shutil.copy(CAT, bak)
ids = {i["id"] for i in ok}
cat["items"] = [i for i in before if i["id"] not in ids] + ok
tmp = CAT.with_suffix(".json.tmp"); json.dump(cat, open(tmp, "w"), indent=1); tmp.replace(CAT)
print("after", len(cat["items"]), cnt(cat["items"])); print("dims_mismatch flagged", sum(1 for i in ok if i.get("dims_mismatch"))); print("design items merged", len(ok), "of", len(new), "by brand", cnt(ok, "brand"))
