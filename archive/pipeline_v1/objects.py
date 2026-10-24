"""Step 5: furniture as objects. Non-structure geometry on the floor -> blobs with real size and position; Claude names each
from a photo crop; Poly Pizza supplies a CC-BY model; the model is scaled to the blob and placed. Photo mesh stays the truth."""
import sys, io, json, base64, pathlib, hashlib, numpy as np, cv2, requests
from PIL import Image
from shapely.geometry import Polygon, Point
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import claude_client as cc, spend
from geometry import OTHER, FLOOR, CEIL, WALL
ROOT = pathlib.Path(__file__).resolve().parents[1]; ASSETS = ROOT / "assets"; ASSETS.mkdir(exist_ok=True)
CELL = 0.05
LABELS = ["sofa", "armchair", "bed", "table", "desk", "chair", "dresser", "wardrobe", "bookshelf", "tv", "radiator", "fridge", "stove", "oven", "washer", "dryer", "dishwasher", "sink", "toilet", "bathtub", "kitchen cabinet", "island counter", "lamp", "plant", "rug", "mirror", "door", "other"]

def detect_blobs(room, V, min_area=0.04, max_h=2.2):
    pts, labels, good = room["pts"], room["labels"], room["good"]; poly = Polygon(V)
    m = good & (labels == OTHER) & (pts[..., 1] > 0.04) & (pts[..., 1] < max_h)
    P = pts[m]; idx_img = np.broadcast_to(np.arange(pts.shape[0])[:, None, None], labels.shape)[m]
    lo = np.array(V).min(0) - 0.3; hi = np.array(V).max(0) + 0.3; nx, nz = int((hi[0] - lo[0]) / CELL) + 1, int((hi[1] - lo[1]) / CELL) + 1
    gx = np.clip(((P[:, 0] - lo[0]) / CELL).astype(int), 0, nx - 1); gz = np.clip(((P[:, 2] - lo[1]) / CELL).astype(int), 0, nz - 1)
    occ = np.zeros((nz, nx), np.int32); np.add.at(occ, (gz, gx), 1)
    mask = (occ >= 4).astype(np.uint8); mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)); mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(mask); cell_id = lab[gz, gx]; blobs = []
    for j in range(1, n):
        if st[j, cv2.CC_STAT_AREA] * CELL * CELL < min_area: continue
        sel = cell_id == j; Q = P[sel]
        if len(Q) < 200: continue
        cx, cz = float(np.median(Q[:, 0])), float(np.median(Q[:, 2]))
        if not poly.buffer(0.3).contains(Point(cx, cz)): continue
        x0, x1 = np.quantile(Q[:, 0], [0.03, 0.97]); z0, z1 = np.quantile(Q[:, 2], [0.03, 0.97]); y0, y1 = np.quantile(Q[:, 1], [0.03, 0.97])
        w, d, h = float(x1 - x0), float(z1 - z0), float(y1)
        if max(w, d) < 0.12 or h < 0.1 or (w > 4.5 and d > 4.5): continue
        imgs, cnts = np.unique(idx_img[sel], return_counts=True); best_img = int(imgs[np.argmax(cnts)])
        blobs.append({"id": len(blobs), "center": [round(cx, 3), round(float(y0), 3), round(cz, 3)], "size": [round(w, 2), round(h, 2), round(d, 2)], "base_y": round(float(y0), 2),
                      "n_pts": int(len(Q)), "best_img": best_img, "bbox": [round(float(x0), 2), round(float(z0), 2), round(float(x1), 2), round(float(z1), 2)]})
    # pixel masks per blob for crops
    for b in blobs:
        i = b["best_img"]; mi = m[i].copy(); inb = (pts[i][..., 0] >= b["bbox"][0] - 0.05) & (pts[i][..., 0] <= b["bbox"][2] + 0.05) & (pts[i][..., 2] >= b["bbox"][1] - 0.05) & (pts[i][..., 2] <= b["bbox"][3] + 0.05)
        ys, xs = np.nonzero(mi & inb)
        b["px_box"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) > 20 else None
    return blobs

def crop_b64(rgb, box, margin=24):
    H, W = rgb.shape[:2]; x0, y0, x1, y1 = box; x0, y0 = max(0, x0 - margin), max(0, y0 - margin); x1, y1 = min(W - 1, x1 + margin), min(H - 1, y1 + margin)
    im = Image.fromarray(rgb[y0:y1 + 1, x0:x1 + 1]); b = io.BytesIO(); im.save(b, "JPEG", quality=85); return base64.standard_b64encode(b.getvalue()).decode()

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"items": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
    "id": {"type": "integer"}, "label": {"type": "string", "enum": LABELS}, "description": {"type": "string"}, "colour": {"type": "string"}, "is_furniture": {"type": "boolean"}, "confidence": {"type": "number"}},
    "required": ["id", "label", "description", "colour", "is_furniture", "confidence"]}}}, "required": ["items"]}

def name_blobs(room, blobs, model=cc.DEV_MODEL):
    todo = [b for b in blobs if b["px_box"]]
    if not todo: return blobs
    content = [{"type": "text", "text": "Each crop below is one object found on the floor of a room, with its measured width x height x depth in metres. Name it, describe it in a few words, give its dominant colour, and say whether it is a movable furniture piece (true) or a fixture/part of the room like a radiator, cabinet, appliance, door or wall section (false)."}]
    for b in todo: content += [{"type": "text", "text": f"Object id {b['id']}, size {b['size'][0]:.2f} x {b['size'][1]:.2f} x {b['size'][2]:.2f} m:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": crop_b64(room["rgb"][b["best_img"]], b["px_box"])}}]
    c = cc.client(); messages = [{"role": "user", "content": content}]
    n_in = c.messages.count_tokens(model=model, messages=messages).input_tokens; spend.check("anthropic", spend.anthropic_estimate(model, n_in, 1500))
    r = c.messages.create(model=model, max_tokens=1500, messages=messages, output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "low"})
    spend.anthropic_charge(model, r.usage, note="name blobs")
    if r.stop_reason == "refusal": return blobs
    named = {it["id"]: it for it in json.loads(next(bl.text for bl in r.content if bl.type == "text"))["items"]}
    for b in blobs:
        if b["id"] in named: b.update({k: named[b["id"]][k] for k in ("label", "description", "colour", "is_furniture", "confidence")})
    return blobs

def poly_pizza(query, limit=5):
    from dotenv import dotenv_values
    key = dotenv_values(ROOT.parent / ".env")["POLY_PIZZA_KEY"]
    r = requests.get(f"https://api.poly.pizza/v1.1/search/{requests.utils.quote(query)}", params={"Limit": limit}, headers={"x-auth-token": key}, timeout=30)
    spend.charge("google", 0.0, count_key="poly_pizza", note=query)   # free; counted for visibility
    if not r.ok: return []
    return r.json().get("results", [])

def fetch_asset(label, colour=""):
    cache = ASSETS / "index.json"; idx = json.load(open(cache)) if cache.exists() else {}
    if label in idx: return idx[label]
    res = [m for m in poly_pizza(label) if not m.get("Animated")] or poly_pizza(label)
    if not res: return None
    m = res[0]; gid = hashlib.sha1(m["Download"].encode()).hexdigest()[:12]; path = ASSETS / f"{gid}.glb"
    if not path.exists(): path.write_bytes(requests.get(m["Download"], timeout=60).content)
    entry = {"file": f"assets/{path.name}", "title": m["Title"], "attribution": m["Attribution"], "licence": m["Licence"], "tris": m.get("Tri Count"), "thumb": m.get("Thumbnail")}
    idx[label] = entry; json.dump(idx, open(cache, "w"), indent=1); return entry

def asset_bbox(path):
    import trimesh
    sc = trimesh.load(path, force="scene"); b = sc.bounds; return b.tolist()

def place_objects(room, V, blobs, edges):
    objs = []
    for b in blobs:
        if not b.get("label") or b["label"] in ("other", "door", "rug", "mirror"): continue
        a = fetch_asset(b["label"])
        if not a: continue
        try: bb = asset_bbox(ROOT / a["file"])
        except Exception: continue
        lo, hi = np.array(bb[0]), np.array(bb[1]); ext = np.maximum(hi - lo, 1e-3)
        w, h, d = b["size"]; cx, _, cz = b["center"]
        # yaw: face away from the nearest wall edge
        best = None
        for e in edges:
            p, q = np.array(e["a"]), np.array(e["b"]); t = np.clip(((np.array([cx, cz]) - p) @ (q - p)) / max(1e-9, (q - p) @ (q - p)), 0, 1); dist = np.linalg.norm(np.array([cx, cz]) - (p + t * (q - p)))
            if best is None or dist < best[0]: best = (dist, e)
        n = np.array(best[1]["n"]) if best else np.array([0.0, 1.0]); yaw = float(np.degrees(np.arctan2(-n[0], -n[1])))   # asset front (+z in glTF) points into the room
        # scale: match width/depth in the asset's local frame (assume asset front along +z: width = x extent, depth = z extent)
        sx, sy, sz = w / ext[0], h / ext[1], d / ext[2]
        if abs(np.radians(yaw)) % np.pi > np.pi / 4 and abs(np.radians(yaw)) % np.pi < 3 * np.pi / 4: sx, sz = d / ext[0], w / ext[2]
        s = [float(np.clip(v, 0.2, 5.0)) for v in (sx, sy, sz)]
        # keep the footprint inside the room: nudge toward the centroid until the half-extent box is inside (max 0.6 m)
        poly = Polygon(V); cen = np.array(poly.centroid.coords[0]); fw, fd = (w, d) if abs(np.radians(yaw)) % np.pi < np.pi / 4 or abs(np.radians(yaw)) % np.pi > 3 * np.pi / 4 else (d, w)
        from shapely.geometry import box as _box
        for _ in range(12):
            if poly.buffer(0.05).contains(_box(cx - fw / 2, cz - fd / 2, cx + fw / 2, cz + fd / 2)): break
            step = cen - np.array([cx, cz]); nrm_ = np.linalg.norm(step)
            if nrm_ < 1e-6: break
            cx, cz = cx + 0.05 * step[0] / nrm_, cz + 0.05 * step[1] / nrm_
        objs.append({"id": b["id"], "label": b["label"], "description": b.get("description"), "colour": b.get("colour"), "is_furniture": b.get("is_furniture"), "confidence": b.get("confidence"),
                     "size_m": b["size"], "position": [round(float(cx), 3), b["base_y"], round(float(cz), 3)], "yaw_deg": round(yaw, 1), "scale": [round(v, 3) for v in s], "asset_offset": [float(-(lo[0] + hi[0]) / 2), float(-lo[1]), float(-(lo[2] + hi[2]) / 2)],
                     "asset": a})
    return objs

def run(room, V, edges, out_json, model=cc.DEV_MODEL):
    blobs = detect_blobs(room, V); blobs = name_blobs(room, blobs, model=model) if blobs else blobs
    objs = place_objects(room, V, blobs, edges)
    json.dump({"blobs": blobs, "objects": objs}, open(out_json, "w"), indent=1)
    print(f"[objects] {len(blobs)} blobs -> {len(objs)} placed: " + "; ".join(f"{o['label']} {o['size_m'][0]}x{o['size_m'][1]}x{o['size_m'][2]} m ({o['asset']['title']})" for o in objs))
    return objs
