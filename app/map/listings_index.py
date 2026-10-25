"""Build app/map/listings.json: one entry per listing for the map front door (app/map/map.html).
Re-runnable. Geocodes RentSFNow addresses once (Google Geocoding through app/spend.py, Nominatim fallback at 1 req/s)
and caches each result in feasibility/listings/<lid>/geo.json; later runs make no network calls.

  feasibility/.venv/bin/python app/map/listings_index.py            # build (geocode what is missing)
  feasibility/.venv/bin/python app/map/listings_index.py --no-geo   # build from caches only

Data caveats handled here:
- RentSFNow addresses are written as "<street> #<unit>, San Francisco, CA" by the scraper for every listing, but the
  landlord also lists Oakland and Los Angeles units. A listing is placed in SF only if Google resolves the street in
  San Francisco without partial_match AND neither it nor another unit at the same street mentions a non-SF place
  (Oakland, Lake Merritt, Hollywood ...) or carries the promo text used only on the LA/Santa Monica units.
- RentSFNow "neighborhood" is "Alamo Square" on every listing (scraper picks a fixed line): dropped.
- Greystar "body" is the site's contact-form boilerplate: dropped.
"""
import json, pathlib, re, sys, time, os, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).parent.resolve(); APP = HERE.parent; ROOT = APP.parent
LIST = ROOT / "feasibility" / "listings"; LAYOUTS = APP / "plan3d" / "layouts" / "index.json"; OUT = HERE / "listings.json"
sys.path.insert(0, str(APP)); import spend  # noqa: E402

SF_BOX = (37.700, 37.835, -122.53, -122.35)
BAY_BOX = (37.20, 38.05, -122.62, -121.75)   # inner Bay Area: Marin to San Jose, the coast to Dublin   # lat0, lat1, lon0, lon1 (city proper plus a margin)
NON_SF = re.compile(r"\b(Oakland|Lake Merritt|Adams Point|Grand Lake|Piedmont|Berkeley|Los Angeles|Los Feliz|Hollywood|Santa Monica|West Adams|Koreatown|Silver Lake|Culver City|Burbank|Pasadena)\b", re.I)
NON_SF_PROMO = re.compile(r"Bilt reward|free parking for the first 6 months", re.I)   # promos seen only on the LA/Santa Monica units
UA = "MoveIn-CalHacks-demo/1.0 (one-off geocoding of ~100 rental addresses; sunlit project)"

def num(v, f=float):
    try: return None if v in (None, "", "None") else f(v)
    except (TypeError, ValueError): return None

def street_of(addr):   # "1025 Post #5, San Francisco, CA" -> "1025 Post"
    return re.sub(r"\s*#\S+", "", addr.split(",")[0]).strip()

def geocode_google(q):
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key: raise spend.SpendCapExceeded("no GOOGLE_MAPS_API_KEY")
    spend.google_call("google_geocode", 1, note=f"map index geocode {q}")   # checks the cap, then charges (worst-case list price)
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode({"address": q, "components": "country:US", "bounds": "37.70,-122.52|37.81,-122.36", "key": key})
    with urllib.request.urlopen(url, timeout=20) as r: d = json.load(r)
    if d.get("status") != "OK" or not d.get("results"): return {"source": "google", "query": q, "status": d.get("status"), "lat": None, "lon": None}
    res = d["results"][0]; loc = res["geometry"]["location"]
    comp = {t: c["long_name"] for c in res["address_components"] for t in c["types"]}
    return {"source": "google", "query": q, "status": "OK", "lat": loc["lat"], "lon": loc["lng"], "formatted": res.get("formatted_address"),
            "locality": comp.get("locality"), "neighborhood": comp.get("neighborhood"), "partial_match": bool(res.get("partial_match")),
            "location_type": res["geometry"].get("location_type"), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}

def geocode_nominatim(q):
    time.sleep(1.05)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "addressdetails": 1, "limit": 1, "countrycodes": "us"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r: d = json.load(r)
    if not d: return {"source": "nominatim", "query": q, "status": "ZERO_RESULTS", "lat": None, "lon": None}
    a = d[0].get("address", {})
    return {"source": "nominatim", "query": q, "status": "OK", "lat": float(d[0]["lat"]), "lon": float(d[0]["lon"]), "formatted": d[0].get("display_name"),
            "locality": a.get("city") or a.get("town"), "neighborhood": a.get("neighbourhood") or a.get("suburb"), "partial_match": False,
            "location_type": d[0].get("type"), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}

STATS = {"google": 0, "nominatim": 0, "cached": 0}
def geocode(lid, addr, memo, allow_net):
    f = LIST / lid / "geo.json"
    if f.exists(): STATS["cached"] += 1; return json.loads(f.read_text())
    if not allow_net: return None
    q = f"{street_of(addr)}, San Francisco, CA"
    if q not in memo:
        try: memo[q] = geocode_google(q); STATS["google"] += 1
        except spend.SpendCapExceeded as e:
            print(f"[geo] ledger refused Google ({e}); Nominatim for {q}"); memo[q] = geocode_nominatim(q); STATS["nominatim"] += 1
    g = dict(memo[q]); f.write_text(json.dumps(g, indent=1)); return g

def in_sf(g):
    if not g or g.get("lat") is None: return False
    lat0, lat1, lon0, lon1 = SF_BOX
    q = street_of(g.get("query", "")).lower(); fmt = (g.get("formatted") or "").lower()
    # partial_match is set for "1035 Sutter" -> "1035 Sutter St": fine when the house number and street name match a rooftop
    street_ok = not g.get("partial_match") or (g.get("location_type") == "ROOFTOP" and fmt.startswith(q))
    return (g.get("locality") == "San Francisco" and street_ok and g.get("location_type") in ("ROOFTOP", "RANGE_INTERPOLATED")
            and lat0 <= g["lat"] <= lat1 and lon0 <= g["lon"] <= lon1)

PLAN_SOURCES = ("gs-", "udr-", "avb-")   # building-level listings with floor plans and coordinates in meta (Greystar, UDR, AvalonBay)
def annotated(u):
    if u.get("annotated") is not None: return bool(u["annotated"])
    return bool(u.get("materials") or u.get("issues") or any(r.get("type") and r["type"] != "other" for r in u["rooms"]))

def size_source(u):
    s0 = (u.get("scale_from") or [""])[0]
    if s0.startswith("reader_dims+printed"): return "plan dimensions printed"
    if s0.startswith("annotation_dims") or "annotation_dims" in (u.get("scale_from") or []): return "Claude size estimates"
    if "listing sqft" in s0: return "listed sqft (true size)"
    if "printed" in s0: return "printed sqft"
    if s0.startswith("area:prior"): return "prior size (typical unit)"
    return s0 or None

def unit_entry(u, fp):
    rooms = [{"id": r["id"], "name": r["name"], "type": r.get("type"), "area_m2": r["area_m2"]} for r in u["rooms"]]
    living = next((r["id"] for r in rooms if r["type"] == "living"), None) or (max(rooms, key=lambda r: r["area_m2"])["id"] if rooms else "r0")
    furnished = [f"{u['unit']}__{r['id']}" for r in rooms if (APP / "furnish" / "plans" / f"{u['unit']}__{r['id']}.json").exists()]
    return {"unit": u["unit"], "plan_name": u.get("plan_name") or (fp or {}).get("name"), "plan_image": u["plan_image"],
            "beds": (fp or {}).get("bedrooms"), "baths": (fp or {}).get("bathrooms"), "sqft_listed": num((fp or {}).get("sqft"), int),
            "area_m2": u["area_m2"], "sqft_model": round(u["area_m2"] * 10.7639) if u.get("area_m2") else None,
            "size_typical": (u.get("scale_from") or [""])[0].startswith("area:prior") and "annotation_dims" not in (u.get("scale_from") or []),
            "n_rooms": len([r for r in rooms if r["area_m2"] > 2]), "rooms": rooms, "agent_room": living,
            "annotated": annotated(u), "materials": bool(u.get("materials")), "n_fixtures": u.get("n_fixtures", 0),
            "scale_from": (u.get("scale_from") or [None])[0], "size_source": size_source(u), "n_issues": len(u.get("issues") or []),
            "furnished_rooms": furnished}

def photos_of(d):
    return [f"/listings/{d.name}/{p.name}" for p in sorted(d.glob("[0-9][0-9].jpg"))]

def main():
    allow_net = "--no-geo" not in sys.argv
    layouts = json.loads(LAYOUTS.read_text()) if LAYOUTS.exists() else []
    by_listing = {}
    for u in layouts: by_listing.setdefault(u["listing"], []).append(u)
    metas = {d.name: json.loads((d / "meta.json").read_text()) for d in sorted(LIST.iterdir()) if (d / "meta.json").exists()}
    # non-SF clues are shared by every unit at the same street address
    clue = {}
    for lid, m in metas.items():
        if not lid.startswith("rsn-"): continue
        s = street_of(m.get("address", "")).lower(); txt = f"{m.get('title', '')} {m.get('body', '')}"
        hit = NON_SF.search(txt) or NON_SF_PROMO.search(txt)
        if hit: clue.setdefault(s, hit.group(0))
    memo, out, missing = {}, [], {"no_photos": [], "no_plans_gs": [], "no_coords": [], "outside_sf": []}
    for lid, m in metas.items():
        d = LIST / lid; photos = photos_of(d); gs = lid.startswith(PLAN_SOURCES)
        e = {"id": lid, "source": m.get("source"), "url": m.get("url"), "title": m.get("title") or lid,
             "address": (m.get("address") or "").replace("&apos;", "'"), "photos": photos[:12], "n_photos": len(photos)}
        if gs:
            e["building"] = m.get("title"); e["lat"], e["lon"] = num(m.get("lat")), num(m.get("lon")); e["geo_source"] = "listing"
            body = m.get("body") or ""; e["body"] = None if body.startswith("Please use the form below") else body[:2500]
            units = {u["unit"]: u for u in by_listing.get(lid, [])}; plans, unit_list = [], []
            for fp in m.get("floorplans") or []:
                stem = pathlib.Path(fp["file"]).stem; uid = f"{lid}_{stem}"
                if not (d / fp["file"]).exists(): continue
                plans.append({"src": f"/listings/{lid}/{fp['file']}", "name": fp.get("name"), "beds": fp.get("bedrooms"), "baths": fp.get("bathrooms"),
                              "sqft": num(fp.get("sqft"), int), "unit": uid if uid in units else None, "units_available": fp.get("units_available")})
                if uid in units: unit_list.append(unit_entry(units[uid], fp))
            for uid, u in units.items():   # units whose plan is not in meta.floorplans
                if not any(x["unit"] == uid for x in unit_list): unit_list.append(unit_entry(u, None))
            e["plans"], e["units"] = plans, unit_list
            beds = [p["beds"] for p in plans if p["beds"] is not None]; baths = [p["baths"] for p in plans if p["baths"] is not None]
            sq = [p["sqft"] for p in plans if p["sqft"]] or [x["sqft_model"] for x in unit_list if x["sqft_model"] and not x["size_typical"]]   # typical (prior) sizes are not measurements
            e["beds_min"], e["beds_max"] = (min(beds), max(beds)) if beds else (None, None)
            e["baths_min"], e["baths_max"] = (min(baths), max(baths)) if baths else (None, None)
            e["sqft_min"], e["sqft_max"] = (min(sq), max(sq)) if sq else (None, None)
            e["sqft_from"] = "listing" if any(p["sqft"] for p in plans) else ("3D model" if sq else None)
            rents = [num(fp.get("rent_min")) for fp in m.get("floorplans") or [] if num(fp.get("rent_min"))]
            e["price"] = int(min(rents)) if rents else None; e["price_note"] = "from, cheapest listed unit" if rents else "pricing on request"
            e["city"] = m.get("city")
            lat0, lat1, lon0, lon1 = SF_BOX
            e["in_sf"] = e["lat"] is not None and lat0 <= e["lat"] <= lat1 and lon0 <= e["lon"] <= lon1 and "South San Francisco" not in e["address"]
            e["in_area"] = e["lat"] is not None and BAY_BOX[0] <= e["lat"] <= BAY_BOX[1] and BAY_BOX[2] <= e["lon"] <= BAY_BOX[3]   # SF plus the inner Bay Area (Greystar/UDR plan sources)
            if not plans: missing["no_plans_gs"].append(lid)
            if not photos and plans: e["cover"] = plans[0]["src"]   # plan-only sources (UDR, AvalonBay): the first plan is the card image
        else:
            g = geocode(lid, m.get("address", ""), memo, allow_net) if m.get("address") else None
            e["lat"], e["lon"] = (g or {}).get("lat"), (g or {}).get("lon"); e["geo_source"] = (g or {}).get("source")
            e["geo"] = {k: (g or {}).get(k) for k in ("formatted", "partial_match", "location_type", "neighborhood")}
            c = clue.get(street_of(m.get("address", "")).lower())
            e["in_sf"] = in_sf(g) and not c; e["in_area"] = e["in_sf"]   # RentSFNow: SF only (its addresses are unreliable outside SF)
            if not e["in_sf"]: e["outside_reason"] = f"text mentions '{c}'" if c else ("geocode not in SF: " + str((g or {}).get("formatted") or (g or {}).get("status")))
            e["neighborhood"] = (g or {}).get("neighborhood") if e["in_sf"] else None
            e["body"] = (m.get("body") or "")[:2500] or None; e["plans"], e["units"] = [], []
            bd, ba, sq = num(m.get("bedrooms"), int), num(m.get("bathrooms")), num(m.get("sqft_total"), int)
            e["beds_min"] = e["beds_max"] = bd; e["baths_min"] = e["baths_max"] = ba; e["sqft_min"] = e["sqft_max"] = sq; e["sqft_from"] = "listing" if sq else None
            e["price"] = num(m.get("price_usd"), int); e["price_note"] = None if e["price"] else "pricing on request"
        e["can_rebuild"] = bool(e["units"]); e["has_plan"] = bool(e["plans"])
        if not photos: missing["no_photos"].append(lid)
        if e["lat"] is None: missing["no_coords"].append(lid)
        if not e["in_sf"]: missing["outside_sf"].append(lid)
        out.append(e)
    doc = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(out), "n_in_sf": sum(e["in_sf"] for e in out), "n_in_area": sum(e.get("in_area", False) for e in out),
           "n_units_3d": sum(len(e["units"]) for e in out), "missing": missing, "listings": out}
    OUT.write_text(json.dumps(doc, separators=(",", ":")))
    print(f"[index] {len(out)} listings ({doc['n_in_sf']} in SF), {doc['n_units_3d']} 3D units -> {OUT}")
    print(f"[index] geocode calls: google {STATS['google']}, nominatim {STATS['nominatim']}, cached {STATS['cached']}; ledger google ${spend.status()['usd']['google']:.3f}")
    for k, v in missing.items(): print(f"[index] {k}: {len(v)} {v[:40]}")
    for e in out:
        if not e["in_sf"] and e["id"].startswith("rsn-"): print(f"   outside SF: {e['id']}: {e.get('outside_reason')}")

if __name__ == "__main__": main()
