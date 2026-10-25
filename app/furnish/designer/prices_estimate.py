"""Estimate prices for designer (dsg-*) catalogue items that have no shop price. Offline, deterministic, idempotent.
Convention (identical to Amazon items, which checkout/order.html + agent/plan expect): price_usd = the estimate, price_source = "estimated"
(checkout sums those into estimated_usd and labels them "estimate"). Extra fields: estimated_usd (same value), price_estimate_method
(est:brand_category_median | est:category_median_x_brand | est:category_median | est:global_designer_median), price_estimate_note.
Real prices are never touched; previous estimates are recomputed from scratch each run.
   feasibility/.venv/bin/python app/furnish/designer/prices_estimate.py"""
import json, pathlib, shutil, statistics as st, math, collections, sys
H = pathlib.Path(__file__).resolve().parent; CAT = H.parent / "catalog.json"
WIDTH_CATS = {"sofa", "dining_table", "coffee_table", "desk", "bench", "bookcase", "bed", "dresser", "side_table", "wardrobe", "rug", "ottoman"}
MINN = 3

def _is_est(i): return i.get("price_source") == "estimated" and i["id"].startswith("dsg-")
def _real(i): return i["id"].startswith("dsg-") and i.get("price_usd") and not _is_est(i)
def _q(v, p):
    v = sorted(v); k = (len(v) - 1) * p; f = int(k); return v[f] + (v[min(f + 1, len(v) - 1)] - v[f]) * (k - f)

def _slope(items):
    """within-brand log-log slope of price vs width (brand fixed effects), clipped to [0,1.2]; None if not enough data."""
    g = collections.defaultdict(list)
    for i in items:
        if i.get("width_m") and i["width_m"] < 5: g[i["brand"]].append((math.log(i["width_m"]), math.log(i["price_usd"])))
    sxy = sxx = syy = 0; n = 0
    for pts in g.values():
        if len(pts) < 2: continue
        mx = sum(p[0] for p in pts) / len(pts); my = sum(p[1] for p in pts) / len(pts)
        for x, y in pts: sxy += (x - mx) * (y - my); sxx += (x - mx) ** 2; syy += (y - my) ** 2; n += 1
    if n < 12 or sxx < 1e-6: return None
    r = sxy / math.sqrt(sxx * syy) if syy > 0 else 0
    return None if r < 0.25 else max(0.0, min(1.2, sxy / sxx))

def _round(p): return round(p / 5) * 5 if p >= 100 else round(p)

def estimate(items):
    ds = [i for i in items if i["id"].startswith("dsg-")]
    for i in ds:
        if (i.get("width_m") or 0) > 5: i["width_m_suspect"] = True   # e.g. mm stored as m; ignored for width scaling
        if _is_est(i):
            for k in ("price_usd", "price_source", "estimated_usd", "price_estimate_method", "price_estimate_note"): i.pop(k, None)
            i["price_usd"] = None
    priced = [i for i in ds if _real(i)]
    bycat = collections.defaultdict(list); bybc = collections.defaultdict(list); bybrand = collections.defaultdict(list)
    for i in priced: bycat[i["category"]].append(i); bybc[(i["brand"], i["category"])].append(i); bybrand[i["brand"]].append(i)
    catmed = {c: st.median(x["price_usd"] for x in v) for c, v in bycat.items() if len(v) >= MINN}
    gmed = st.median(x["price_usd"] for x in priced)
    bfac = {}
    for b, v in bybrand.items():
        r = [x["price_usd"] / catmed[x["category"]] for x in v if x["category"] in catmed]
        if len(r) >= MINN: bfac[b] = (max(.3, min(3., st.median(r))), len(r))
    other = collections.defaultdict(list)
    for i in items:
        if not i["id"].startswith("dsg-") and i.get("price_usd") and i.get("price_source") != "estimated": other[i["category"]].append(i["price_usd"])
    ratios = [catmed[c] / st.median(other[c]) for c in catmed if len(other.get(c, [])) >= 10]
    prem = max(1., min(5., st.median(ratios))) if ratios else 2.
    slope = {c: _slope(v) for c, v in bycat.items() if c in WIDTH_CATS}
    out = []
    for i in ds:
        if i.get("price_usd") or _is_est(i): continue
        c, b, w = i["category"], i["brand"], i.get("width_m")
        if (w or 0) >= 5: w = None
        s = slope.get(c); ref = None
        if (b, c) in bybc and len(bybc[(b, c)]) >= MINN:
            v = bybc[(b, c)]; base = st.median(x["price_usd"] for x in v); m = "est:brand_category_median"; n = len(v)
            ref = st.median(x["width_m"] for x in v if (x.get("width_m") if (x.get("width_m") or 0) < 5 else None)) if any((x.get("width_m") if (x.get("width_m") or 0) < 5 else None) for x in v) else None
            note = f"median of {n} priced {b} {c} items"
        elif c in catmed and b in bfac:
            v = bycat[c]; base = catmed[c] * bfac[b][0]; m = "est:category_median_x_brand"
            ref = st.median(x["width_m"] for x in v if (x.get("width_m") if (x.get("width_m") or 0) < 5 else None))
            note = f"median of {len(v)} priced designer {c} items x brand factor {bfac[b][0]:.2f} ({b}, {bfac[b][1]} items)"
        elif c in catmed:
            v = bycat[c]; base = catmed[c]; m = "est:category_median"; ref = st.median(x["width_m"] for x in v if (x.get("width_m") if (x.get("width_m") or 0) < 5 else None))
            note = f"median of {len(v)} priced designer {c} items"
        elif len(other.get(c, [])) >= 10:
            base = st.median(other[c]) * prem; m = "est:nondesigner_category_median_x_premium"; s = None
            note = f"median of {len(other[c])} priced non-designer {c} items x designer premium {prem:.2f}"
        else:
            base = gmed * (bfac[b][0] if b in bfac else 1); m = "est:global_designer_median"; s = None
            note = f"no priced {c} items; global designer median of {len(priced)} items" + (f" x brand factor {bfac[b][0]:.2f}" if b in bfac else "")
        p = base
        if s and w and ref: f = max(.4, min(2.5, w / ref)); p = base * f ** s; note += f"; width-scaled ^{s:.2f}"
        if c in catmed:
            vals = [x["price_usd"] for x in bycat[c]]; lo, hi = (_q(vals, .1), _q(vals, .9)) if len(vals) >= 5 else (catmed[c],) * 2
            p = max(.3 * lo, min(3 * hi, p))
        p = float(_round(p)); i["price_usd"] = p; i["estimated_usd"] = p; i["price_source"] = "estimated"; i["price_estimate_method"] = m; i["price_estimate_note"] = note
        i["price_currency"] = "USD"; out.append(i)
    return out, catmed, slope

def run(cat_path=CAT, report=True):
    cat = json.load(open(cat_path)); items = cat["items"]
    bak = cat_path.with_name(cat_path.name + ".bak_prices")
    if not bak.exists(): shutil.copy(cat_path, bak)
    est, catmed, slope = estimate(items)
    tmp = cat_path.with_suffix(".json.tmp"); json.dump(cat, open(tmp, "w"), indent=1); tmp.replace(cat_path)
    if report:
        ds = [i for i in items if i["id"].startswith("dsg-")]
        print(f"{'category':14s} {'priced':>6s} {'estimated':>9s} {'median est':>10s} {'slope':>6s}")
        cats = sorted({i["category"] for i in ds})
        for c in cats:
            npri = sum(1 for i in ds if i["category"] == c and _real(i)); e = [i["price_usd"] for i in est if i["category"] == c]
            print(f"{c:14s} {npri:6d} {len(e):9d} {(st.median(e) if e else 0):10.0f} {slope.get(c) if slope.get(c) is not None else '-':>6}" if not slope.get(c) else f"{c:14s} {npri:6d} {len(e):9d} {st.median(e) if e else 0:10.0f} {slope[c]:6.2f}")
        print("methods:", dict(collections.Counter(i["price_estimate_method"] for i in est)), "total estimated", len(est))
        import random; random.Random(7).shuffle(est)
        print("\nspot checks (name | brand | category | width | estimate | method)")
        for i in est[:15]: print(f"  {i['name'][:42]:42s} | {i['brand']:14s} | {i['category']:13s} | {i.get('width_m')} | ${i['price_usd']:.0f} | {i['price_estimate_method'][4:]}")
    return len(est)

if __name__ == "__main__": run()
