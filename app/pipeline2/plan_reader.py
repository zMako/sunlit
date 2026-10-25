"""Floor plan -> rooms as metric rectangles with walls and openings (schema v2). Claude (Sonnet by default; Haiku misses
dimension text) reads the plan image: room labels, printed dimensions verbatim, the room rectangle in image fractions, which
walls are exterior, and where windows/doors/openings sit along each wall. Dimensions are converted feet->metres in code;
rooms without printed dimensions are scaled from the plan's pixel scale when another room has printed dimensions.
Usage: plan_reader.py <plan image> [sqft_total|-] [model]"""
import sys, io, json, base64, re, pathlib, hashlib, statistics
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import claude_client as cc, spend

V2_MODEL = "claude-sonnet-5-5"
WALL = {"type": "object", "additionalProperties": False, "properties": {
    "exterior": {"type": "boolean", "description": "the wall is on the building exterior (windows possible)"},
    "openings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "kind": {"type": "string", "enum": ["window", "door", "opening", "closet"]},
        "from_frac": {"type": "number", "description": "start along the wall, 0..1; N/S walls run west->east, E/W walls run north->south"},
        "to_frac": {"type": "number"}}, "required": ["kind", "from_frac", "to_frac"]}}}, "required": ["exterior", "openings"]}
SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
  "has_dimensions": {"type": "boolean", "description": "at least one room has printed dimensions"}, "units": {"type": "string", "enum": ["feet_inches", "feet_decimal", "metres", "none"]},
  "total_sqft_printed": {"type": ["number", "null"]}, "unit_label": {"type": ["string", "null"], "description": "plan title, e.g. '1 Bed, 1 Bath A' or 'Residence 04'"},
  "rooms": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
      "name": {"type": "string"}, "type": {"type": "string", "enum": ["living", "bedroom", "kitchen", "bathroom", "dining", "hallway", "office", "closet", "laundry", "balcony", "entry", "other"]},
      "width_text": {"type": ["string", "null"], "description": "printed dimension along the image x axis, verbatim, e.g. 12'6\""}, "depth_text": {"type": ["string", "null"], "description": "printed dimension along the image y axis, verbatim"},
      "width_m": {"type": ["number", "null"]}, "depth_m": {"type": ["number", "null"]},
      "shape": {"type": "string", "enum": ["rectangle", "L", "irregular"]},
      "position": {"type": "object", "additionalProperties": False, "properties": {"x_frac": {"type": "number"}, "y_frac": {"type": "number"}}, "required": ["x_frac", "y_frac"], "description": "room centre in the plan image, 0..1"},
      "x0_frac": {"type": "number"}, "x1_frac": {"type": "number"}, "y0_frac": {"type": "number"}, "y1_frac": {"type": "number"},
      "walls": {"type": "object", "additionalProperties": False, "properties": {"N": WALL, "S": WALL, "E": WALL, "W": WALL}, "required": ["N", "S", "E", "W"]},
      "exterior_sides": {"type": "array", "items": {"type": "string", "enum": ["north", "south", "east", "west"]}, "description": "image-up is north"},
      "windows": {"type": "integer"}, "doors": {"type": "integer"}, "adjacent": {"type": "array", "items": {"type": "string"}}},
      "required": ["name", "type", "width_text", "depth_text", "width_m", "depth_m", "shape", "position", "x0_frac", "x1_frac", "y0_frac", "y1_frac", "walls", "exterior_sides", "windows", "doors", "adjacent"]}},
  "notes": {"type": "string"}}, "required": ["has_dimensions", "units", "total_sqft_printed", "unit_label", "rooms", "notes"]}

SYSTEM = """You read architectural floor plans of apartments. Image-up is NORTH. For every room that is drawn (do not invent rooms):
- name and type; printed dimensions EXACTLY as written (width_text = the dimension along the image x axis, depth_text = along the image y axis;
  the printed "A x B" is usually width x depth but check which direction the room is longer in the drawing) and converted to metres
  (1 ft = 0.3048 m; 12'6" = 3.81 m). If a room has no printed dimensions set both texts to null and ESTIMATE width_m/depth_m from the
  drawing scale (door leaf 0.8 m, bathtub 1.5 m, bed 2.0 m), noting it in notes.
- the room's bounding rectangle in image fractions x0_frac<x1_frac, y0_frac<y1_frac (0..1 of the whole image), and its centre.
- for each of its four walls N,S,E,W: exterior (bool) and the openings drawn in that wall: windows (double lines / glazing symbol), doors
  (arc), open passages, closets. Position each opening as from_frac..to_frac along that wall: N and S walls run from their WEST end (0) to
  their EAST end (1); E and W walls run from their NORTH end (0) to their SOUTH end (1). An opening into a closet is kind "closet".
- exterior_sides, window count, door count and adjacent rooms as before.
has_dimensions is true when at least one room has printed dimensions. Be precise about which wall each window is on; that is what the
photos will be matched against."""

def ft_to_m(txt):
    if not txt: return None
    t = txt.replace("″", '"').replace("’", "'").replace("′", "'")
    m = re.match(r"\s*(\d+)\s*'?\s*(?:-|\s)?\s*(\d+)?(?:\s*(\d)/(\d))?", t)
    if not m: return None
    ft = int(m.group(1)); inch = int(m.group(2)) if m.group(2) else 0
    if m.group(3): inch += int(m.group(3)) / int(m.group(4))
    return round((ft + inch / 12) * 0.3048, 3)

def _scale_rooms(g, W, H):
    """metres per image pixel from rooms with printed dimensions; apply to rooms without."""
    sx, sy = [], []
    for rm in g["rooms"]:
        pw, ph = (rm["x1_frac"] - rm["x0_frac"]) * W, (rm["y1_frac"] - rm["y0_frac"]) * H
        if rm.get("width_text") and rm.get("width_m") and pw > 5: sx.append(rm["width_m"] / pw)
        if rm.get("depth_text") and rm.get("depth_m") and ph > 5: sy.append(rm["depth_m"] / ph)
    s = statistics.median(sx + sy) if (sx + sy) else None; g["m_per_px"] = round(s, 6) if s else None
    for rm in g["rooms"]:
        printed = bool(rm.get("width_text") or rm.get("depth_text"))
        if printed: rm["dims_source"] = "printed"
        elif s:
            rm["width_m"] = round((rm["x1_frac"] - rm["x0_frac"]) * W * s, 2); rm["depth_m"] = round((rm["y1_frac"] - rm["y0_frac"]) * H * s, 2); rm["dims_source"] = "scaled_from_plan"
        else: rm["dims_source"] = "estimated"
        if printed:   # one printed dimension only: scale the other from pixels
            if not rm.get("width_text") and s: rm["width_m"] = round((rm["x1_frac"] - rm["x0_frac"]) * W * s, 2)
            if not rm.get("depth_text") and s: rm["depth_m"] = round((rm["y1_frac"] - rm["y0_frac"]) * H * s, 2)
    return g

def read_plan(path, sqft_total=None, model=V2_MODEL, cached_only=False):
    path = pathlib.Path(path); key = hashlib.sha1((str(path) + model + "v2").encode()).hexdigest()[:10]; cache = path.parent / f"plan_{key}.json"
    if cache.exists(): return json.load(open(cache))
    if cached_only:   # offline rebuilds: the cache key holds the path as first given, absolute or repo-relative
        root = pathlib.Path(__file__).resolve().parents[2]
        for alt in {str(path.resolve()), str(path.resolve().relative_to(root)) if path.resolve().is_relative_to(root) else str(path)}:
            c2 = path.parent / f"plan_{hashlib.sha1((alt + model + 'v2').encode()).hexdigest()[:10]}.json"
            if c2.exists(): return json.load(open(c2))
        return None
    im0 = Image.open(path).convert("RGB"); W0, H0 = im0.size; im = im0.copy(); im.thumbnail((1600, 1600)); b = io.BytesIO(); im.save(b, "PNG")
    content = [{"type": "text", "text": f"Floor plan image {im.size[0]}x{im.size[1]} px. Listed total: {sqft_total or 'unknown'} sq ft."},
               {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(b.getvalue()).decode()}}]
    c = cc.client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, system=SYSTEM, messages=messages).input_tokens; spend.check("anthropic", spend.anthropic_estimate(model, n_in, 12000))
    r = c.messages.create(model=model, max_tokens=12000, system=SYSTEM, messages=messages, output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "medium"})
    usd = spend.anthropic_charge(model, r.usage, note=f"plan v2 {path.name}")
    txt = next((bl.text for bl in r.content if bl.type == "text"), None)
    if r.stop_reason == "refusal" or txt is None: raise RuntimeError(f"plan_reader: no JSON (stop {r.stop_reason}, blocks {[bl.type for bl in r.content]}, out tokens {r.usage.output_tokens})")
    g = json.loads(txt); g["_model"] = model; g["_usd"] = round(usd, 5); g["_schema"] = 2; g["_image_px"] = [W0, H0]; g["_file"] = path.name
    for rm in g["rooms"]:   # trust printed text over the model's arithmetic
        for k in ("width", "depth"):
            v = ft_to_m(rm.get(f"{k}_text"))
            if v: rm[f"{k}_m"] = v
        for side in ("N", "S", "E", "W"):
            for o in rm["walls"][side]["openings"]:
                o["from_frac"], o["to_frac"] = sorted((max(0.0, min(1.0, o["from_frac"])), max(0.0, min(1.0, o["to_frac"]))))
    g = _scale_rooms(g, W0, H0)
    g["has_dimensions"] = any(rm["dims_source"] == "printed" for rm in g["rooms"])
    area = sum((rm["width_m"] or 0) * (rm["depth_m"] or 0) for rm in g["rooms"] if rm["type"] != "balcony"); g["rooms_area_m2"] = round(area, 1)
    if sqft_total: g["listed_area_m2"] = round(sqft_total * 0.0929, 1); g["area_ratio_rooms_over_listed"] = round(area / max(g["listed_area_m2"], 1e-6), 2)
    json.dump(g, open(cache, "w"), indent=1); return g

def summary(g):
    out = []
    for r in g["rooms"]:
        ops = {s: "".join(o["kind"][0].upper() for o in r["walls"][s]["openings"]) for s in "NSEW"}
        out.append(f"{r['name'][:22]:22s} {r['type']:8s} {r['width_text'] or '-':>7s} x {r['depth_text'] or '-':<7s} = {r['width_m']}x{r['depth_m']} m [{r['dims_source']}] walls " + " ".join(f"{s}:{'ext' if r['walls'][s]['exterior'] else 'int'}{('/' + ops[s]) if ops[s] else ''}" for s in "NSEW"))
    return "\n".join(out)

if __name__ == "__main__":
    sq = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    g = read_plan(sys.argv[1], sq, sys.argv[3] if len(sys.argv) > 3 else V2_MODEL)
    print(json.dumps({k: g.get(k) for k in ("unit_label", "has_dimensions", "units", "m_per_px", "rooms_area_m2", "_usd")})); print(summary(g))
