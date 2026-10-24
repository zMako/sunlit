"""Render render.png (shaded, quality=low) and depth.png (disparity pass) for every camera in cameras.json with headless
Chrome (SwiftShader), at the photo crop's aspect ratio. Needs the app proxy on :8765. Usage: render.py [photo-filter]"""
import sys, json, asyncio, pathlib
from playwright.async_api import async_playwright
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "out"
BASE = "http://127.0.0.1:8765/plan3d/apartment.html"

def size_for(aspect, long=1200):
    w = long; h = int(round(w / aspect / 2) * 2); return w, h

async def shot(b, url, path, w, h, wait_ms):
    pg = await b.new_page(viewport={"width": w, "height": h}); logs = []
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text[:200]}")); pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {str(e)[:300]}"))
    await pg.goto(url); await pg.wait_for_timeout(4000)
    last = -1
    for _ in range(int(wait_ms / 2000)):   # wait until the furniture models stop arriving
        st = await pg.evaluate("window.polishcam ? window.polishcam.status() : null")
        if st and st["itemMeshes"] == last and st["frames"] > 10: break
        last = st["itemMeshes"] if st else -1; await pg.wait_for_timeout(2000)
    await pg.wait_for_timeout(1500); await pg.screenshot(path=str(path)); st = await pg.evaluate("window.polishcam ? window.polishcam.status() : null"); await pg.close()
    errs = [l for l in logs if "PAGEERROR" in l or l.startswith("error")]
    print(path.name, st, errs[:4])

async def main():
    cams = json.load(open(HERE / "cameras.json")); flt = sys.argv[1] if len(sys.argv) > 1 else ""
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for c in cams:
            if flt not in c["photo"]: continue
            key = c["photo"].replace("/", "_").replace(".jpg", ""); d = OUT / key; d.mkdir(parents=True, exist_ok=True)
            x, y, z = c["pos"]; cam = f"{x},{y},{z},{c['yaw']},{c['pitch']},{c['fov']}"; w, h = size_for(c["aspect"])
            q = f"?unit={c['unit']}&view=walk&room={c['room']}&nolock=1&quality=low&hideui=1&cam={cam}"
            await shot(b, BASE + q, d / "render.png", w, h, 40000)
            await shot(b, BASE + q + "&depth=1", d / "depth.png", w, h, 40000)
        await b.close()
asyncio.run(main())
