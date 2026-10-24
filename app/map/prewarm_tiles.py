"""Pre-warm the OSM tile cache (app/map/tiles/z/x/y.png) for the SF bbox at zooms 12-15 so the map works on bad wifi.
OSM tile usage policy: identifying User-Agent, sequential with 0.1 s pacing, only this small fixed area, cached forever.
  feasibility/.venv/bin/python app/map/prewarm_tiles.py [zmin zmax]"""
import math, pathlib, sys, time, urllib.request
HERE = pathlib.Path(__file__).parent.resolve(); TILES = HERE / "tiles"
UA = "MoveIn-CalHacks-demo/1.0 (local single-user tile cache; app/map in the sunlit project)"
LAT0, LAT1, LON0, LON1 = 37.70, 37.81, -122.52, -122.36
def tx(lon, z): return int((lon + 180) / 360 * 2 ** z)
def ty(lat, z): r = math.radians(lat); return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z)
def tiles(z0, z1):
    for z in range(z0, z1 + 1):
        for x in range(tx(LON0, z), tx(LON1, z) + 1):
            for y in range(ty(LAT1, z), ty(LAT0, z) + 1): yield z, x, y
if __name__ == "__main__":
    z0, z1 = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (12, 15)
    todo = list(tiles(z0, z1)); got = have = fail = 0
    print(f"[tiles] {len(todo)} tiles z{z0}-{z1}")
    for z, x, y in todo:
        f = TILES / str(z) / str(x) / f"{y}.png"
        if f.exists(): have += 1; continue
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers={"User-Agent": UA}), timeout=15) as r: data = r.read()
            f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(data); got += 1
        except Exception as e: fail += 1; print(f"[tiles] {z}/{x}/{y}: {e}")
        time.sleep(0.1)
    print(f"[tiles] fetched {got}, cached already {have}, failed {fail}")
