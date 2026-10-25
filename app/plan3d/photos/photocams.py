"""Where was each listing photo taken? -> app/plan3d/photos/<unit>.json for the apartment page's Photos mode.

For every empty-room listing photo of the unit's building (feasibility/listings/<lid>/NN.jpg; furnished ones were renamed
*.furnished and are skipped), Claude gets the landlord's floor plan, a diagram of OUR rebuilt layout (room ids, metre grid,
windows, doors, direction legend) and the photo, and answers: does the photo belong to this apartment, which room, where the
photographer stood (x, z in metres on the diagram), which way they looked, lens width, eye height and tilt. Answers are
checked (inside the room, plausible height / lens / tilt) and clamped. The single-view metrology cameras in
polish/cameras.json win where they still sit inside the same room of the current layout. Spend goes through claude_client.
    ../../../feasibility/.venv/bin/python photocams.py gs-22612_plan_03 [more units] [--max 12] [--model claude-sonnet-5-5]
yaw: degrees, walk convention (0 looks +z = down on the diagram, 90 looks +x = right); pitch: + looks up; hfov: horizontal."""
import sys, json, math, re, pathlib, argparse, io
from PIL import Image, ImageDraw, ImageFont
HERE = pathlib.Path(__file__).resolve().parent; APP = HERE.parents[1]; ROOT = APP.parent
sys.path.insert(0, str(APP)); import claude_client   # noqa: E402
LIST = ROOT / "feasibility" / "listings"

SYSTEM = """You locate the camera of a real-estate listing photo inside a floor plan. You get: (1) the landlord's floor plan,
(2) a diagram of the same apartment as rebuilt by us, in metres, with room ids, windows (blue), doors (green) and a 1 m grid,
(3) one listing photo. Listing galleries often mix units of the same building, so first decide whether the photo can be this
apartment at all (room shape, windows, doors, fixtures must be consistent with the plan); if not, say so.
If it matches: identify the room and which walls are visible on the left, centre and right of the photo, then place the
photographer on the diagram. Photographers usually stand in a corner or a doorway, at 1.3-1.6 m, with a wide lens (60-95 deg
horizontal), tilted slightly down. Use window and door positions in the photo to fix the direction.
Directions on the diagram: 0 deg = looking toward the BOTTOM of the diagram (+z), 90 = toward the RIGHT (+x), 180 = toward the
TOP, 270 = toward the LEFT. Think briefly, then end with one JSON object on its own line:
{"match": true|false, "room": "<room id like r0>", "x": <m>, "z": <m>, "height_m": <m>, "yaw_deg": <deg>, "pitch_deg": <deg>,
 "hfov_deg": <deg>, "confidence": <0..1>, "visible": "<left / centre / right walls in a few words>", "why": "<one sentence>"}"""

def in_poly(x, z, P):
    k = False; j = len(P) - 1
    for i in range(len(P)):
        xi, zi = P[i]; xj, zj = P[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi: k = not k
        j = i
    return k

def roomy(P):   # grid point inside the polygon farthest from its edges
    xs, zs = [p[0] for p in P], [p[1] for p in P]; best, bd = None, -1
    def edge(x, z):
        m = 1e9
        for i in range(len(P)):
            (ax, az), (bx, bz) = P[i], P[(i + 1) % len(P)]; dx, dz = bx - ax, bz - az; L = dx * dx + dz * dz or 1
            t = max(0, min(1, ((x - ax) * dx + (z - az) * dz) / L)); m = min(m, math.hypot(x - ax - t * dx, z - az - t * dz))
        return m
    for i in range(1, 24):
        for j in range(1, 24):
            x = min(xs) + (max(xs) - min(xs)) * i / 24; z = min(zs) + (max(zs) - min(zs)) * j / 24
            if in_poly(x, z, P):
                d = edge(x, z)
                if d > bd: bd, best = d, (x, z)
    return best, edge

def diagram(L, path):
    xs = [p[0] for w in L["walls"] for p in (w["a"], w["b"])]; zs = [p[1] for w in L["walls"] for p in (w["a"], w["b"])]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs); S = 900 / max(x1 - x0, z1 - z0, 1); M = 70
    W, H = int((x1 - x0) * S) + 2 * M, int((z1 - z0) * S) + 2 * M + 60
    img = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(img)
    try: f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15); fs = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception: f = fs = ImageFont.load_default()
    P = lambda x, z: (M + (x - x0) * S, M + (z - z0) * S)
    for gx in range(math.floor(x0), math.ceil(x1) + 1):
        d.line([P(gx, z0 - 0.5), P(gx, z1 + 0.5)], fill=(232, 232, 232)); d.text((P(gx, z0)[0] - 6, M - 40), f"{gx}", fill=(120, 120, 120), font=fs)
    for gz in range(math.floor(z0), math.ceil(z1) + 1):
        d.line([P(x0 - 0.5, gz), P(x1 + 0.5, gz)], fill=(232, 232, 232)); d.text((M - 50, P(x0, gz)[1] - 7), f"{gz}", fill=(120, 120, 120), font=fs)
    d.text((M, 8), "x (m) ->", fill=(120, 120, 120), font=fs); d.text((6, M - 20), "z (m)", fill=(120, 120, 120), font=fs)
    tints = [(255, 244, 230), (232, 244, 255), (236, 250, 236), (250, 236, 246), (246, 246, 230), (236, 236, 250)]
    for k, r in enumerate(L["rooms"]):
        d.polygon([P(*p) for p in r["polygon"]], fill=tints[k % len(tints)])
    walls = {w["id"]: w for w in L["walls"]}
    for w in L["walls"]: d.line([P(*w["a"]), P(*w["b"])], fill=(20, 20, 20), width=max(3, int((w.get("thickness_m") or 0.15) * S)))
    for o in L["openings"]:
        w = walls.get(o["wall"]);
        if not w: continue
        ax, az = w["a"]; bx, bz = w["b"]; ln = math.hypot(bx - ax, bz - az) or 1; ux, uz = (bx - ax) / ln, (bz - az) / ln
        a, b = (ax + ux * o["s0"], az + uz * o["s0"]), (ax + ux * o["s1"], az + uz * o["s1"])
        col = (40, 140, 230) if o["type"] == "window" else (40, 170, 80) if o["type"] in ("door", "closet_door") else (200, 200, 200)
        d.line([P(*a), P(*b)], fill=col, width=max(5, int((w.get("thickness_m") or 0.15) * S) + 3))
    for r in L["rooms"]:
        c, _ = roomy(r["polygon"]) if r["polygon"] else (None, None)
        if c: tx, ty = P(*c); lab = f'{r["id"]} {r["name"]}'; d.text((tx - d.textlength(lab, font=f) / 2, ty - 8), lab, fill=(0, 0, 0), font=f)
    d.text((M, H - 46), "Directions: 0 = toward the BOTTOM (+z), 90 = RIGHT (+x), 180 = TOP, 270 = LEFT.   blue = window, green = door", fill=(60, 60, 60), font=fs)
    img.save(path); return path

def content_box(path):   # listing photos are often a 4:3 shot centred on white padding: the real photo's box, normalised
    import numpy as np
    g = np.asarray(Image.open(path).convert("L"), dtype=np.float32); H, W = g.shape
    cols = np.where((g < 238).mean(axis=0) > 0.04)[0]; rows = np.where((g < 238).mean(axis=1) > 0.04)[0]
    if len(cols) < W * 0.2 or len(rows) < H * 0.2: return [0.0, 0.0, 1.0, 1.0]
    return [round(cols[0] / W, 4), round(rows[0] / H, 4), round((cols[-1] + 1) / W, 4), round((rows[-1] + 1) / H, 4)]

def frame_of(ph, lid, metro_cam=None):   # crop box and its aspect; metrology cameras keep the exact crop they were measured on
    im = Image.open(ph); W, H = im.size
    try:
        if metro_cam:
            x0, y0, x1, y1 = json.load(open(APP / "plan3d" / "polish" / "work" / "intrinsics.json"))[f"{lid}/{ph.stem}"]["crop"]
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1); c = [x0 / W, y0 / H, x1 / W, y1 / H]
        else: c = content_box(ph)
    except Exception: c = content_box(ph)
    return [round(v, 4) for v in c], round((c[2] - c[0]) * W / ((c[3] - c[1]) * H), 4)

def jpeg_small(src, out, side=1024):
    im = Image.open(src).convert("RGB"); im.thumbnail((side, side)); im.save(out, quality=88); return out

def locate(unit, max_photos, model):
    L = json.load(open(APP / "plan3d" / "layouts" / f"{unit}.json")); lid = unit.split("_plan_")[0]
    work = HERE / "work" / unit; work.mkdir(parents=True, exist_ok=True)
    dia = diagram(L, work / "diagram.png")
    pi = L.get("plan_image", ""); plan = LIST / pi[pi.index("/listings/") + len("/listings/"):] if "/listings/" in pi else None
    plan_small = jpeg_small(plan, work / "plan.jpg", 1400) if plan and plan.exists() else None
    photos = sorted(p for p in (LIST / lid).glob("*.jpg") if re.fullmatch(r"\d+\.jpg", p.name))[:max_photos]
    rooms = {r["id"]: r for r in L["rooms"]}
    # metrology cameras that still fit the current layout
    metro = {}
    try:
        for c in json.load(open(APP / "plan3d" / "polish" / "cameras.json")):
            r = rooms.get(c.get("room"))
            if c["unit"] == unit and r and in_poly(c["pos"][0], c["pos"][2], r["polygon"]): metro[c["photo"].split("/")[1]] = c
    except Exception: pass
    out, spent = [], 0.0
    for ph in photos:
        src = f"/listings/{lid}/{ph.name}"; crop, aspect = frame_of(ph, lid, metro.get(ph.name))
        if ph.name in metro:
            c = metro[ph.name]; out.append({"src": src, "room": c["room"], "pos": c["pos"], "yaw": c["yaw"], "pitch": c["pitch"], "hfov": c["fov"], "aspect": aspect, "crop": crop,
                                            "confidence": 0.9, "source": "metrology", "why": "single-view metrology (floor and ceiling lines)"}); continue
        content = [{"type": "text", "text": f"Apartment {unit}. Rooms: " + "; ".join(f'{r["id"]} {r["name"]} ({r.get("area_m2", 0):.0f} m2)' for r in L["rooms"])}]
        if plan_small: content += [{"type": "text", "text": "(1) landlord's floor plan:"}, claude_client.image_block(plan_small)]
        content += [{"type": "text", "text": "(2) our rebuilt layout in metres:"}, claude_client.image_block(dia),
                    {"type": "text", "text": f"(3) listing photo {ph.name} (aspect {aspect:.2f}):"}, claude_client.image_block(jpeg_small(ph, work / ph.name))]
        try: text, usd = claude_client.ask(SYSTEM, content, model=model, max_tokens=900, note=f"photocam {unit} {ph.name}")
        except Exception as e: print(f"  {ph.name}: {type(e).__name__} {str(e)[:120]}"); break
        spent += usd; m = re.findall(r"\{[^{}]*\}", text, re.S); a = None
        for blob in reversed(m):
            try: a = json.loads(blob); break
            except Exception: continue
        if not a or not a.get("match") or a.get("room") not in rooms:
            print(f"  {ph.name}: not this apartment ({(a or {}).get('why', 'no answer')[:90]})"); continue
        r = rooms[a["room"]]; x, z = float(a.get("x", 0)), float(a.get("z", 0))
        best, edge = roomy(r["polygon"])
        if not in_poly(x, z, r["polygon"]) and best: x, z = best   # outside its own room: stand at the roomiest spot instead
        elif edge(x, z) < 0.3 and best:                              # hugging a wall: step 0.3 m toward the room
            dx, dz = best[0] - x, best[1] - z; n = math.hypot(dx, dz) or 1; x, z = x + dx / n * 0.3, z + dz / n * 0.3
        h = min(1.8, max(1.2, float(a.get("height_m") or 1.5))); hf = min(110, max(45, float(a.get("hfov_deg") or 75)))
        out.append({"src": src, "room": a["room"], "pos": [round(x, 3), round(h, 3), round(z, 3)], "yaw": float(a.get("yaw_deg") or 0) % 360,
                    "pitch": min(15, max(-25, float(a.get("pitch_deg") or -5))), "hfov": hf, "aspect": aspect, "crop": crop, "confidence": float(a.get("confidence") or 0.5),
                    "source": f"claude ({model})", "visible": a.get("visible", ""), "why": a.get("why", "")})
        print(f"  {ph.name}: {a['room']} {r['name']}, ({x:.1f}, {z:.1f}) yaw {out[-1]['yaw']:.0f} hfov {hf:.0f} conf {out[-1]['confidence']:.2f}  ${usd:.3f}")
    json.dump({"unit": unit, "photos": out, "model": model}, open(HERE / f"{unit}.json", "w"), indent=1)
    print(f"{unit}: {len(out)} of {len(photos)} photos placed, ${spent:.3f}")

def recrop(unit):   # refresh crop boxes and aspects of an existing result without asking Claude again
    f = HERE / f"{unit}.json"; J = json.load(open(f)); lid = unit.split("_plan_")[0]
    for p in J["photos"]:
        ph = LIST / p["src"].split("/listings/")[1]; p["crop"], p["aspect"] = frame_of(ph, lid, p if p.get("source") == "metrology" else None)
    json.dump(J, open(f, "w"), indent=1); print(unit, [(p["src"].rsplit("/", 1)[1], p["crop"], p["aspect"]) for p in J["photos"]])

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("units", nargs="+"); ap.add_argument("--max", type=int, default=12); ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--recrop", action="store_true", help="only refresh crops of existing results (no Claude calls)")
    A = ap.parse_args()
    for u in A.units: recrop(u) if A.recrop else locate(u, A.max, A.model)
