"""Time from navigation start to the first rendered frame of the built apartment in apartment.html?quality=low, headless Chrome
(Playwright, SwiftShader software GL: slower than any real GPU, so these are upper bounds). The init script counts WebGL draw
calls and wraps requestAnimationFrame; the first rAF callback that issues draw calls after window.apartment exists (the scene is
built and the render loop runs) marks the first frame; the time is taken at the start of the following rAF (frame presented). Usage: page_time.py <base_url> <unit> [<unit> ...] -> one JSON line per unit."""
import sys, json, asyncio
from playwright.async_api import async_playwright
INIT = """(() => {
  let draws = 0; window.__t_first = null;
  for (const C of [window.WebGL2RenderingContext, window.WebGLRenderingContext]) { if (!C) continue;
    for (const f of ['drawElements', 'drawArrays', 'drawElementsInstanced', 'drawArraysInstanced']) { const o = C.prototype[f]; if (!o) continue;
      C.prototype[f] = function (...a) { draws++; return o.apply(this, a); }; } }
  const raf = window.requestAnimationFrame.bind(window);
  let pending = false;   // the frame counts once the NEXT rAF fires, i.e. after the browser presented it
  window.requestAnimationFrame = cb => raf(t => { if (pending && window.__t_first === null) window.__t_first = performance.now();
    const ready = !!window.apartment, d0 = draws; cb(t); if (ready && draws > d0) pending = true; });
})();"""
async def main(base, units):
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        for u in units:
            ctx = await b.new_context(viewport={"width": 1400, "height": 900}); pg = await ctx.new_page(); await pg.add_init_script(INIT)
            errs = []; pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
            try:
                await pg.goto(f"{base}/plan3d/apartment.html?unit={u}&quality=low", timeout=120000)
                await pg.wait_for_function("window.__t_first !== null", timeout=120000, polling=100)
                t = await pg.evaluate("window.__t_first"); print(json.dumps({"unit": u, "ok": True, "first_frame_s": round(t / 1000, 3), "pageerrors": errs[:2]}), flush=True)
            except Exception as e:
                print(json.dumps({"unit": u, "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}", "pageerrors": errs[:2]}), flush=True)
            await ctx.close()
        await b.close()
asyncio.run(main(sys.argv[1], sys.argv[2:]))
