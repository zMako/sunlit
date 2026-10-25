"""Fill missing prices from the DWR index (raw/dwr_index.json): for items with price_usd None, match (brand, name) -> DWR product; sets price_usd, price_source 'DWR USD (from price)', buy_url = DWR url.
Rerunnable. Runs over raw/items_*.json in place."""
import json, glob, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dwr_index import lookup
H = pathlib.Path(__file__).resolve().parent; n = 0; tot = 0
for f in sorted(glob.glob(str(H / "raw/items_*.json"))):
    its = json.load(open(f)); ch = 0
    for i in its:
        tot += 1
        if i.get("price_usd") is not None: continue
        nm = i["name"]
        m = lookup(i["brand"], nm) or (lookup(i["brand"], f"{i.get('collection','')} {nm}") if i.get("collection") else None)
        if m and m.get("price_usd"):
            i.update(price_usd=m["price_usd"], price_currency="USD", price_orig=m["price_usd"], price_source="DWR USD (lowest variant)", buy_url=m["url"].split("?")[0]); ch += 1
    if ch: json.dump(its, open(f, "w"), indent=1)
    n += ch; print(pathlib.Path(f).name, ch)
# never keep a constant: same DWR price on >=4 differently named items of one brand is a bad match -> clear those DWR-filled prices
import collections
for f in sorted(glob.glob(str(H / "raw/items_*.json"))):
    its = json.load(open(f)); c = collections.Counter(i["price_usd"] for i in its if str(i.get("price_source", "")).startswith("DWR"))
    bad = {k for k, v in c.items() if v >= 4}
    for i in its:
        if str(i.get("price_source", "")).startswith("DWR") and i["price_usd"] in bad: i.update(price_usd=None, price_source=None, price_orig=None, price_currency=None)
    json.dump(its, open(f, "w"), indent=1)
print("filled", n, "of", tot)
