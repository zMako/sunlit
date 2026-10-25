"""Render light-stage thumbnails for the landing page: python landing/shoot.py [unit[:key=val,...]] ... -> landing/thumbs/<unit>[ -furnished].jpg"""
import sys, asyncio, pathlib
from playwright.async_api import async_playwright
OUT = pathlib.Path(__file__).resolve().parent / "thumbs"; OUT.mkdir(exist_ok=True)
async def main(jobs):
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"])
        for job in jobs:
            unit, _, extra = job.partition(":"); prm = {"furnish": "0", "bg": "f5f5f4", "dpr": "2"}
            prm.update(kv.split("=", 1) for kv in extra.split(",") if "=" in kv); q = "&".join(f"{k}={v}" for k, v in prm.items())
            name = unit + ("-furnished" if prm["furnish"] == "1" else "") + (f"-{prm['tag']}" if "tag" in prm else "")
            for attempt in range(4):   # the dev server resets connections under bursts (listen backlog 5): a reset texture renders black, so retry
                pg = await b.new_page(viewport={"width": int(prm.get("w", 1200)), "height": int(prm.get("h", 900))}); errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)[:160])); pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text[:160]))
                await pg.goto(f"http://127.0.0.1:8765/plan3d/stage.html?unit={unit}&{q}", timeout=90000)
                try: await pg.wait_for_function("document.title !== 'stage'", timeout=90000)
                except Exception as e: errs.append("timeout")
                await pg.wait_for_timeout(1500); title = await pg.title()
                if not errs and title == "ready": break
                await pg.close(); await asyncio.sleep(2)
            await pg.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=88)
            print(f"[shoot] {name}: {title} attempt {attempt + 1} {errs[:1]}", flush=True); await pg.close()
        await b.close()
asyncio.run(main(sys.argv[1:]))
