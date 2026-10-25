"""Step 5: append catalog_abo.json items into ../catalog.json (idempotent by id; replaces existing abo-* entries). Prints per-category counts before/after.
   feasibility/.venv/bin/python app/furnish/abo/merge.py"""
import json, pathlib, collections, shutil
H = pathlib.Path(__file__).resolve().parent; CAT = H.parent / "catalog.json"
cat = json.load(open(CAT)); abo = json.load(open(H / "catalog_abo.json"))["items"]
cnt = lambda L: dict(sorted(collections.Counter(i.get("category") for i in L).items()))
before = cat["items"]; print("before", len(before), cnt(before))
bak = H / "raw/catalog.json.bak"
if not bak.exists(): shutil.copy(CAT, bak)
new = {i["id"]: i for i in abo}
kept = [i for i in before if i["id"] not in new]       # drop prior copies, then append (idempotent)
cat["items"] = kept + abo
tmp = CAT.with_suffix(".json.tmp"); json.dump(cat, open(tmp, "w"), indent=1); tmp.replace(CAT)
print("after", len(cat["items"]), cnt(cat["items"])); print("added/refreshed", len(abo))
