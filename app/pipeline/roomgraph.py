"""Phase 5: whole-apartment room graph from Claude. Input: listing title/address, all photos (downscaled), consistency clusters
as a hint. Output: rooms with photo assignment, type, exterior-window judgement, likely facade; floor plan parse if present."""
import sys, json, io, pathlib, base64
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import claude_client as cc, spend

SCHEMA = {"type": "object", "additionalProperties": False,
  "properties": {
    "unit": {"type": "object", "additionalProperties": False, "properties": {"floor": {"type": ["integer", "null"]}, "bedrooms": {"type": ["integer", "null"]}, "bathrooms": {"type": ["number", "null"]}, "notes": {"type": "string"}}, "required": ["floor", "bedrooms", "bathrooms", "notes"]},
    "floor_plan": {"type": "object", "additionalProperties": False, "properties": {"present": {"type": "boolean"}, "image_index": {"type": ["integer", "null"]},
        "rooms": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "approx_w_m": {"type": ["number", "null"]}, "approx_d_m": {"type": ["number", "null"]}, "touches_street_side": {"type": ["boolean", "null"]}}, "required": ["name", "approx_w_m", "approx_d_m", "touches_street_side"]}},
        "adjacency": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}}}, "required": ["present", "image_index", "rooms", "adjacency"]},
    "rooms": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string"}, "type": {"type": "string", "enum": ["living", "bedroom", "kitchen", "bathroom", "dining", "hallway", "office", "closet", "laundry", "balcony", "other"]},
        "photos": {"type": "array", "items": {"type": "integer"}},
        "has_exterior_window": {"type": "boolean"}, "window_description": {"type": "string"},
        "likely_facade": {"type": "string", "enum": ["street", "back", "side_lightwell", "corner", "unknown"]},
        "direct_sun_visible_in_photos": {"type": "boolean"}, "confidence": {"type": "number"}}, "required": ["name", "type", "photos", "has_exterior_window", "window_description", "likely_facade", "direct_sun_visible_in_photos", "confidence"]}},
    "non_room_images": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"index": {"type": "integer"}, "what": {"type": "string"}}, "required": ["index", "what"]}}
  }, "required": ["unit", "floor_plan", "rooms", "non_room_images"]}

SYSTEM = """You are an architect reading a rental listing. You get the listing title, address and every listing image, numbered.
Group the interior photos into rooms (the same room photographed from several angles is ONE room). Use the geometry hint
(photo clusters that were found to share the same 3D surfaces) but override it when the pictures clearly show otherwise.
For each room say whether it has a window to the outside, describe the windows, and judge which side of the building it is on:
"street" (bay windows, street view, front facade), "back" (yard, lightwell with other backs), "side_lightwell", "corner", or "unknown".
Say whether direct sunlight patches are visible on the floor or walls in its photos.
If an image is a floor plan, parse it: room names, rough sizes in metres if a scale or dimensions are given, which rooms touch the
street side, and adjacency pairs. Images that are not rooms (floor plan, map, logo, exterior, amenities) go in non_room_images.
Be concrete and conservative; use confidence 0..1 per room."""

def thumb(path, max_px=768):
    im = Image.open(path).convert("RGB"); im.thumbnail((max_px, max_px)); b = io.BytesIO(); im.save(b, "JPEG", quality=82)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(b.getvalue()).decode()}}

def room_graph(listing_dir, model=cc.DEV_MODEL):
    d = pathlib.Path(listing_dir); meta = json.load(open(d / "meta.json")); photos = sorted(d.glob("*.jpg"))
    hint = json.load(open(d / "clusters.json")) if (d / "clusters.json").exists() else []
    codes = {c["i"]: c for c in meta.get("photo_codes", [])}
    if codes and model == cc.DEV_MODEL: model = "claude-sonnet-5-5"   # building galleries need the better eye for cross-angle matching
    gallery = ("\nThis is a BUILDING gallery, not one unit: photos with the same room code (BED1..BED6) can be different units, but a unit is "
               "usually shown with 2-4 views of the same living room / kitchen / bedroom. Merge photos into one room when distinctive features "
               "recur (same fireplace, ceiling material, balcony door, window shape, floor colour, closet doors, pass-through), even from very "
               "different angles; keep photos apart when such features contradict. Identical duplicates are one room.") if codes else ""
    content = [{"type": "text", "text": f"Listing title: {meta['title']}\nAddress: {meta.get('address')}\nGeometry hint, photo clusters that share 3D surfaces: {[c['images'] for c in hint]}{gallery}\nImages follow, numbered by filename index."}]
    for p in photos:
        tag = f" [gallery code {codes[int(p.stem)]['code']}, {codes[int(p.stem)]['room_hint']}]" if int(p.stem) in codes else ""
        content.append({"type": "text", "text": f"Image {int(p.stem)} ({p.name}){tag}:"}); content.append(thumb(p))
    c = cc.client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, system=SYSTEM, messages=messages).input_tokens
    est = spend.anthropic_estimate(model, n_in, 8000); spend.check("anthropic", est)
    kwargs = dict(model=model, max_tokens=8000, system=SYSTEM, messages=messages, output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "medium"})
    r = c.messages.create(**kwargs); usd = spend.anthropic_charge(model, r.usage, note=f"roomgraph {d.name}")
    if r.stop_reason == "refusal": raise RuntimeError("refused")
    text = next((b.text for b in r.content if b.type == "text"), None)
    if text is None or r.stop_reason == "max_tokens": raise RuntimeError(f"roomgraph: no complete JSON (stop {r.stop_reason}, out tokens {r.usage.output_tokens})")
    g = json.loads(text); g["_model"] = model; g["_usd"] = round(usd, 5); g["_input_tokens"] = n_in
    json.dump(g, open(d / "roomgraph.json", "w"), indent=1)
    print(f"[roomgraph] {meta['title'][:40]} | {model} | {n_in} in tokens, ${usd:.4f} | floor {g['unit']['floor']} | plan {g['floor_plan']['present']} | rooms: " +
          "; ".join(f"{r_['name']} ({r_['type']}, photos {r_['photos']}, win={r_['has_exterior_window']}, {r_['likely_facade']}, sun={r_['direct_sun_visible_in_photos']})" for r_ in g["rooms"]))
    return g

if __name__ == "__main__":
    room_graph(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else cc.DEV_MODEL)
