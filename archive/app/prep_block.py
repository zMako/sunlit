"""Fetch SF building footprints with LiDAR heights around (lat, lon); write block.json in a local metric ENU frame."""
import sys, json, math, pathlib, requests
lat, lon = float(sys.argv[1]), float(sys.argv[2]); radius = float(sys.argv[3]) if len(sys.argv) > 3 else 180
out = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else pathlib.Path(__file__).parent / "block.json"
url = ("https://data.sfgov.org/resource/ynuv-fyni.json?$select=sf16_bldgid,hgt_mediancm,hgt_maxcm,gnd_mediancm,shape"
       f"&$where=within_circle(shape,{lat},{lon},{radius})&$limit=2000")
rows = requests.get(url, timeout=60).json()
mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(lat)); mlon = 111412.84 * math.cos(math.radians(lat)) - 93.5 * math.cos(3 * math.radians(lat))
def enu(p): return [round((p[0] - lon) * mlon, 2), round((p[1] - lat) * mlat, 2)]
gnds = [float(r["gnd_mediancm"]) / 100 for r in rows if r.get("gnd_mediancm")]
gnd0 = sorted(gnds)[len(gnds) // 2] if gnds else 0.0
bld = []
for r in rows:
    g = r["shape"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    h = float(r.get("hgt_mediancm") or r.get("hgt_maxcm") or 300) / 100
    gnd = float(r["gnd_mediancm"]) / 100 - gnd0 if r.get("gnd_mediancm") else 0.0
    for poly in polys:
        bld.append({"id": r["sf16_bldgid"], "ring": [enu(p) for p in poly[0]], "height": round(h, 2), "ground": round(gnd, 2)})
out.write_text(json.dumps({"lat": lat, "lon": lon, "radius": radius, "ground0_m": gnd0, "buildings": bld}))
print(f"{len(rows)} footprints, {len(bld)} polygons, ground0 {gnd0:.1f} m, heights {min(b['height'] for b in bld):.1f}-{max(b['height'] for b in bld):.1f} m -> {out}")
