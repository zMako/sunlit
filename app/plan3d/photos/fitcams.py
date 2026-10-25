"""Deterministic listing-photo cameras for the apartment page's Photos mode: no model calls, nothing to pay.
Each empty-room photo of the unit's building has a Mask2Former label image (feasibility/listings/<lid>/NN.seg.npz); fit.js
renders our apartment as the same labels from a grid of standpoints and finds the camera whose labels agree best
(analysis by synthesis). Photos that agree poorly with every pose are another unit of the building, and are left out.
Writes app/plan3d/photos/<unit>.json (same format as photocams.py, source "fit").
    ../../../feasibility/.venv/bin/python fitcams.py gs-22612_plan_03 [more units | --building gs-22612] [--min 0.6]"""
import sys, json, re, pathlib, argparse, asyncio, numpy as np
HERE = pathlib.Path(__file__).resolve().parent; APP = HERE.parents[1]; LIST = APP.parent / "feasibility" / "listings"
sys.path.insert(0, str(HERE)); from photocams import content_box   # noqa: E402

def labels_at(seg, crop, w):
    L = np.load(seg)["labels"]; H, W = L.shape; x0, y0, x1, y1 = int(crop[0] * W), int(crop[1] * H), int(crop[2] * W), int(crop[3] * H)
    L = L[y0:y1, x0:x1]; h = max(8, round(w * L.shape[0] / L.shape[1])); out = np.zeros((h, w), np.uint8)
    ys = np.linspace(0, L.shape[0], h + 1).astype(int); xs = np.linspace(0, L.shape[1], w + 1).astype(int)
    for j in range(h):
        for i in range(w):
            b = L[ys[j]:max(ys[j] + 1, ys[j + 1]), xs[i]:max(xs[i] + 1, xs[i + 1])]; out[j, i] = np.bincount(b.ravel(), minlength=9).argmax()
    return out

def photos_of(lid):
    out = []
    for p in sorted((LIST / lid).glob("*.jpg")):
        if not re.fullmatch(r"\d+\.jpg", p.name) or not p.with_suffix(".seg.npz").exists(): continue
        crop = content_box(p); from PIL import Image; im = Image.open(p); aspect = (crop[2] - crop[0]) * im.width / ((crop[3] - crop[1]) * im.height)
        c, f = labels_at(p.with_suffix(".seg.npz"), crop, 40), labels_at(p.with_suffix(".seg.npz"), crop, 96)
        info = float(np.isin(f, [1, 2, 4, 5]).mean())   # floor, ceiling and openings locate a photo; tile close-ups have none
        if info < 0.15: print(f"  {p.name}: left out, close-up ({info:.0%} floor/ceiling/openings)"); continue
        if float(np.isin(f, [4, 5]).mean()) < 0.02: print(f"  {p.name}: left out, no window or door to anchor it"); continue   # a blank corner fits anywhere
        heavy = float((f == 7).mean()) >= 0.25   # mostly cabinetry: a kitchen or bath, search only rooms with fixtures
        out.append({"id": p.name, "src": f"/listings/{lid}/{p.name}", "crop": [round(v, 4) for v in crop], "aspect": round(aspect, 4),
                    "w": c.shape[1], "h": c.shape[0], "labels": c.ravel().tolist(), "fw": f.shape[1], "fh": f.shape[0], "flabels": f.ravel().tolist(), "fixtureHeavy": heavy})
    return out

async def run(units, minscore):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"])
        cache = {}
        for unit in units:
            lid = unit.split("_plan_")[0]; ph = cache.setdefault(lid, photos_of(lid))
            if not ph: print(f"{unit}: no segmented photos"); continue
            pg = await b.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
            await pg.goto(f"http://127.0.0.1:8765/plan3d/photos/fit.html?unit={unit}", timeout=90000)
            try: await pg.wait_for_function("window.fit && window.fit.ready", timeout=90000)
            except Exception: print(f"{unit}: page failed {errs[:1]}"); await pg.close(); continue
            r = await pg.evaluate("ph => window.fit.run(ph)", [{k: v for k, v in x.items() if k not in ("src", "crop")} for x in ph])
            rooms = {x["id"]: x["name"] for x in await pg.evaluate("window.fit.rooms")}
            byid = {x["id"]: x for x in ph}; keep = []
            # measured cameras (photo metrology, polish/cameras.json) beat the fit wherever they still sit in the same room
            try: metro = {c["photo"].split("/")[1]: c for c in json.load(open(APP / "plan3d" / "polish" / "cameras.json")) if c["unit"] == unit}
            except Exception: metro = {}
            for res in r["results"]:
                c = metro.get(res["id"])
                if c and c.get("room") == res.get("room"):
                    res.update(pos=c["pos"], yaw=c["yaw"], pitch=c["pitch"], hfov=c["fov"], score=max(res["score"], 0.9), measured=True)
            for res in sorted(r["results"], key=lambda q: -q["score"]):
                x = byid[res["id"]]; ok = res["score"] >= minscore
                print(f"  {res['id']}: {'KEEP' if ok else 'skip'} score {res['score']:.3f} (coarse {res['coarse']:.3f})  {res['room']} {rooms.get(res['room'], '')} pos {res['pos']} yaw {res['yaw']} pitch {res['pitch']} hfov {res['hfov']}")
                if ok: keep.append({"src": x["src"], "room": res["room"], "pos": res["pos"], "yaw": res["yaw"], "pitch": res["pitch"], "hfov": res["hfov"],
                                    "aspect": x["aspect"], "crop": x["crop"], "confidence": res["score"], "source": "metrology" if res.get("measured") else "fit",
                                    "why": "single-view metrology (floor and ceiling lines)" if res.get("measured") else "label match (analysis by synthesis)"})
            keep.sort(key=lambda q: q["src"])
            json.dump({"unit": unit, "photos": keep, "model": "fit (deterministic)", "standpoints": r["standpoints"]}, open(HERE / f"{unit}.json", "w"), indent=1)
            print(f"{unit}: {len(keep)} of {len(ph)} photos kept, {r['standpoints']} standpoints, {r['ms'] / 1000:.1f} s"); await pg.close()
        await b.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("units", nargs="*"); ap.add_argument("--building"); ap.add_argument("--min", type=float, default=0.6)
    A = ap.parse_args(); units = list(A.units)
    if A.building: units += [u["unit"] for u in json.load(open(APP / "plan3d" / "layouts" / "index.json")) if u["unit"].startswith(A.building + "_plan_")]
    asyncio.run(run(units, A.min))
