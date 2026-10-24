"""Plan-first room: the box comes from the floor plan's printed dimensions; each photo gives exact, perspective-corrected
textures for the wall faces it shows (homography from the face's image quad to the wall rectangle); unseen walls are flat
measured paint with a baseboard; windows are cut where the photo shows them. Nothing is generated.

    build.py <listing_dir> <room name from plan_link> [--link plan_link.json] [--ceiling 2.6] [--ppm 120]

Reads feasibility/listings/<lid>/plan_link.json (P1's contract) unless --link is given. Writes app/rooms/<name>.glb,
<name>_polished.glb, <name>.json, <name>_review.jpg."""
import sys, os, json, time, math, pathlib, argparse, tempfile
import numpy as np, cv2
from PIL import Image, ImageDraw
HERE = pathlib.Path(__file__).resolve().parent; APP = HERE.parents[1]; ROOMS = APP / "rooms"
sys.path.insert(0, str(APP / "pipeline2")); sys.path.insert(0, str(APP / "pipeline")); sys.path.insert(0, str(APP)); sys.path.insert(0, str(HERE))
import seg, geom

WALLISH = [seg.WALL, seg.WINDOW, seg.DOOR, seg.FIXTURE, seg.MIRROR]
ORDER = ["N", "E", "S", "W"]   # walking around the room clockwise as seen from above (x east, z south)

def wall_defs(W, D):
    """inside-left -> inside-right endpoints (x, z), outward normal, length, and the map from P1's fraction to inside-left u."""
    return {"N": {"a": (0.0, 0.0), "b": (W, 0.0), "n": (0.0, -1.0), "len": W, "u_of_frac": lambda f: f * W},
            "E": {"a": (W, 0.0), "b": (W, D), "n": (1.0, 0.0), "len": D, "u_of_frac": lambda f: f * D},
            "S": {"a": (W, D), "b": (0.0, D), "n": (0.0, 1.0), "len": W, "u_of_frac": lambda f: (1 - f) * W},
            "W": {"a": (0.0, D), "b": (0.0, 0.0), "n": (-1.0, 0.0), "len": D, "u_of_frac": lambda f: (1 - f) * D}}

def vggt_K(img_crop):
    """Camera matrix for the cropped photo from VGGT's single-image intrinsics (scaled from its 518-wide frame)."""
    try:
        import recon
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as t: Image.fromarray(img_crop).save(t.name, quality=92); P = recon.run([t.name])
        os.unlink(t.name); Ki = P["intrinsic"][0]; h, w = P["rgb"].shape[1:3]; sx = img_crop.shape[1] / w
        K = np.array([[Ki[0, 0] * sx, 0, img_crop.shape[1] / 2], [0, Ki[1, 1] * sx, img_crop.shape[0] / 2], [0, 0, 1]], float); return K, "vggt"
    except Exception as e:
        f = 0.62 * img_crop.shape[1]; return np.array([[f, 0, img_crop.shape[1] / 2], [0, f, img_crop.shape[0] / 2], [0, 0, 1]], float), f"default ({type(e).__name__})"

def paint_colours(img, lab, crop):
    x0, y0, x1, y1 = crop; I = img[y0:y1, x0:x1].reshape(-1, 3); L = lab[y0:y1, x0:x1].reshape(-1)
    wall = I[L == seg.WALL]
    if len(wall) < 100: wall = I
    lum = wall.mean(1); keep = (lum > np.percentile(lum, 80)) & (lum < np.percentile(lum, 96)); wall_c = np.median(wall[keep] if keep.sum() > 50 else wall, 0)   # the lit part of the wall: flat paint should read as a daylit wall, not a shaded corner
    floor = I[L == seg.FLOOR]; floor_c = np.median(floor, 0) if len(floor) > 100 else np.array([150, 110, 70])
    ceil = I[L == seg.CEIL]; cl = ceil.mean(1) if len(ceil) else None
    ceil_c = np.median(ceil[cl > np.percentile(cl, 80)], 0) if len(ceil) > 100 else np.maximum(wall_c, 235); ceil_c = np.maximum(ceil_c, wall_c)   # ceilings are never darker than the walls
    return wall_c.astype(np.uint8), floor_c.astype(np.uint8), ceil_c.astype(np.uint8)

def floor_patch(img, lab, crop):
    """A clean square of floor with the least lighting variation (no sun patches, no reflections), from the lower floor band."""
    x0, y0, x1, y1 = crop; L = lab[y0:y1, x0:x1]; I = img[y0:y1, x0:x1]; fm = (L == seg.FLOOR); ys, xs = np.where(fm)
    if len(ys) < 4000: return None
    y_lo, y_hi = int(np.percentile(ys, 40)), int(np.percentile(ys, 99)); med = np.median(I[fm], 0); best = None
    for size in (224, 176, 128, 96, 64, 40):
        for yb in range(y_hi, y_lo + size, -max(8, size // 4)):
            for xa in range(0, I.shape[1] - size, max(8, size // 4)):
                blk = fm[yb - size:yb, xa:xa + size]
                if blk.shape != (size, size) or blk.mean() < 0.93: continue
                px = I[yb - size:yb, xa:xa + size].reshape(-1, 3).astype(np.float32); lum = px.mean(1)
                score = lum.std() + 0.5 * abs(px.mean(0) - med).sum() / 3 - 0.02 * size   # flat lighting, typical colour, larger is better
                if best is None or score < best[0]: best = (score, I[yb - size:yb, xa:xa + size].copy())
        if best is not None: return best[1]
    return None

def build(listing_dir, room_name, link_path=None, ceiling=2.6, ppm=120, quiet=False):
    t0 = time.time(); d = pathlib.Path(listing_dir); link = json.load(open(link_path or d / "plan_link.json"))
    room = next((r for r in link["rooms"] if r["name"] == room_name), None)
    if room is None: raise SystemExit(f"room {room_name} not in link; have {[r['name'] for r in link['rooms']]}")
    W, D = float(room["width_m"]), float(room["depth_m"]); H = float(room.get("ceiling_m") or ceiling); walls = wall_defs(W, D)
    tex = {k: np.zeros((int(H * ppm), int(walls[k]["len"] * ppm), 3), np.uint8) for k in ORDER}; cov = {k: np.zeros(tex[k].shape[:2], np.float32) for k in ORDER}
    openings = {k: [] for k in ORDER}; prov = {k: [] for k in ORDER}; log = []
    for k in ORDER:   # plan openings first (defaults refined by photos later)
        for o in (room.get("walls", {}).get(k, {}) or {}).get("openings", []):
            u_a, u_b = sorted([walls[k]["u_of_frac"](o["from_frac"]), walls[k]["u_of_frac"](o["to_frac"])])
            if o["kind"] == "window": openings[k].append({"kind": "window", "u0": u_a, "u1": u_b, "bottom": 0.9, "top": 2.2, "src": "plan"})
            elif o["kind"] in ("door", "opening"): openings[k].append({"kind": "door", "u0": u_a, "u1": u_b, "bottom": 0.0, "top": 2.03, "src": "plan"})
    photos = [p for p in link["photos"] if p["index"] in room.get("photos", [])]
    wall_c = floor_c = ceil_c = None; fpatch = None; review_imgs = []
    for ph in photos:
        path = d / f"{ph['index']:02d}.jpg"; img = np.asarray(Image.open(path).convert("RGB")); lab, _ = seg.segment(path)
        crop = geom.letterbox(img); x0, y0, x1, y1 = crop; I = img[y0:y1, x0:x1]; L = lab[y0:y1, x0:x1]
        # exposure: listing photos are often dim; bring the bright wall/ceiling pixels to a daylit level (global gain, no colour change)
        ref = I[np.isin(L, [seg.WALL, seg.CEIL])]
        if len(ref) > 500:
            p90 = float(np.percentile(ref.mean(1), 90)); gain = float(np.clip(228.0 / max(p90, 1.0), 1.0, 1.45))
            if gain > 1.02: I = np.clip(I.astype(np.float32) * gain, 0, 255).astype(np.uint8); img = img.copy(); img[y0:y1, x0:x1] = I; log.append(f"photo {ph['index']}: exposure gain {gain:.2f}")
        faces, yf, yc = geom.faces_from_masks(lab, WALLISH, seg.FLOOR, seg.CEIL, crop)
        if wall_c is None: wall_c, floor_c, ceil_c = paint_colours(img, lab, crop)
        if fpatch is None: fpatch = floor_patch(img, lab, crop)
        if not faces: log.append(f"photo {ph['index']}: no wall/floor boundary found"); continue
        facing = ph.get("facing_walls") or [ph.get("primary_wall")]; primary = ph.get("primary_wall") or facing[len(facing) // 2]
        # far face = the one matched to the primary wall: the least sloped floor line
        far_idx = int(np.argmin([abs(f["floor"][0]) for f in faces]))
        pi = facing.index(primary) if primary in facing else len(facing) // 2
        assign = {far_idx: primary}
        for j in range(far_idx - 1, -1, -1):
            w_i = pi - (far_idx - j)
            if w_i >= 0: assign[j] = facing[w_i]
        for j in range(far_idx + 1, len(faces)):
            w_i = pi + (j - far_idx)
            if w_i < len(facing): assign[j] = facing[w_i]
        K, ksrc = vggt_K(I)
        far_wall = walls[primary]; far_f = faces[far_idx]
        far_partial = far_f["partial_left"] or far_f["partial_right"]
        seen, _ = geom.metric_positions(faces, K, far_idx, far_wall["len"]) if not far_partial else ({}, None)
        far_seen = None
        if far_partial or not seen:
            seen_c, side = geom.metric_from_corner(faces, K, far_idx, H)
            if seen_c: seen = {k_: v_ for k_, v_ in seen_c.items() if k_ != far_idx}; far_seen = (seen_c.get(far_idx), side); log.append(f"photo {ph['index']}: scale from the corner vertical (H={H}), far wall seen {far_seen[0] and round(far_seen[0], 2)} m from its {side} corner")
        rv = Image.fromarray(I.copy()); dr = ImageDraw.Draw(rv)
        for j, f in enumerate(faces):
            if j not in assign: continue
            wk = assign[j]; wd = walls[wk]; q = geom.quad(f, default_ceil_y=0.0)
            dr.polygon([tuple(p) for p in q], outline=(255, 60, 60) if j == far_idx else (60, 200, 255), width=3); dr.text((q[0][0] + 6, q[0][1] + 6), wk, fill=(255, 255, 0))
            if j == far_idx:
                u0, u1 = 0.0, wd["len"]
                if far_seen and far_seen[0] and np.isfinite(far_seen[0]) and 0.3 < far_seen[0] < wd["len"]:
                    # the far wall runs out of frame: the seen stretch ends at the real corner on `side`
                    u0, u1 = (wd["len"] - far_seen[0], wd["len"]) if far_seen[1] == "right" else (0.0, far_seen[0])
            else:
                s = seen.get(j)
                if s is None or not np.isfinite(s) or s <= 0.05: s = 0.5 * wd["len"]; note = "assumed half"
                else: note = f"metric {s:.2f} m"
                s = min(s, wd["len"])
                if j < far_idx: u0, u1 = wd["len"] - s, wd["len"]   # left of the far wall: its inside-right end is the shared corner
                else: u0, u1 = 0.0, s
                log.append(f"photo {ph['index']} face {j}->{wk}: {note}")
            Hm = geom.homography(q, (u0, u1, 0.0, H)); S = np.diag([ppm, ppm, 1.0]); M = S @ Hm
            out_w, out_h = tex[wk].shape[1], tex[wk].shape[0]
            warped = cv2.warpPerspective(I, M, (out_w, out_h), flags=cv2.INTER_LINEAR)
            qmask = np.zeros(I.shape[:2], np.uint8); cv2.fillConvexPoly(qmask, q.astype(np.int32), 255)
            # drop pixels of other surfaces (floor/ceiling spill) but keep everything that sits on the wall
            qmask[~np.isin(L, WALLISH)] = 0
            wm = cv2.warpPerspective(qmask, M, (out_w, out_h), flags=cv2.INTER_NEAREST) > 0
            res = float(np.linalg.norm(q[1] - q[0]) / max(u1 - u0, 1e-3))   # photo pixels per metre on this wall
            better = wm & (res > cov[wk])
            tex[wk][better] = warped[better]; cov[wk][better] = res
            prov[wk].append({"photo": ph["index"], "u0": round(u0, 2), "u1": round(u1, 2), "px_per_m": round(res, 1), "partial": bool(f["partial_left"] or f["partial_right"])})
            # openings from this photo on this wall
            lw = cv2.warpPerspective(L.astype(np.uint8), M, (out_w, out_h), flags=cv2.INTER_NEAREST)
            for kind_lab in (seg.WINDOW, seg.DOOR):
                m = ((lw == kind_lab) & wm).astype(np.uint8)
                n, cc, st, _ = cv2.connectedComponentsWithStats(m)
                for ci in range(1, n):
                    x, y, w, h, area = st[ci]
                    if area < 0.02 * out_w * out_h / 4 or w < 0.3 * ppm or h < 0.3 * ppm: continue
                    comp = (cc == ci); cols = np.where(comp.any(0))[0]
                    lows = np.array([np.where(comp[:, cx_])[0].max() for cx_ in cols]); highs = np.array([np.where(comp[:, cx_])[0].min() for cx_ in cols])
                    bottom = H - float(np.median(lows)) / ppm; top = H - float(np.median(highs)) / ppm
                    x, w = int(cols.min()), int(cols.max() - cols.min() + 1)
                    kind = "window" if bottom > 0.35 else "door"
                    if kind_lab == seg.DOOR and kind == "window" and bottom < 0.6: kind = "door"
                    if kind == "door":   # a 'door' that is mostly bright sky/view in its upper part is a window the segmenter mislabelled
                        upper = comp.copy(); upper[int(y + 0.5 * h):, :] = False; px = warped[upper]
                        if len(px) > 50 and px.mean() > 165 and px[:, 2].mean() >= px[:, 0].mean() - 5: kind = "window"; bottom = max(bottom, 0.6)
                    if kind == "door" and w / ppm > 1.3: kind = "opening"
                    o = {"kind": kind, "u0": x / ppm, "u1": (x + w) / ppm, "bottom": round(bottom, 2), "top": round(min(top, H - 0.05), 2), "src": f"photo {ph['index']}"}
                    # replace an overlapping plan opening, else add
                    rep = [p for p in openings[wk] if p["src"] == "plan" and min(p["u1"], o["u1"]) - max(p["u0"], o["u0"]) > 0]
                    for p in rep: openings[wk].remove(p)
                    openings[wk].append(o)
        review_imgs.append(rv); log.append(f"photo {ph['index']}: {len(faces)} faces, K {ksrc}, far={primary}")
    for k in ORDER:
        keep = []
        for o in openings[k]:
            if o["src"] == "plan":
                c0, c1 = int(max(0, o["u0"]) * ppm), int(min(walls[k]["len"], o["u1"]) * ppm); r0, r1 = int((H - o["top"]) * ppm), int((H - o["bottom"]) * ppm)
                seen_frac = float((cov[k][max(0, r0):max(1, r1), max(0, c0):max(1, c1)] > 0).mean()) if c1 > c0 and r1 > r0 else 0.0
                if seen_frac > 0.6: log.append(f"wall {k}: plan {o['kind']} at {o['u0']:.2f}-{o['u1']:.2f} m dropped, the photo shows wall there"); continue
            keep.append(o)
        openings[k] = keep
    if wall_c is None: wall_c, floor_c, ceil_c = np.array([235, 232, 225], np.uint8), np.array([160, 115, 70], np.uint8), np.array([245, 245, 243], np.uint8)
    # flat paint + baseboard where no photo landed
    bb_h = int(0.1 * ppm); base_c = (wall_c.astype(int) * 0.0 + np.array([235, 235, 235])).astype(np.uint8)
    for k in ORDER:
        un = cov[k] <= 0; tex[k][un] = wall_c
        rows = np.zeros_like(un); rows[-bb_h:, :] = True; tex[k][un & rows] = base_c
        # soft blend seams: slight blur of the coverage edge
    export(room_name, room, W, D, H, walls, tex, openings, prov, wall_c, floor_c, ceil_c, fpatch, photos, link, ppm, log, review_imgs, t0, quiet)

def export(name, room, W, D, H, walls, tex, openings, prov, wall_c, floor_c, ceil_c, fpatch, photos, link, ppm, log, review_imgs, t0, quiet):
    import trimesh
    from shapely.geometry import Polygon as SPoly, box as sbox
    scene = trimesh.Scene(); ROOMS.mkdir(exist_ok=True)
    def add(name_, verts, faces, uv, image):
        m = trimesh.Trimesh(vertices=np.asarray(verts, float), faces=np.asarray(faces, int), process=False)
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(image), baseColorFactor=[255, 255, 255, 255], metallicFactor=0.0, roughnessFactor=1.0)
        m.visual = trimesh.visual.TextureVisuals(uv=np.asarray(uv, float), material=mat); scene.add_geometry(m, node_name=name_, geom_name=name_)
    # floor / ceiling
    fl_img = None
    if fpatch is not None:
        # mirror-tile so seams vanish: 2x2 block of (p, fliplr, flipud, flip both)
        top = np.concatenate([fpatch, fpatch[:, ::-1]], axis=1); blk = np.concatenate([top, top[::-1]], axis=0)
        reps = (int(math.ceil(D * ppm / 2 / blk.shape[0])) + 1, int(math.ceil(W * ppm / 2 / blk.shape[1])) + 1)
        fl_img = np.tile(blk, (reps[0], reps[1], 1))[: int(D * ppm / 2), : int(W * ppm / 2)]
    else: fl_img = np.full((64, 64, 3), floor_c, np.uint8)
    add("pfloor", [[0, 0, 0], [W, 0, 0], [W, 0, D], [0, 0, D]], [[0, 2, 1], [0, 3, 2]], [[0, 1], [1, 1], [1, 0], [0, 0]], fl_img)
    add("pceil", [[0, H, 0], [W, H, 0], [W, H, D], [0, H, D]], [[0, 1, 2], [0, 2, 3]], [[0, 1], [1, 1], [1, 0], [0, 0]], np.full((16, 16, 3), ceil_c, np.uint8))
    wins_json, doors_json, other_json = [], [], []
    poly = [[0.0, 0.0], [W, 0.0], [W, D], [0.0, D]]
    if not SPoly(poly).exterior.is_ccw: poly = poly[::-1]
    edges = []
    for i in range(4):
        a, b = np.array(poly[i]), np.array(poly[(i + 1) % 4]); dv = b - a; L = float(np.linalg.norm(dv)); dv = dv / L; nn = np.array([dv[1], -dv[0]])
        if nn @ (0.5 * (a + b) - np.array([W / 2, D / 2])) < 0: nn = -nn
        edges.append({"a": a.tolist(), "b": b.tolist(), "dir": dv.tolist(), "n": nn.tolist(), "offset": float(nn @ a), "len": L, "inferred": False, "axis": 0 if abs(nn[0]) > abs(nn[1]) else 1})
    def edge_of(k):
        a, b = np.array(walls[k]["a"]), np.array(walls[k]["b"]); mid = 0.5 * (a + b)
        return min(range(4), key=lambda i: np.linalg.norm(0.5 * (np.array(edges[i]["a"]) + np.array(edges[i]["b"])) - mid))
    for k in ORDER:
        wd = walls[k]; a, b = np.array(wd["a"]), np.array(wd["b"]); L = wd["len"]; dv = (b - a) / L; n = np.array(wd["n"])
        rect = sbox(0, 0, L, H); holes = []
        for o in openings[k]:
            if o["kind"] != "window": continue
            u0, u1 = max(0.02, o["u0"]), min(L - 0.02, o["u1"]); vb, vt = max(0.05, o["bottom"]), min(H - 0.05, o["top"])
            if u1 - u0 < 0.2 or vt - vb < 0.2: continue
            holes.append(sbox(u0, vb, u1, vt))
        wall_poly = rect
        for h_ in holes: wall_poly = wall_poly.difference(h_)
        polys = [wall_poly] if wall_poly.geom_type == "Polygon" else list(wall_poly.geoms)
        V3, F3, UV = [], [], []
        for pg in polys:
            v2, f2 = trimesh.creation.triangulate_polygon(pg, engine="earcut") if hasattr(trimesh.creation, "triangulate_polygon") else (None, None)
            base = len(V3)
            for (u, v) in v2: V3.append([a[0] + dv[0] * u, v, a[1] + dv[1] * u]); UV.append([u / L, v / H])
            for f in f2:
                tri = [base + int(i) for i in f]
                p0, p1, p2 = [np.array(V3[i]) for i in tri]; nrm = np.cross(p1 - p0, p2 - p0)
                if nrm @ np.array([n[0], 0, n[1]]) > 0: tri = [tri[0], tri[2], tri[1]]   # faces point inward (toward the room)
                F3.append(tri)
        add(f"pwall_{k}", V3, F3, UV, tex[k][::-1].copy())   # texture row 0 is the ceiling; UV v=0 is the floor -> flip
        ei = edge_of(k); ea = np.array(edges[ei]["a"]); edir = np.array(edges[ei]["dir"])
        for o in openings[k]:
            c2 = a + dv * 0.5 * (o["u0"] + o["u1"]); s_mid = float((c2 - ea) @ edir); half = 0.5 * (o["u1"] - o["u0"])
            rec = {"kind": o["kind"], "edge": ei, "s0": round(s_mid - half, 3), "s1": round(s_mid + half, 3), "sill_m": round(o["bottom"], 3), "height_m": round(o["top"] - o["bottom"], 3), "width_m": round(o["u1"] - o["u0"], 3),
                   "center": [round(float(c2[0]), 3), round(0.5 * (o["top"] + o["bottom"]), 3), round(float(c2[1]), 3)], "normal": [float(n[0]), 0.0, float(n[1])], "src": o["src"], "wall": k}
            (wins_json if o["kind"] == "window" else doors_json if o["kind"] == "door" else other_json).append(rec)
            if o["kind"] == "window":   # a faint pane so the hole reads as glass from inside
                u0, u1, vb, vt = o["u0"], o["u1"], o["bottom"], o["top"]; off = np.array([n[0], 0, n[1]]) * 0.01
                vs = [[a[0] + dv[0] * u0, vb, a[1] + dv[1] * u0], [a[0] + dv[0] * u1, vb, a[1] + dv[1] * u1], [a[0] + dv[0] * u1, vt, a[1] + dv[1] * u1], [a[0] + dv[0] * u0, vt, a[1] + dv[1] * u0]]
                vs = (np.array(vs) + off).tolist(); pane = np.full((8, 8, 4), [180, 215, 255, 90], np.uint8)
                m = trimesh.Trimesh(vertices=vs, faces=[[0, 1, 2], [0, 2, 3], [0, 2, 1], [0, 3, 2]], process=False); m.visual = trimesh.visual.TextureVisuals(uv=[[0, 0], [1, 0], [1, 1], [0, 1]], material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(pane, "RGBA"), baseColorFactor=[255, 255, 255, 255]))
                scene.add_geometry(m, node_name=f"pglass_{k}_{len(wins_json)}", geom_name=f"pglass_{k}_{len(wins_json)}")
    glb = ROOMS / f"{name}.glb"; scene.export(glb); import shutil; shutil.copy(glb, ROOMS / f"{name}_polished.glb")
    meta = {"name": name, "source": "wallwrap", "listing": pathlib.Path(link.get("listing", "")).name or None, "plan": room.get("plan"), "plan_room": room.get("room"), "type": room.get("type"),
            "ceiling_m": H, "width_m": W, "depth_m": D, "area_m2": round(W * D, 2), "polygon": poly, "edges": edges, "windows": wins_json, "doors": doors_json, "openings_other": other_json,
            "bounds": [[0.0, 0.0, 0.0], [W, H, D]], "cameras": [], "photos": [p["index"] for p in photos], "texture_provenance": prov, "flat_walls": [k for k in ORDER if not prov[k]],
            "paint_rgb": wall_c.tolist(), "floor_rgb": floor_c.tolist(), "ceil_rgb": ceil_c.tolist(), "build_s": round(time.time() - t0, 1), "log": log}
    json.dump(meta, open(ROOMS / f"{name}.json", "w"), indent=1)
    # review sheet: photos with quads, then the four wall textures
    rows = [im for im in review_imgs]; strips = []
    for k in ORDER:
        t = Image.fromarray(tex[k]); t.thumbnail((1400, 220)); strips.append((k, t))
    Wd = max([im.width for im in rows] + [1400]); Hd = sum(im.height for im in rows) + sum(t.height + 18 for _, t in strips)
    sheet = Image.new("RGB", (Wd, Hd), (20, 20, 20)); y = 0; dr = ImageDraw.Draw(sheet)
    for im in rows: sheet.paste(im, (0, y)); y += im.height
    for k, t in strips: dr.text((4, y + 2), f"wall {k}  {walls[k]['len']:.2f} m  {'photo' if prov[k] else 'flat'}  openings {[(o['kind'], round(o['u0'], 2), round(o['u1'], 2)) for o in openings[k]]}", fill=(255, 255, 0)); sheet.paste(t, (0, y + 16)); y += t.height + 18
    sheet.save(ROOMS / f"{name}_review.jpg", quality=85)
    if not quiet: print(f"[wallwrap] {name}: {W}x{D}x{H} m, photo walls {[k for k in ORDER if prov[k]]}, flat {meta['flat_walls']}, windows {len(wins_json)}, doors {len(doors_json)}, {meta['build_s']}s | " + "; ".join(log))
    return meta

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("listing_dir"); ap.add_argument("room"); ap.add_argument("--link"); ap.add_argument("--ceiling", type=float, default=2.6); ap.add_argument("--ppm", type=int, default=120)
    a = ap.parse_args(); build(a.listing_dir, a.room, a.link, a.ceiling, a.ppm)
