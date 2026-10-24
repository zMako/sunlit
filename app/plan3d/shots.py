"""Headless dollhouse screenshot of every unit in layouts/index.json -> app/plan3d/shots/<unit>.jpg; records page errors."""
import sys, json, asyncio, pathlib
from playwright.async_api import async_playwright
HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "shots"; OUT.mkdir(exist_ok=True)
units = [d["unit"] for d in json.load(open(HERE / "layouts" / "index.json"))]
if len(sys.argv) > 1: units = [u for u in units if any(u.startswith(a) for a in sys.argv[1:])]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"]); report = {}
        for u in units:
            if (OUT / f"{u}.jpg").exists(): continue
            pg = await b.new_page(viewport={"width": 1200, "height": 800}); errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)[:200]))
            try:
                await pg.goto(f"http://127.0.0.1:8765/plan3d/apartment.html?unit={u}", timeout=60000); await pg.wait_for_timeout(8000)
                await pg.screenshot(path=str(OUT / f"{u}.jpg"), type="jpeg", quality=80)
            except Exception as e: errs.append(f"nav: {str(e)[:120]}")
            await pg.close(); report[u] = errs; print(f"[shots] {u}: {'ok' if not errs else errs[0]}", flush=True)
        await b.close(); json.dump(report, open(OUT / "errors.json", "w"), indent=1)
asyncio.run(main())
