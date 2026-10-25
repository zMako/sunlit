"""Room names and types from the text printed on the plan (Apple Vision OCR through ocrmac: local, free). Each OCR'd word
is placed in the room polygon that holds it; room-name words (BEDROOM, BATH 2, WALK-IN CLOSET, ...) become the room's name
and type. Names Claude already gave (annotation / plan reading carried by rebuild.py) are kept; generic ones ("Room 3") and
the model's room-class guesses are replaced. OCR is cached next to the plan: ocr_<stem>.json.

  room_names.py [units ...]   rename rooms in layouts/<unit>.json (default: every unit rebuilt with the learned walls),
                              then refresh rooms_export + the index entries"""
import sys, json, re, pathlib, subprocess
from shapely.geometry import Polygon, Point
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]; PY = str(ROOT / "feasibility/.venv/bin/python")

# word -> (type, canonical name); first match per room wins in reading order, but a second distinct word joins ("Living / Dining")
VOCAB = [
    (r"^(PRIMARY|MASTER|OWNER'?S)$", None, "Primary"),   # modifier: joins the next name word
    (r"^(BED ?ROOM|BEDRM|BDRM|BR|BED|SLEEP)$", "bedroom", "Bedroom"),
    (r"^(GREAT ?ROOM)$", "living", "Great Room"),
    (r"^(LIVING|LIVE|LOUNGE|FAMILY)$", "living", "Living"),
    (r"^(DINING|DINE|EAT|NOOK)$", "dining", "Dining"),
    (r"^(KITCHEN|KIT\.?)$", "kitchen", "Kitchen"),
    (r"^(BATH ?ROOM|BATH|BA|POWDER|PDR\.?|EN ?SUITE|WC|SHOWER)$", "bathroom", "Bath"),
    (r"^(WALK-?IN|W\.?I\.?C\.?|WIC)$", "closet", "Walk-in Closet"),
    (r"^(CLOSET|CLO\.?|CL\.?|WARDROBE|LINEN|LIN\.?|PANTRY|PAN\.?|COAT|STORAGE|STOR\.?)$", "closet", "Closet"),
    (r"^(W/?D|LAUNDRY|LAUN\.?|UTILITY|UTIL\.?)$", "laundry", "Laundry"),
    (r"^(ENTRY|FOYER|VESTIBULE)$", "entry", "Entry"),
    (r"^(HALL|HALLWAY|CORRIDOR|GALLERY)$", "hallway", "Hall"),
    (r"^(DEN|OFFICE|STUDY|FLEX|MEDIA|LIBRARY|LOFT|ALCOVE)$", "office", None),   # keep the printed word as the name
    (r"^(BALCONY|PATIO|DECK|TERRACE|LANAI|PORCH)$", "balcony", None),
]
BAD = re.compile(r"\d+\s*['’′]|\d+\s*x\s*\d+|SQ\.?\s*FT", re.I)   # dimensions and areas (bare numbers stay: BEDROOM / 1)

def ocr(plan):
    p = pathlib.Path(plan); cache = p.parent / f"ocr_{p.stem}.json"
    if cache.exists(): return json.load(open(cache))
    from ocrmac import ocrmac
    r = ocrmac.OCR(str(p), recognition_level="accurate").recognize()
    out = [{"text": t, "conf": float(c), "box": [float(v) for v in b]} for t, c, b in r]   # box: x, y, w, h normalised, y from the BOTTOM
    json.dump(out, open(cache, "w")); return out

def name_from_words(words):
    """words in reading order -> (name, type) or None"""
    toks = []
    for w in words:
        for t in re.split(r"[\s/]+(?=[A-Za-z])", w.strip()):   # "LIVING/DINING" -> two words; keep "W/D" whole below
            toks.append(t)
    if any(re.fullmatch(r"W/?D", w.strip(), re.I) for w in words): toks = [w.strip() for w in words]
    parts, typ, mod, num = [], None, None, None
    for t in toks:
        u = t.upper().strip(".,:;()*")
        if not u: continue
        if re.fullmatch(r"\d{1,2}", u) and parts: num = num or u; continue
        for pat, ty, canon in VOCAB:
            if re.fullmatch(pat, u):
                if ty is None: mod = canon; break
                nm = canon or u.title()
                # a second word joins only when it names another kind of living space (Living / Dining, Kitchen / Dining)
                if not parts or (nm not in parts and ty in ("living", "dining", "kitchen") and typ in ("living", "dining", "kitchen")): parts.append(nm)
                typ = typ or ty; break
    if not parts: return None
    name = " / ".join(parts[:2])
    if mod and typ in ("bedroom", "bathroom", "closet"): name = f"{mod} {name}"
    if num and len(parts) == 1: name = f"{name} {num}"
    return name, typ

def rename(L):
    """in place; returns the number of rooms renamed"""
    plan = L["plan_image"] if L["plan_image"].startswith("/") else str(ROOT / L["plan_image"])
    words = ocr(plan)
    from PIL import Image
    W, H = Image.open(plan).size; sc = L["scale"]; m, (ox, oy), s = sc["m_per_px"], sc["origin_px"], sc.get("image_scale", 1) or 1
    polys = [Polygon([((x / m + ox) / s, (z / m + oy) / s) for x, z in r["polygon"]]).buffer(0) for r in L["rooms"]]
    inside = {i: [] for i in range(len(L["rooms"]))}
    for w in words:
        if w["conf"] < 0.4 or BAD.search(w["text"]): continue
        x, y, bw, bh = w["box"]; cx, cy = (x + bw / 2) * W, (1 - y - bh / 2) * H
        for i, P in enumerate(polys):
            if P.contains(Point(cx, cy)): inside[i].append((cy, cx, w["text"])); break
    n = 0
    for i, r in enumerate(L["rooms"]):
        keep = r.get("named_from") in ("previous layout", "plan reading (cached)") and not r["name"].startswith("Room ")
        got = name_from_words([t for _, _, t in sorted(inside[i])])
        if got and not keep:
            r["name"], r["type"] = got[0], got[1] or r["type"]; r["named_from"] = "plan text (OCR)"; n += 1
        elif not keep and r["name"].startswith("Room ") and r.get("area_m2", 99) < 2.0:   # tiny unlabelled space: a closet
            r["name"], r["type"], r["named_from"] = "Closet", "closet", "size"
    # numbered duplicates: two "Bedroom" -> "Bedroom 1", "Bedroom 2" (the printed numbers win when present)
    seen = {}
    for r in L["rooms"]: seen.setdefault(r["name"], []).append(r)
    for nm, rs in seen.items():
        if len(rs) > 1 and not nm.startswith("Room ") and rs[0]["type"] in ("bedroom", "bathroom"):
            for k, r in enumerate(rs, 1): r["name"] = f"{nm} {k}"
    return n

if __name__ == "__main__":
    idx_f = HERE / "layouts" / "index.json"; idx = json.load(open(idx_f)); by = {d["unit"]: d for d in idx}
    units = sys.argv[1:] or [d["unit"] for d in idx if d.get("walls_from")]
    tot = 0
    for u in units:
        f = HERE / "layouts" / f"{u}.json"; L = json.load(open(f))
        try: n = rename(L)
        except Exception as e: print(f"[names] {u}: {type(e).__name__} {e}"); continue
        json.dump(L, open(f, "w"), indent=1); tot += n
        subprocess.run([PY, str(HERE / "rooms_export.py"), u], capture_output=True, text=True, cwd=str(ROOT))
        d = by.get(u)
        if d: d["rooms"] = [{"id": r["id"], "name": r["name"], "type": r["type"], "area_m2": r["area_m2"]} for r in L["rooms"]]; d["bedrooms"] = sum(1 for r in L["rooms"] if r["type"] == "bedroom")
    json.dump(idx, open(idx_f, "w"), indent=1); print(f"[names] {tot} rooms named from plan text over {len(units)} units")
