"""Per listing photo: everything the plan-built model can take from it. Wall faces (floor/ceiling boundary lines, corners),
windows (sill/head height from the vertical cross-ratio against the ceiling height, position along the wall via the face
homography, mullions, style), doors (position, width, kind), materials (CLIP+colour top-3 per surface from the CC0 library),
paint colours, plank direction. Metric anchors: ceiling height from the room's cached Claude structure (else 2.6 m) for the
vertical; the linked plan room's wall length for widths (else a fronto-parallel approximation, flagged).
Usage: photo_facts.py <listing_dir> [...]  -> <listing_dir>/photo_facts.json"""
import sys, json, pathlib, hashlib, math
import numpy as np, cv2
from PIL import Image
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[1]
for p in ("app/pipeline2", "app/pipeline2/wallwrap", "app/furnish", "app/pipeline", "app"): sys.path.insert(0, str(ROOT / p))
import seg, geom, matmatch
WALLISH = [seg.WALL, seg.WINDOW, seg.DOOR, seg.FIXTURE, seg.MIRROR]
DOOR_W = 0.86

def labels_for(photo, npz):
    lab = np.load(npz)["labels"].astype(np.uint8); W, H = photo.size
    return np.asarray(Image.fromarray(lab).resize((W, H), Image.NEAREST))

def structure_ceiling(ldir, photo_idxs, room_label):
    """Ceiling height from a cached vlm_structure call (no new calls). Tries the exact cache key, then the median over all cached structures of the listing."""
    try:
        import vlm_structure as vs, claude_client as cc
        for mk in (lambda i: str(ldir / f"{i:02d}.jpg"), lambda i: str((ldir / f"{i:02d}.jpg").resolve())):
            paths = [mk(i) for i in photo_idxs]
            for model in (cc.DEV_MODEL, "claude-sonnet-5-5"):
                key = hashlib.sha1(("|".join(paths) + model).encode()).hexdigest()[:12]; f = ldir / f"structure_{key}.json"
                if f.exists():
                    g = json.load(open(f)); return g.get("ceiling_m"), g, "structure(exact)"
    except Exception: pass
    cs = []
    for f in ldir.glob("structure_*.json"):
        try: g = json.load(open(f)); cs.append(g.get("ceiling_m"))
        except Exception: pass
    cs = [c for c in cs if c and 2.2 <= c <= 3.6]
    return (float(np.median(cs)) if cs else None), None, ("structure(listing median)" if cs else "default")

def components(mask, min_px):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8); out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a >= min_px: out.append({"x0": int(x), "y0": int(y), "x1": int(x + w), "y1": int(y + h), "area": int(a), "mask": lab == i})
    return out

def face_for(faces, xc):
    for k, f in enumerate(faces):
        if f["x0"] - 2 <= xc <= f["x1"] + 2: return k
    return None

def vertical_fracs(face, x, y_bottom, y_top):
    """Fractions of the wall height (0 floor .. 1 ceiling) of two image rows at column x, from the face's floor and ceiling lines."""
    mf, cf = face["floor"]; yF = mf * x + cf
    if not face["ceil"]: return None, None, yF, None
    mc, cc = face["ceil"]; yC = mc * x + cc
    if yF - yC < 10: return None, None, yF, yC
    fb = (yF - y_bottom) / (yF - yC); ft = (yF - y_top) / (yF - yC); return float(np.clip(fb, -0.2, 1.2)), float(np.clip(ft, -0.2, 1.3)), yF, yC

def u_fracs(face, x0, x1):
    """Position along the face (0..1, perspective-corrected) of two image columns, via the face quad homography."""
    q = geom.quad(face, default_ceil_y=0.0)
    try: Hm = geom.homography(q, (0.0, 1.0, 1.0, 0.0))
    except Exception: return None, None
    def u_of(x):
        y = face["floor"][0] * x + face["floor"][1]; v = Hm @ np.array([x, y, 1.0]); return float(v[0] / v[2]) if abs(v[2]) > 1e-9 else None
    return u_of(x0), u_of(x1)

def mullions(wmask_crop):
    """Vertical frame bars inside a window: columns in the middle rows with low window coverage."""
    if wmask_crop.size == 0: return 0, False
    h, w = wmask_crop.shape; mid = wmask_crop[int(h * 0.25):int(h * 0.75), :]
    if mid.size == 0: return 0, False
    cov = mid.mean(0); low = cov < 0.35; runs = 0; inrun = False
    for i in range(2, w - 2):
        if low[i] and not inrun: inrun = True; start = i
        if not low[i] and inrun:
            inrun = False
            if 2 <= i - start <= max(4, w // 8): runs += 1
    rows = wmask_crop[:, int(w * 0.25):int(w * 0.75)].mean(1); hdiv = bool(((rows[int(h * 0.3):int(h * 0.7)] < 0.35).sum() >= 2)) if h > 10 else False
    return runs, hdiv

def plank_direction(img, floor_mask):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY); e = cv2.Canny(g, 60, 140); e[~floor_mask] = 0
    e = cv2.erode(e, np.ones((1, 1), np.uint8)); lines = cv2.HoughLinesP(e, 1, np.pi / 180, 40, minLineLength=max(30, img.shape[1] // 25), maxLineGap=6)
    if lines is None or len(lines) < 4: return "unknown", 0
    lines = np.asarray(lines).reshape(-1, 4)
    ang = np.array([abs(math.degrees(math.atan2(l[3] - l[1], l[2] - l[0]))) for l in lines]); ang = np.minimum(ang, 180 - ang)
    horiz = int((ang < 15).sum()); steep = int((ang > 25).sum())
    if horiz + steep < 4: return "unknown", len(lines)
    return ("along_photo_x" if horiz >= 1.4 * steep else "along_depth" if steep >= 1.4 * horiz else "unknown"), int(len(lines))

def median_rgb(px):
    return [int(v) for v in np.median(px, 0)] if len(px) else None

def photo_facts(ldir, idx, link_photo, rg_room, ceiling_m, face_len_m):
    photo = Image.open(ldir / f"{idx:02d}.jpg").convert("RGB"); img = np.asarray(photo); lab = labels_for(photo, ldir / f"{idx:02d}.seg.npz")
    crop = geom.letterbox(img); x0c, y0c, x1c, y1c = crop; L = lab[y0c:y1c, x0c:x1c]; I = img[y0c:y1c, x0c:x1c]
    faces, yf, yc = geom.faces_from_masks(lab, WALLISH, seg.FLOOR, seg.CEIL, crop)
    far = int(np.argmin([abs(f["floor"][0]) for f in faces])) if faces else None
    facing = (link_photo or {}).get("facing_walls") or []
    wall_of_face = {}
    if faces and facing:
        if len(facing) == len(faces): wall_of_face = {k: facing[k] for k in range(len(faces))}
        else: wall_of_face = {far: (link_photo or {}).get("primary_wall") or facing[0]}
    H = ceiling_m or 2.6
    out_windows, out_doors = [], []
    for kind, label, store in (("window", seg.WINDOW, out_windows), ("door", seg.DOOR, out_doors)):
        for c in components(L == label, min_px=max(400, L.size // 2500)):
            xc = (c["x0"] + c["x1"]) / 2; k = face_for(faces, xc)
            if k is None: continue
            f = faces[k]; fb, ft, yF, yC = vertical_fracs(f, xc, c["y1"], c["y0"]); ua, ub = u_fracs(f, c["x0"], c["x1"])
            wall = wall_of_face.get(k); length = face_len_m.get(wall) if wall else None
            ppm = ((yF - yC) / H) if yC is not None and yF - yC > 10 else None
            width_m, wsrc = None, None
            if ua is not None and ub is not None and length and not (f["partial_left"] or f["partial_right"]): width_m, wsrc = abs(ub - ua) * length, "face length from plan"
            elif ppm: width_m, wsrc = (c["x1"] - c["x0"]) / ppm, "fronto approx"
            rec = {"wall": wall, "face": k, "x_frac_along_wall": round((ua + ub) / 2, 3) if ua is not None and ub is not None else None, "width_m": round(width_m, 2) if width_m else None, "width_source": wsrc,
                   "bbox_frac": [round(c["x0"] / L.shape[1], 3), round(c["y0"] / L.shape[0], 3), round(c["x1"] / L.shape[1], 3), round(c["y1"] / L.shape[0], 3)], "partial": bool(f["partial_left"] or f["partial_right"])}
            if kind == "window":
                rec["sill_m"] = round(fb * H, 2) if fb is not None else None; rec["head_m"] = round(ft * H, 2) if ft is not None else None
                sub = (L == label)[c["y0"]:c["y1"], c["x0"]:c["x1"]]; m, hdiv = mullions(sub); rec["mullions"] = m; rec["h_divider"] = hdiv
                asp = (c["y1"] - c["y0"]) / max(1, c["x1"] - c["x0"])
                rec["style"] = "double-hung" if hdiv and asp >= 0.9 else ("slider" if m >= 1 and asp < 0.9 else ("fixed" if m == 0 and asp < 0.9 else ("casement" if m >= 1 else "unknown")))
                rec["height_source"] = "cross-ratio vs ceiling" if fb is not None else None
            else:
                rec["head_m"] = round(ft * H, 2) if ft is not None else None
                if fb is not None and fb * H >= 0.25 and (ft is None or ft * H >= 1.6):   # bottom edge well above the floor: this is glass, not a door
                    rec["sill_m"] = round(fb * H, 2); sub = (L == label)[c["y0"]:c["y1"], c["x0"]:c["x1"]]; m, hdiv = mullions(sub); rec["mullions"] = m; rec["h_divider"] = hdiv
                    asp = (c["y1"] - c["y0"]) / max(1, c["x1"] - c["x0"]); rec["style"] = "double-hung" if hdiv and asp >= 0.9 else ("slider" if m >= 1 and asp < 0.9 else ("fixed" if m == 0 and asp < 0.9 else "casement"))
                    rec["height_source"] = "cross-ratio vs ceiling"; rec["from_label"] = "door"; out_windows.append(rec); continue
                rec["kind"] = "closet" if (width_m or 0) > 1.3 else ("opening" if (c["y1"] >= L.shape[0] - 3 and (c["x1"] - c["x0"]) > 0.4 * L.shape[1]) else "hinged")
            store.append(rec)
    # bay: windows on two faces that share a corner
    faces_with_win = sorted({w["face"] for w in out_windows if w["face"] is not None})
    if any(b - a == 1 for a, b in zip(faces_with_win, faces_with_win[1:])):
        for w in out_windows: w["style_group"] = "bay_or_corner"
    # materials and colours
    try: mm, _ = matmatch.match(str(ldir), str(idx))
    except Exception as e: mm = {"error": str(e)}
    def top(name): return [x["id"] for x in (mm.get(name) or [])][:3]
    wall_px = I[L == seg.WALL]; lum = wall_px.mean(1) if len(wall_px) else np.array([])
    lit = wall_px[(lum > np.percentile(lum, 75)) & (lum < np.percentile(lum, 97))] if len(wall_px) > 200 else wall_px
    ceil_px = I[L == seg.CEIL]; cl = ceil_px.mean(1) if len(ceil_px) else np.array([]); ceil_lit = ceil_px[cl > np.percentile(cl, 70)] if len(ceil_px) > 200 else ceil_px
    floor_px = I[L == seg.FLOOR]
    # trim: wall pixels just above the floor line (baseboard); window frame: ring around window components
    trim = []
    if faces:
        for x in range(0, L.shape[1], 6):
            k = face_for(faces, x)
            if k is None: continue
            yF = faces[k]["floor"][0] * x + faces[k]["floor"][1]; ya, yb = int(yF - 26), int(yF - 8)
            if 0 <= ya and yb < L.shape[0]: col = I[ya:yb, x]; lb = L[ya:yb, x]; trim += list(col[lb == seg.WALL])
    ring = cv2.dilate((L == seg.WINDOW).astype(np.uint8), np.ones((7, 7), np.uint8)) - (L == seg.WINDOW).astype(np.uint8); frame_px = I[ring > 0]
    fdir, nlines = plank_direction(I, L == seg.FLOOR)
    conf = 0.2 + 0.3 * bool(faces) + 0.2 * bool(faces and faces[far]["ceil"]) + 0.15 * bool(wall_of_face) + 0.15 * bool(ceiling_m)
    return {"index": idx, "room": rg_room.get("name") if rg_room else None, "room_type": rg_room.get("type") if rg_room else None, "plan": (link_photo or {}).get("plan"), "plan_room": (link_photo or {}).get("room"),
            "facing_walls": facing, "primary_wall": (link_photo or {}).get("primary_wall"), "n_faces": len(faces), "far_face": far, "ceiling_m": ceiling_m, "windows": out_windows, "doors": out_doors,
            "materials": {"floor": top("floor"), "wall": top("wall"), "door": top("door"), "fixture": top("fixture"), "cabinet": top("fixture"), "counter": top("fixture"),
                          "ceiling": median_rgb(ceil_lit), "window_frame": median_rgb(frame_px), "trim": median_rgb(np.array(trim)) if trim else None},
            "colours": {"wall_rgb": median_rgb(lit), "ceiling_rgb": median_rgb(ceil_lit), "floor_rgb": median_rgb(floor_px), "trim_rgb": median_rgb(np.array(trim)) if trim else None},
            "floor_direction": fdir, "floor_lines": nlines, "confidence": round(conf, 2), "crop": [int(v) for v in crop]}

def run(ldir):
    ldir = pathlib.Path(ldir); link = json.load(open(ldir / "plan_link.json")) if (ldir / "plan_link.json").exists() else None
    rg = json.load(open(ldir / "roomgraph.json")) if (ldir / "roomgraph.json").exists() else {"rooms": []}
    room_of = {}
    for r in rg["rooms"]:
        for i in r["photos"]: room_of[i] = r
    link_photo = {p["index"]: p for p in (link or {}).get("photos", [])}
    # wall lengths per plan room (from the link's room records: width_m along N/S walls, depth_m along E/W)
    face_len = {}
    for r in (link or {}).get("rooms", []):
        key = (r.get("plan"), r.get("room")); face_len[key] = {"N": r.get("width_m"), "S": r.get("width_m"), "E": r.get("depth_m"), "W": r.get("depth_m")}
    photos = sorted(int(p.stem) for p in ldir.glob("[0-9][0-9].jpg")); facts = []; ceil_cache = {}
    for i in photos:
        r = room_of.get(i); rkey = r["name"] if r else None
        if rkey not in ceil_cache: ceil_cache[rkey] = structure_ceiling(ldir, r["photos"] if r else [i], r.get("name", "") if r else "")
        ceiling, _, csrc = ceil_cache[rkey]; lp = link_photo.get(i); fl = face_len.get((lp.get("plan"), lp.get("room")), {}) if lp else {}
        try: f = photo_facts(ldir, i, lp, r, ceiling, fl); f["ceiling_source"] = csrc
        except Exception as e: f = {"index": i, "error": f"{type(e).__name__}: {e}"}
        facts.append(f); print(f"[facts] {ldir.name} {i:02d} {f.get('room_type')}: faces {f.get('n_faces')} win {len(f.get('windows', []))} doors {len(f.get('doors', []))} floor {f.get('materials', {}).get('floor', [None])[:1]} dir {f.get('floor_direction')} {f.get('error', '')}", flush=True)
    # summaries per room type and building
    def agg(sel):
        s = {}
        sills = [w["sill_m"] for f in sel for w in f.get("windows", []) if w.get("sill_m") is not None and 0.1 <= w["sill_m"] <= 1.6]
        heads = [w["head_m"] for f in sel for w in f.get("windows", []) if w.get("head_m") is not None and 1.5 <= w["head_m"] <= 2.8]
        styles = [w["style"] for f in sel for w in f.get("windows", []) if w.get("style") not in (None, "unknown")]
        s["window"] = {"sill_m": round(float(np.median(sills)), 2) if sills else None, "head_m": round(float(np.median(heads)), 2) if heads else None, "style": max(set(styles), key=styles.count) if styles else None, "n": len(sills)}
        for surf in ("floor", "wall", "door", "cabinet"):
            votes = [f["materials"][surf][0] for f in sel if f.get("materials", {}).get(surf)]
            s[surf] = max(set(votes), key=votes.count) if votes else None
        for col in ("wall_rgb", "ceiling_rgb", "floor_rgb", "trim_rgb"):
            vals = [f["colours"][col] for f in sel if f.get("colours", {}).get(col)]
            s[col] = [int(v) for v in np.median(np.array(vals), 0)] if vals else None
        dirs = [f["floor_direction"] for f in sel if f.get("floor_direction") not in (None, "unknown")]
        s["floor_direction"] = max(set(dirs), key=dirs.count) if dirs else None
        ceils = [f["ceiling_m"] for f in sel if f.get("ceiling_m")]; s["ceiling_m"] = round(float(np.median(ceils)), 2) if ceils else None
        return s
    ok = [f for f in facts if "error" not in f]; by_type = {}
    for t in sorted({f.get("room_type") for f in ok if f.get("room_type")}): by_type[t] = agg([f for f in ok if f.get("room_type") == t])
    summary = {"by_room_type": by_type, "building": agg(ok), "wet": agg([f for f in ok if f.get("room_type") in ("kitchen", "bathroom", "laundry")]), "dry": agg([f for f in ok if f.get("room_type") not in ("kitchen", "bathroom", "laundry")])}
    out = {"listing": ldir.name, "photos": facts, "unit_summary": summary}; json.dump(out, open(ldir / "photo_facts.json", "w"), indent=1); return out

if __name__ == "__main__":
    for d in sys.argv[1:]: run(d)
