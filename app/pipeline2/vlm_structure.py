"""VLM structure pass: Claude reads all photos of ONE room and returns its structure as JSON (shape, approximate size,
walls in clockwise order with openings, colours, floor). Used as the prior for walls no photo measured, as a cross-check
on measured ones, and as the no-fail fallback room. Cached per room by photo list."""
import sys, io, json, base64, hashlib, pathlib
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import claude_client as cc, spend

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
  "shape": {"type": "string", "enum": ["rectangle", "L", "rectangle_with_bay", "other"]},
  "width_m": {"type": "number"}, "depth_m": {"type": "number"}, "ceiling_m": {"type": "number"},
  "size_confidence": {"type": "number"},
  "walls": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
      "label": {"type": "string", "description": "a short name: 'window wall', 'door wall', 'left of window', 'opposite window'"},
      "length_m": {"type": "number"}, "exterior": {"type": "boolean"}, "seen_in_photos": {"type": "array", "items": {"type": "integer"}},
      "openings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
          "kind": {"type": "string", "enum": ["window", "door", "passage", "closet"]}, "position_frac": {"type": "number", "description": "centre along the wall, 0 = left end when facing the wall from inside, 1 = right end"},
          "width_m": {"type": "number"}, "height_m": {"type": "number"}, "sill_m": {"type": "number"}}, "required": ["kind", "position_frac", "width_m", "height_m", "sill_m"]}}},
      "required": ["label", "length_m", "exterior", "seen_in_photos", "openings"]}},
  "wall_colour": {"type": "string"}, "wall_colour_rgb": {"type": "array", "items": {"type": "integer"}}, "floor_material": {"type": "string"}, "floor_colour_rgb": {"type": "array", "items": {"type": "integer"}},
  "notes": {"type": "string"}}, "required": ["shape", "width_m", "depth_m", "ceiling_m", "size_confidence", "walls", "wall_colour", "wall_colour_rgb", "floor_material", "floor_colour_rgb", "notes"]}

SYSTEM = """You are an architect reading photographs of ONE room of an empty apartment. Describe its structure as JSON.
Walk around the room clockwise as seen from above, starting with the wall that holds the main window (or, if none, the
wall most visible in the photos). For each wall give its length in metres, whether it is an exterior wall, which photos
show it, and its openings with position along the wall (0..1, left to right when facing the wall from inside), width,
height and sill. Use known sizes for scale: interior doors are about 2.03 m tall and 0.8 m wide, outlets sit 0.3 m above
the floor, baseboards are about 0.1 m, double-hung windows are about 0.9 m wide. Give the room's overall width (along the
first wall) and depth (perpendicular). Be conservative: if a wall was never photographed, estimate it from the room type
and say so in notes. size_confidence is 0..1."""

def thumb(path, max_px=900):
    im = Image.open(path).convert("RGB"); im.thumbnail((max_px, max_px)); b = io.BytesIO(); im.save(b, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(b.getvalue()).decode()}}

def structure(photo_paths, room_label="", model=cc.DEV_MODEL, cache_dir=None):
    photo_paths = [str(p) for p in photo_paths]; key = hashlib.sha1(("|".join(photo_paths) + model).encode()).hexdigest()[:12]
    cache = pathlib.Path(cache_dir or pathlib.Path(photo_paths[0]).parent) / f"structure_{key}.json"
    if cache.exists(): return json.load(open(cache))
    content = [{"type": "text", "text": f"Room: {room_label or 'unknown type'}. {len(photo_paths)} photos follow, numbered from 0."}]
    for i, p in enumerate(photo_paths): content += [{"type": "text", "text": f"Photo {i}:"}, thumb(p)]
    c = cc.client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, system=SYSTEM, messages=messages).input_tokens; spend.check("anthropic", spend.anthropic_estimate(model, n_in, 2500))
    r = c.messages.create(model=model, max_tokens=2500, system=SYSTEM, messages=messages, output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "medium"})
    usd = spend.anthropic_charge(model, r.usage, note=f"structure {room_label}")
    if r.stop_reason == "refusal": return None
    g = json.loads(next(b.text for b in r.content if b.type == "text")); g["_model"] = model; g["_usd"] = round(usd, 5)
    json.dump(g, open(cache, "w"), indent=1); return g

if __name__ == "__main__":
    g = structure(sys.argv[2:], sys.argv[1]); print(json.dumps({k: g[k] for k in ("shape", "width_m", "depth_m", "ceiling_m", "size_confidence", "wall_colour", "floor_material", "_usd")}), "| walls:", [(w["label"], w["length_m"], [o["kind"] for o in w["openings"]]) for w in g["walls"]])
