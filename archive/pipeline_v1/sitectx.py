"""Phase 4 site context for a listing: geocode (via local proxy, counted), SF footprints with LiDAR heights,
OSM street centrelines (free), the building, its street-facing facades with compass bearings, and the floor."""
import sys, json, math, re, pathlib, requests
ROOT = pathlib.Path(__file__).resolve().parents[1]; PROXY = "http://127.0.0.1:8765"
UA = {"User-Agent": "sunlit-hackathon/0.1"}

def geocode(address):
    r = requests.get(f"{PROXY}/gapi/geocode", params={"address": address}, timeout=30); r.raise_for_status(); d = r.json()
    if d.get("status") != "OK": raise RuntimeError(f"geocode {d.get('status')}")
    g = d["results"][0]; loc = g["geometry"]["location"]
    return {"lat": loc["lat"], "lon": loc["lng"], "formatted": g["formatted_address"], "location_type": g["geometry"]["location_type"], "cached": r.headers.get("X-Sunlit-Cache")}

def enu_factory(lat, lon):
    mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(lat)); mlon = 111412.84 * math.cos(math.radians(lat)) - 93.5 * math.cos(3 * math.radians(lat))
    return lambda p: [(p[0] - lon) * mlon, (p[1] - lat) * mlat]

def footprints(lat, lon, radius=180):
    url = ("https://data.sfgov.org/resource/ynuv-fyni.json?$select=sf16_bldgid,hgt_mediancm,hgt_maxcm,gnd_mediancm,shape"
           f"&$where=within_circle(shape,{lat},{lon},{radius})&$limit=2000")
    rows = requests.get(url, timeout=60).json(); enu = enu_factory(lat, lon)
    gnds = sorted(float(r["gnd_mediancm"]) / 100 for r in rows if r.get("gnd_mediancm")); gnd0 = gnds[len(gnds) // 2] if gnds else 0.0
    out = []
    for r in rows:
        g = r["shape"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        h = float(r.get("hgt_mediancm") or r.get("hgt_maxcm") or 300) / 100; hmax = float(r.get("hgt_maxcm") or 0) / 100
        gnd = float(r["gnd_mediancm"]) / 100 - gnd0 if r.get("gnd_mediancm") else 0.0
        for poly in polys: out.append({"id": r["sf16_bldgid"], "ring": [[round(v, 2) for v in enu(p)] for p in poly[0]], "height": round(h, 2), "height_max": round(hmax, 2), "ground": round(gnd, 2)})
    return out, gnd0

MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://lz4.overpass-api.de/api/interpreter", "https://z.overpass-api.de/api/interpreter"]
def streets(lat, lon, radius=120):
    import time, hashlib
    cache = ROOT / "cache" / ("osm_" + hashlib.sha1(f"{lat:.5f},{lon:.5f},{radius}".encode()).hexdigest() + ".json")
    if cache.exists(): data = json.load(open(cache))
    else:
        data = None
        # 1) SF city street centrelines (free, reliable, SF only)
        try:
            r = requests.get("https://data.sf.gov/resource/3psu-pn9h.json", params={"$select": "streetname,line", "$where": f"within_circle(line,{lat},{lon},{radius})", "$limit": 500}, timeout=30)
            if r.ok and r.json():
                data = {"elements": [{"type": "way", "tags": {"name": row["streetname"].title().replace(" Aly", " Alley").replace(" St", " Street").replace(" Ave", " Avenue")}, "geometry": [{"lon": c[0], "lat": c[1]} for c in row["line"]["coordinates"]]} for row in r.json() if row.get("line")]}
        except requests.RequestException: data = None
        q = f'[out:json][timeout:25];way(around:{radius},{lat},{lon})["highway"]["name"];out geom;'
        for attempt in range(6 if data is None else 0):
            url = MIRRORS[attempt % len(MIRRORS)]
            try:
                r = requests.post(url, data={"data": q}, headers=UA, timeout=60)
                if r.ok: data = r.json(); break
            except requests.RequestException: pass
            time.sleep(3)
        if data is None: raise RuntimeError("Overpass unavailable on all mirrors")
        json.dump(data, open(cache, "w"))
    enu = enu_factory(lat, lon); out = []
    for w in data.get("elements", []):
        if w.get("type") != "way": continue
        out.append({"name": w["tags"].get("name"), "pts": [enu((p["lon"], p["lat"])) for p in w.get("geometry", [])]})
    return out

def point_in_poly(p, ring):
    x, y = p; inside = False
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1: inside = not inside
    return inside

def seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p; dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2)); qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)

def polyline_dist(p, pts): return min(seg_dist(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1)) if len(pts) > 1 else 1e9

def choose_building(bld, p=(0.0, 0.0)):
    inside = [b for b in bld if point_in_poly(p, b["ring"])]
    if inside: return max(inside, key=lambda b: b["height"])
    return min(bld, key=lambda b: min(seg_dist(p, b["ring"][i], b["ring"][i + 1]) for i in range(len(b["ring"]) - 1)))

def facades(b, sts, street_name=None, others=None):
    """Group footprint edges into the building's four sides (principal axis +- 90), so bays made of short edges count as
    one facade. Each side: bearing of outward normal, extreme line position, span, number of bay segments, nearest street."""
    ring = b["ring"][:-1]; n = len(ring); cx = sum(p[0] for p in ring) / n; cy = sum(p[1] for p in ring) / n
    # principal direction = longest edge
    L = [(math.hypot(ring[(i + 1) % n][0] - ring[i][0], ring[(i + 1) % n][1] - ring[i][1]), i) for i in range(n)]; _, i0 = max(L)
    a, c = ring[i0], ring[(i0 + 1) % n]; th = math.atan2(c[0] - a[0], c[1] - a[1])  # bearing of the long edge direction
    sides = []
    for k in range(4):
        nb = (math.degrees(th) + 90 * k) % 360; nx, ny = math.sin(math.radians(nb)), math.cos(math.radians(nb))   # side outward normal (compass)
        tx, ty = -ny, nx  # along-side direction
        members = []; total = 0.0
        for i in range(n):
            p, q = ring[i], ring[(i + 1) % n]; ex, ey = q[0] - p[0], q[1] - p[1]; el = math.hypot(ex, ey)
            if el < 0.5: continue
            ox, oy = ey / el, -ex / el; mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            if (mid[0] - cx) * ox + (mid[1] - cy) * oy < 0: ox, oy = -ox, -oy
            if ox * nx + oy * ny > math.cos(math.radians(35)): members.append(i); total += el
        if not members: continue
        pts = [ring[i] for i in members] + [ring[(i + 1) % n] for i in members]
        off = max((p[0] - cx) * nx + (p[1] - cy) * ny for p in pts)     # extreme outward offset of this side
        ts = [(p[0] - cx) * tx + (p[1] - cy) * ty for p in pts]; t0, t1 = min(ts), max(ts)
        A = [cx + nx * off + tx * t0, cy + ny * off + ty * t0]; B = [cx + nx * off + tx * t1, cy + ny * off + ty * t1]
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2); probe = (mid[0] + nx * 8, mid[1] + ny * 8)
        near = (mid[0] + nx * 2.5, mid[1] + ny * 2.5)
        party = any(point_in_poly(near, o["ring"]) for o in (others or []) if o["id"] != b["id"])
        best = None
        for s_ in sts:
            d = polyline_dist(probe, s_["pts"])
            if best is None or d < best[0]: best = (d, s_["name"])
        sides.append({"edge": k, "a": [round(A[0], 2), round(A[1], 2)], "b": [round(B[0], 2), round(B[1], 2)], "len": round(t1 - t0, 2), "bearing": round(nb, 1),
                      "n_segments": len(members), "bays": int(sum(1 for i in members if L[i][0] < 2.5) > 2), "street": best[1] if best else None, "street_dist_m": round(best[0], 1) if best else None, "party_wall": party})
    # candidates: every side that is not a party wall (front, back, lightwell); street-facing ones first
    sf = [f for f in sides if not f["party_wall"]]
    for f in sf: f["street_facing"] = bool(f["street_dist_m"] is not None and f["street_dist_m"] < 35)
    for f in sf: f["is_address_street"] = bool(street_name and f["street"] and street_name.lower().split()[0] in f["street"].lower())
    sf.sort(key=lambda f: (not f.get("is_address_street"), not f["street_facing"], f["street_dist_m"] or 1e9))
    return sides, sf

def parse_floor(title):
    m = re.search(r"#\s*(\d{3,4})\b", title)
    if m: n = int(m.group(1)); return (n // 100) if n >= 100 else None
    m = re.search(r"\b(\d+)(st|nd|rd|th)\s+floor", title, re.I)
    if m: return int(m.group(1))
    if re.search(r"penthouse|top floor", title, re.I): return "top"
    if re.search(r"ground floor|garden", title, re.I): return 1
    return None

def build_site(listing_dir, out_dir):
    meta = json.load(open(pathlib.Path(listing_dir) / "meta.json")); title = meta["title"]; addr = meta.get("address") or ""
    address = f"{addr}, San Francisco, CA" if addr else title
    g = geocode(address); lat, lon = g["lat"], g["lon"]
    bld, gnd0 = footprints(lat, lon); sts = streets(lat, lon); b = choose_building(bld)
    street_name = addr.split(",")[0]; street_name = re.sub(r"^\d+\s+", "", street_name)
    all_f, sf = facades(b, sts, street_name, others=bld)
    floor = parse_floor(title); storeys = max(1, round(b["height"] / 3.0))
    if floor == "top": floor = storeys
    terrain = terrain_grid(bld); horizon = horizon_profile(lat, lon, gnd0)
    site = {"terrain": terrain, "horizon": horizon, "listing": meta, "address": address, "geocode": g, "lat": lat, "lon": lon, "ground0_m": gnd0, "building": b, "n_buildings": len(bld),
            "storeys_est": storeys, "floor": floor, "facades_all": all_f, "facades_street": sf, "streets": [s["name"] for s in sts if s["name"]],
            "buildings": bld}
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True); json.dump(site, open(out / "site.json", "w"))
    print(f"[site] {address} -> {g['formatted']} ({g['location_type']}, cache {g['cached']}) | building h {b['height']} m ~{storeys} storeys, floor {floor} | "
          f"{len(bld)} footprints | horizon max {max(horizon['horizon_deg'].values()):.1f}° | street facades: " + "; ".join(f"edge {f['edge']} {f['len']} m bearing {f['bearing']}° -> {f['street']} ({f['street_dist_m']} m)" for f in sf))
    return site


def plan_image(site, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 9)); ax.set_facecolor("#111")
    for b in site["buildings"]:
        r = b["ring"]; ax.fill([p[0] for p in r], [p[1] for p in r], color=(0.5, 0.5, 0.55), alpha=0.6, lw=0.3, ec="k")
    r = site["building"]["ring"]; ax.fill([p[0] for p in r], [p[1] for p in r], color="orange", alpha=0.9)
    for f in site["facades_street"]:
        a, b = f["a"], f["b"]; ax.plot([a[0], b[0]], [a[1], b[1]], "c-", lw=4); mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ax.annotate(f"e{f['edge']} {f['bearing']}° {f['street']}", mid, color="cyan", fontsize=8)
    ax.scatter([0], [0], c="red", marker="*", s=200, zorder=5, label="geocode")
    ax.set_xlim(-120, 120); ax.set_ylim(-120, 120); ax.set_aspect("equal"); ax.set_title(site["address"] + f"  floor {site['floor']}  h {site['building']['height']} m"); ax.legend()
    plt.tight_layout(); plt.savefig(path, dpi=80); plt.close()


def terrain_grid(bld, half=220.0, cell=5.0, power=2.0):
    """IDW heightfield over building centroid ground heights (relative to block median). Returns dict with heights (nz, nx)."""
    import numpy as np
    pts = np.array([[sum(p[0] for p in b["ring"][:-1]) / (len(b["ring"]) - 1), sum(p[1] for p in b["ring"][:-1]) / (len(b["ring"]) - 1), b["ground"]] for b in bld])
    xs = np.arange(-half, half + cell, cell); zs = np.arange(-half, half + cell, cell); X, Z = np.meshgrid(xs, zs)
    d2 = (X[..., None] - pts[None, None, :, 0]) ** 2 + (Z[..., None] - pts[None, None, :, 1]) ** 2
    w = 1.0 / np.maximum(d2, 4.0) ** (power / 2); H = (w * pts[None, None, :, 2]).sum(-1) / w.sum(-1)
    return {"x0": float(xs[0]), "n0": float(zs[0]), "cell": cell, "nx": len(xs), "nn": len(zs), "heights": np.round(H, 2).tolist()}

def horizon_profile(lat, lon, site_elev_m, az_step=5, dists=(250, 500, 1000, 2000, 4000, 8000)):
    """Terrain horizon elevation angle per azimuth from Open-Meteo's free elevation API (cached). Angle relative to site ground."""
    import hashlib, numpy as np
    cache = ROOT / "cache" / ("horizon_" + hashlib.sha1(f"{lat:.5f},{lon:.5f},{az_step},{dists}".encode()).hexdigest() + ".json")
    if cache.exists(): return json.load(open(cache))
    mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(lat)); mlon = 111412.84 * math.cos(math.radians(lat))
    azs = list(range(0, 360, az_step)); samples = [(az, d) for az in azs for d in dists]
    lats = [lat + d * math.cos(math.radians(az)) / mlat for az, d in samples]; lons = [lon + d * math.sin(math.radians(az)) / mlon for az, d in samples]
    import time
    def get(la, lo):
        for attempt in range(6):
            r = requests.get("https://api.open-meteo.com/v1/elevation", params={"latitude": ",".join(f"{v:.5f}" for v in la), "longitude": ",".join(f"{v:.5f}" for v in lo)}, timeout=60)
            if r.status_code == 429: time.sleep(6 * (attempt + 1)); continue
            r.raise_for_status(); return r.json()["elevation"]
        raise RuntimeError("open-meteo rate limited")
    elev = []
    for i in range(0, len(samples), 100): elev += get(lats[i:i + 100], lons[i:i + 100]); time.sleep(2)
    e0 = get([lat], [lon])[0]
    prof = {}
    for az in azs:
        best = -10.0
        for d in dists:
            e = elev[samples.index((az, d))]; ang = math.degrees(math.atan2(e - e0, d)); best = max(best, ang)
        prof[str(az)] = round(best, 2)
    out = {"az_step": az_step, "site_elev_m": e0, "horizon_deg": prof, "source": "open-meteo elevation (90 m)"}
    json.dump(out, open(cache, "w")); return out

if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[3] == "plan":
        site = json.load(open(pathlib.Path(sys.argv[2]) / "site.json")); plan_image(site, pathlib.Path(sys.argv[2]) / "plan.png"); print("plan written")
    else:
        site = build_site(sys.argv[1], sys.argv[2]); plan_image(site, pathlib.Path(sys.argv[2]) / "plan.png")
