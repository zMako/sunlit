"""Up-axis + front-direction detection for the designer GLBs -> orient.json.

Stages (python: feasibility/.venv/bin/python app/furnish/designer/orient.py <stage>):
  pts     sample surface points of models/<id>.glb (uncompressed, same frame as models_opt) -> orient/cache/pts/<id>.npz
  feat    geometric features per item and per up-candidate -> orient/cache/feat.json
  decide  deterministic up + front decision (+ confidence) -> orient/cache/geo.json
  clip    renders (orient/render.html) of the geometric top-2 ups x 4 yaws for low-confidence items + CLIP scores -> cache/clip.json
  final   geometry + CLIP tie-break -> orient.json
  sheets  contact sheets (hero | before | after) -> orient/sheets

Conventions (see REPORT.md): "up" = axis of the CURRENT file that must point to +y. front_yaw_deg = yaw about +y applied AFTER the up-fix
that brings the model's front to local +z.  q = q_yaw(front_yaw_deg about +Y) * q_up.
"""
import sys, os, json, math, pathlib, time, random, collections
import numpy as np

H = pathlib.Path(__file__).resolve().parent
APP = H.parent.parent
OUT = H / "orient"; CACHE = OUT / "cache"; PTS = CACHE / "pts"
CAT = APP / "furnish" / "catalog.json"
sys.path.insert(0, str(H))
NPTS = 24000

def items():
    c = json.load(open(CAT)); it = c["items"] if isinstance(c, dict) else c
    return [i for i in it if i["id"].startswith("dsg-") and i.get("model_glb") and (H / "models_opt" / f"{i['id']}.glb").exists()]

# ---------------------------------------------------------------- rotation maths
# R_up maps the named axis of the current file to +y (right-handed, same matrices as three.js makeRotationX/Z)
def rx(a):
    c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
def ry(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
def rz(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
D = math.pi / 180
UP_EULER = {"y": (0, 0, 0), "-y": (180, 0, 0), "z": (-90, 0, 0), "-z": (90, 0, 0), "x": (0, 0, 90), "-x": (0, 0, -90)}   # (rx, ry, rz) degrees, single-axis each
def R_up(u):
    a, _, c = UP_EULER[u]; return rx(a * D) if a else (rz(c * D) if c else np.eye(3))
def R_full(u, yaw): return ry(yaw * D) @ R_up(u)
AXV = {"x": np.array([1., 0, 0]), "y": np.array([0., 1, 0]), "z": np.array([0., 0, 1])}
def axvec(u): return -AXV[u[1]] if u.startswith("-") else AXV[u]
for _u in UP_EULER: assert np.allclose(R_up(_u) @ axvec(_u), [0, 1, 0]), _u

# ---------------------------------------------------------------- stage: pts
def _pts_one(iid):
    out = PTS / f"{iid}.npz"
    if out.exists(): return iid, True
    import trimesh
    try:
        sc = trimesh.load(str(H / "models" / f"{iid}.glb"), force="scene")
        ms = []; pc = []
        for node in sc.graph.nodes_geometry:
            T, g = sc.graph[node]; geo = sc.geometry[g]
            if not hasattr(geo, "faces") or len(geo.faces) == 0:
                pc.append(trimesh.transformations.transform_points(geo.vertices, T)); continue
            v = trimesh.transformations.transform_points(geo.vertices, T); ms.append((v, geo.faces))
        if not ms:   # point-cloud-only GLB (faces lost in conversion): use the vertices
            V = np.concatenate(pc); p = V[np.random.default_rng(0).choice(len(V), NPTS)]
            np.savez_compressed(out, p=p.astype(np.float32), n=np.zeros_like(p, dtype=np.float16), v=V.astype(np.float32), area=0.0, nf=0)
            return iid, True
        V = np.concatenate([m[0] for m in ms]); F = np.concatenate([m[1] + o for m, o in zip(ms, np.cumsum([0] + [len(m[0]) for m in ms])[:-1])])
        mesh = trimesh.Trimesh(V, F, process=False)
        p, fi = trimesh.sample.sample_surface(mesh, NPTS, seed=0)
        n = mesh.face_normals[fi]
        vs = V[np.random.default_rng(0).choice(len(V), min(len(V), 8000), replace=False)]
        np.savez_compressed(out, p=p.astype(np.float32), n=n.astype(np.float16), v=vs.astype(np.float32), area=float(mesh.area), nf=len(F))
        return iid, True
    except Exception as e:
        print("pts fail", iid, e, flush=True); return iid, False

def stage_pts():
    from multiprocessing import Pool
    ids = [i["id"] for i in items()]
    todo = [i for i in ids if not (PTS / f"{i}.npz").exists()]
    # big files first so the pool tail is short
    todo.sort(key=lambda i: -(H / "models" / f"{i}.glb").stat().st_size)
    print(len(ids), "items,", len(todo), "to sample", flush=True)
    t = time.time(); ok = 0
    with Pool(12, maxtasksperchild=40) as pool:
        for k, (iid, good) in enumerate(pool.imap_unordered(_pts_one, todo, chunksize=1)):
            ok += good
            if k % 200 == 0: print(k, round(time.time() - t), "s", flush=True)
    print("done", ok, "/", len(todo), round(time.time() - t), "s")

# ---------------------------------------------------------------- stage: feat
G = 48
def grid_of(p, lo, hi, n=G):
    q = np.clip(((p - lo) / np.maximum(hi - lo, 1e-9) * n).astype(int), 0, n - 1)
    g = np.zeros((n, n, n), bool); g[q[:, 0], q[:, 1], q[:, 2]] = True; return g
def dilate(g):
    d = g.copy()
    for ax in range(3):
        d |= np.roll(g, 1, ax) | np.roll(g, -1, ax)
    return d
def sym_score(g, gd, ax):
    f = np.flip(g, ax); fd = np.flip(gd, ax)
    return 0.5 * ((g & fd).sum() / max(g.sum(), 1) + (f & gd).sum() / max(f.sum(), 1))
def occ2d(p2, lo2, hi2, n=24):
    if len(p2) == 0: return 0.0
    q = np.clip(((p2 - lo2) / np.maximum(hi2 - lo2, 1e-9) * n).astype(int), 0, n - 1)
    return len(set(map(tuple, q))) / (n * n)
def hull_area_and_inside(p2, c2):
    if len(p2) < 3: return 0.0, -1.0
    try:
        from scipy.spatial import ConvexHull
        h = ConvexHull(p2); eq = h.equations   # a x + b y + c <= 0 inside
        m = -(eq[:, :2] @ c2 + eq[:, 2]).min()   # >0 inside: distance to nearest edge
        return float(h.volume), float(m)
    except Exception: return 0.0, -1.0

def _feat_one(iid):
    z = np.load(PTS / f"{iid}.npz"); p = z["p"].astype(np.float64)
    lo, hi = p.min(0), p.max(0); ext = hi - lo; ctr = (lo + hi) / 2; p = p - ctr; lo, hi = lo - ctr, hi - ctr
    g = grid_of(p, lo, hi); gd = dilate(g)
    sym = [float(sym_score(g, gd, a)) for a in range(3)]
    com = p.mean(0)
    per = {}
    for u in ("x", "-x", "y", "-y", "z", "-z"):
        a = "xyz".index(u[-1]); s = -1 if u.startswith("-") else 1
        hgt = s * p[:, a]; hl, hh = -ext[a] / 2, ext[a] / 2; t = (hgt - hl) / max(ext[a], 1e-9)   # 0 bottom .. 1 top
        o = [b for b in range(3) if b != a]; p2 = p[:, o]; lo2, hi2 = lo[o], hi[o]
        bot = occ2d(p2[t < 0.10], lo2, hi2); mid = occ2d(p2[(t > 0.4) & (t < 0.6)], lo2, hi2); top = occ2d(p2[t > 0.9], lo2, hi2)
        con = p2[t < 0.03]; ha, inside = hull_area_and_inside(con, com[o])
        fa = float(np.prod(ext[o]))
        # upper-mass offset along the two horizontal axes (normalised by extent): backrest side
        up55 = p[t > 0.55]
        off = [float((up55[:, b].mean() if len(up55) else 0) / max(ext[b], 1e-9)) for b in o]
        per[u] = {"bot": bot, "mid": mid, "top": top, "con_occ": occ2d(con, lo2, hi2), "hull": ha / max(fa, 1e-12), "inside": inside / max(math.sqrt(fa), 1e-9),
                  "com_t": float((s * com[a] - hl) / max(ext[a], 1e-9)), "frac_low": float((t < 0.5).mean()), "off": off, "haxes": ["xyz"[b] for b in o]}
    # flat outer faces (for cabinets): occupancy of the outermost 2% slab on each of the 6 sides, 2D grid of the face
    faces = {}
    for u in ("x", "-x", "y", "-y", "z", "-z"):
        a = "xyz".index(u[-1]); s = -1 if u.startswith("-") else 1; o = [b for b in range(3) if b != a]
        t = (s * p[:, a] + ext[a] / 2) / max(ext[a], 1e-9)
        faces[u] = occ2d(p[t > 0.98][:, o], lo[o], hi[o])
    return iid, {"ext": [float(e) for e in ext], "sym": sym, "per": per, "faces": faces, "nf": int(z["nf"])}

def stage_feat():
    from multiprocessing import Pool
    ids = [i["id"] for i in items()]
    t = time.time(); F = {}
    with Pool(14) as pool:
        for iid, f in pool.imap_unordered(_feat_one, ids, chunksize=8): F[iid] = f
    json.dump(F, open(CACHE / "feat.json", "w")); print("feat", len(F), round(time.time() - t), "s")

# ---------------------------------------------------------------- stage: decide (geometry only)
from common import ASPECT
SEAT = {"sofa", "armchair", "dining_chair", "desk_chair", "bench", "bed", "ottoman", "bar_stool"}
CASE = {"bookcase", "dresser", "wardrobe", "tv_bench", "nightstand"}
UPS = ("y", "z", "-z", "x", "-x", "-y")

def yaw_for(front_vec):
    """front_vec: horizontal unit vector (post-up frame) of the model's front -> yaw (deg) that maps it to +z."""
    for yaw in (0, 90, 180, 270):
        if np.allclose(ry(yaw * D) @ front_vec, [0, 0, 1], atol=1e-6): return yaw
    raise ValueError(front_vec)

def up_scores(f, it, zup):
    cat = it["category"]; ext = f["ext"]; sym = f["sym"]; sc = {}; why = {}
    srt = sorted(sym, reverse=True)
    for u in UPS:
        a = "xyz".index(u[-1]); o = [b for b in range(3) if b != a]; pu = f["per"][u]; w = []
        s = {"y": 1.0, "z": 0.35 if not zup else -0.2, "-z": 0.35 if zup else -0.2, "x": -0.5, "-x": -0.5, "-y": -0.7}[u]; w.append(("prior", s))
        # mirror symmetry: the width axis (best mirror plane) is never up; two symmetric axes => they are horizontal
        if sym[a] == srt[0] and sym[a] - srt[1] > 0.06: v = -0.9; w.append(("sym_width", v)); s += v
        so = sorted(sym[b] for b in o)
        if so[0] > 0.80 and so[0] - sym[a] > 0.06: v = 0.6; w.append(("sym_rot", v)); s += v
        # category aspect prior: height / sqrt(w d)
        h = ext[a]; wd = math.sqrt(max(ext[o[0]] * ext[o[1]], 1e-9))
        if cat in ASPECT and cat != "pendant_lamp":
            v = -0.45 * abs(math.log(max(h, 1e-6) / wd / ASPECT[cat])); w.append(("aspect", v)); s += v
        # support: thin bottom (legs / base) vs mid section, and stable support polygon
        if cat == "pendant_lamp":   # hangs: cord/canopy at the top (thin), shade at the bottom
            v = 0.8 * (pu["bot"] - pu["top"]) / max(pu["bot"] + pu["top"], 1e-3); w.append(("pendant", v)); s += v
        elif cat not in ("mirror", "rug"):
            ratio = pu["bot"] / max(pu["mid"], 1e-3)
            v = 0.25 * (0.5 - min(ratio, 1.5)); w.append(("thin_base", v)); s += v
            v = 0.15 if pu["inside"] > 0.02 else -0.25; w.append(("stable", v)); s += v
        if cat == "rug":   # thin dimension is up
            v = 1.0 if h == min(ext) else -1.0; w.append(("rug_thin", v)); s += v
        if cat == "mirror":   # wall mirrors: tall, thin dimension horizontal
            v = -1.0 if h == min(ext) else 0.0; w.append(("mirror", v)); s += v
        sc[u] = s; why[u] = w
    return sc, why

def front_for(f, it, up):
    """returns (front_yaw_deg, confidence, method, flags) in the post-up frame."""
    cat = it["category"]; a = "xyz".index(up[-1]); R = R_up(up); pu = f["per"][up]; o = [b for b in range(3) if b != a]
    ext = f["ext"]; flags = []
    def hvec(b, sign):   # original axis b with sign -> post-up horizontal unit vector
        v = np.zeros(3); v[b] = sign; return np.round(R @ v)
    # long horizontal side -> x (the viewer stretches to width along x); used for symmetric items and as fallback
    lw = it.get("width_m") or 0; ld = it.get("depth_m") or 0
    long_b = o[0] if ext[o[0]] >= ext[o[1]] else o[1]; short_b = o[1] if long_b == o[0] else o[0]
    def yaw_long_x(): return yaw_for(hvec(short_b, 1))   # front along the short side -> long side ends up on x
    if cat in SEAT or (cat == "other" and max(abs(x) for x in pu["off"]) > 0.08):
        offs = pu["off"]; k = int(np.argmax(np.abs(offs))); m = abs(offs[k])
        if m < 0.004:
            return yaw_long_x(), 0.25, "seat_no_backrest_long_x", ["no_backrest_signal"]
        if m < 0.015:   # weak but usable: low backrests (bar stools, poufs with a lip); CLIP was worse than this on eyeballed sheets
            back = hvec(o[k], 1 if offs[k] > 0 else -1); return yaw_for(-back), 0.35, "seat_backrest_mass_weak", ["weak_backrest_signal"]
        back = hvec(o[k], 1 if offs[k] > 0 else -1); yaw = yaw_for(-back)
        other = abs(offs[1 - k]); conf = min(0.95, 0.35 + 5 * (m - other))
        if cat == "other": conf = min(conf, 0.6); flags.append("category_other")
        return yaw, round(max(conf, 0.2), 2), "seat_backrest_mass", flags
    if cat in CASE or cat == "desk":
        fa = f["faces"]; s_pos = fa[["x", "y", "z"][short_b]]; s_neg = fa["-" + "xyz"[short_b]]
        if cat == "desk":
            return yaw_long_x(), 0.4, "desk_long_side_x", ["front_unknown"]
        d = s_pos - s_neg
        if abs(d) < 0.08: return yaw_long_x(), 0.3, "case_symmetric", ["symmetric"]
        back = hvec(short_b, 1 if d > 0 else -1)   # flattest / fullest outer face = back panel
        return yaw_for(-back), round(min(0.85, 0.4 + 1.5 * abs(d)), 2), "case_flat_back", flags
    if cat == "mirror":
        thin_b = o[0] if ext[o[0]] <= ext[o[1]] else o[1]
        return yaw_for(hvec(thin_b, 1)), 0.5, "mirror_thin_depth", ["symmetric", "mirror_face_unknown"]
    return yaw_long_x(), 0.9, "symmetric_long_x", ["symmetric"]

def stage_decide():
    F = json.load(open(CACHE / "feat.json")); its = items(); G = {}
    for it in its:
        iid = it["id"]; f = F[iid]
        zj = H / "models" / f"{iid}.json"; zup = bool(json.load(open(zj)).get("zup")) if zj.exists() else False
        sc, why = up_scores(f, it, zup)
        rank = sorted(sc, key=lambda u: -sc[u]); u1, u2 = rank[0], rank[1]
        margin = sc[u1] - sc[u2]; conf = round(min(0.97, 0.35 + 0.5 * margin), 2)
        # second best of a different axis is the real alternative (u vs -u share all dims-based cues)
        yaw, fconf, fmeth, flags = front_for(f, it, u1)
        if f["nf"] == 0: flags = flags + ["points_only_model"]
        G[iid] = {"up": u1, "up2": u2, "up_conf": conf, "scores": {u: round(v, 3) for u, v in sc.items()}, "why": {u: [(k, round(v, 2)) for k, v in why[u]] for u in (u1, u2)},
                  "front_yaw_deg": yaw, "front_conf": fconf, "front_method": fmeth, "flags": flags, "zup_applied": zup, "category": it["category"], "brand": it["brand"]}
    json.dump(G, open(CACHE / "geo.json", "w"), indent=0)
    c = collections.Counter(g["up"] for g in G.values()); print("up", c)
    print("up conf<0.7", sum(g["up_conf"] < 0.7 for g in G.values()), " front conf<0.7", sum(g["front_conf"] < 0.7 for g in G.values()))
    print(collections.Counter((g["up"], g["category"]) for g in G.values() if g["up"] != "y").most_common(25))

# ---------------------------------------------------------------- stage: clip (tie-break among the geometric top-2)
CAT_WORD = {"dining_chair": "chair", "desk_chair": "office chair", "bar_stool": "bar stool", "pendant_lamp": "pendant lamp", "table_lamp": "table lamp", "floor_lamp": "floor lamp",
            "coffee_table": "coffee table", "side_table": "side table", "dining_table": "dining table", "tv_bench": "tv bench", "plant_pot": "plant pot"}
EMB = CACHE / "emb.npz"
def _clip():
    sys.path.insert(0, str(APP / "furnish")); import matmatch; return matmatch
def embed_paths(paths):
    from PIL import Image
    cache = dict(np.load(EMB)) if EMB.exists() else {}
    todo = [str(p) for p in paths if str(p) not in cache and pathlib.Path(p).exists()]
    if todo:
        mm = _clip(); t = time.time()
        for i in range(0, len(todo), 512):
            E = mm.embed([Image.open(p) for p in todo[i:i + 512]])
            for p, e in zip(todo[i:i + 512], E): cache[p] = e.astype(np.float32)
        np.savez(EMB, **cache); print("embedded", len(todo), round(time.time() - t), "s", flush=True)
    return cache
def embed_texts(texts):
    mm = _clip(); m, pre, dev, torch = mm.clip_model(); import open_clip
    tok = open_clip.get_tokenizer("ViT-B-32")
    with torch.no_grad():
        f = m.encode_text(tok(texts).to(dev)).float(); f = f / f.norm(dim=-1, keepdim=True)
    return f.cpu().numpy()

def clip_jobs(G):
    jobs = {}
    for iid, g in G.items():
        cs = set()
        if g["up_conf"] < 0.7: cs |= {(u, y) for u in (g["up"], g["up2"]) for y in (0, 90, 180, 270)}
        if g["front_conf"] < 0.7 and g["front_method"] not in ("desk_long_side_x", "mirror_thin_depth"): cs |= {(g["up"], y) for y in (0, 90, 180, 270)}
        if cs: jobs[iid] = sorted(cs)
    return jobs

def stage_clip(render="1"):
    G = json.load(open(CACHE / "geo.json")); its = {i["id"]: i for i in items()}
    jobs = clip_jobs(G)
    print("clip items", len(jobs), "shots", sum(len(v) for v in jobs.values()), flush=True)
    if render == "1": render_jobs(jobs, n_pages=10, size=192)
    paths = [rpath(i, *c) for i, cs in jobs.items() for c in cs] + [THUMB / f"{i}.jpg" for i in jobs if (THUMB / f"{i}.jpg").exists()]
    E = embed_paths(paths)
    words = {i: CAT_WORD.get(its[i]["category"], its[i]["category"].replace("_", " ")) if its[i]["category"] != "other" else its[i]["name"][:50] for i in jobs}
    uw = sorted(set(words.values())); TE = dict(zip(uw, embed_texts([f"a photo of a {w}" for w in uw])))
    C = {}
    for iid, cs in jobs.items():
        hp = str(THUMB / f"{iid}.jpg"); he = E.get(hp); te = TE[words[iid]]
        sc = {}
        for c in cs:
            e = E.get(str(rpath(iid, *c)))
            if e is None: continue
            sc[f"{c[0]}|{c[1]}"] = {"img": float(e @ he) if he is not None else None, "txt": float(e @ te)}
        C[iid] = sc
    json.dump(C, open(CACHE / "clip.json", "w"))
    print("clip scored", len(C))

# ---------------------------------------------------------------- stage: final (geometry + CLIP tie-break) -> orient.json
FRONT_CATS = SEAT | CASE
DELTA_UP, DELTA_FRONT, W_TXT = 0.010, 0.008, 0.5
def cscore(v):
    if v is None: return None
    return (v["img"] if v["img"] is not None else 0.0) + (W_TXT if v["img"] is not None else 1.0) * v["txt"]

def finalize_one(iid, g, c, f, it):
    up, uconf, umeth = g["up"], g["up_conf"], "geometry"; flags = list(g["flags"])
    yaw, fconf, fmeth = g["front_yaw_deg"], g["front_conf"], g["front_method"]
    has_hero = (THUMB / f"{iid}.jpg").exists()
    S = {}
    for k, v in (c or {}).items():
        u, y = k.split("|"); S[(u, int(y))] = cscore(v)
    if uconf < 0.7 and S:
        su = {u: max([s for (uu, y), s in S.items() if uu == u] or [-9]) for u in (g["up"], g["up2"])}
        d = su[g["up2"]] - su[g["up"]]
        if d > DELTA_UP:
            up = g["up2"]; umeth = "clip_tiebreak" + ("" if has_hero else "_text"); uconf = round(min(0.85, 0.45 + 8 * d), 2)
            yaw, fconf, fmeth, fl = front_for(f, it, up); flags = [x for x in fl] + (["points_only_model"] if f["nf"] == 0 else [])
        else:
            umeth = "geometry+clip_agree" if d < -DELTA_UP else "geometry(clip_undecided)"
            uconf = round(min(0.9, uconf + (min(0.3, 8 * -d) if d < 0 else 0)), 2)
    needs_front = it["category"] in FRONT_CATS or fmeth == "seat_backrest_mass"
    if needs_front and fconf < 0.7 and all((up, y) in S for y in (0, 90, 180, 270)):
        if fmeth == "seat_no_backrest_long_x": pass   # CLIP 'best view' choice was mostly wrong on eyeballed sheets: keep the long side on x
        else:
            opp = (yaw + 180) % 360; d = S[(up, opp)] - S[(up, yaw)]
            # eyeballing showed CLIP front/back flips against a backrest-mass decision were mostly wrong (grey renders of front and back
            # look alike to CLIP): never flip, only lower the confidence when CLIP disagrees
            if d > DELTA_FRONT and fmeth == "seat_backrest_mass_weak":   # weak geometry (thin shell backs): here CLIP was right on the sheets
                yaw = opp; fmeth = fmeth + "+clip_flip"; fconf = round(min(0.6, 0.35 + 8 * d), 2)
            elif d > DELTA_FRONT: fmeth = fmeth + "+clip_disagrees"; fconf = round(max(0.2, fconf - 0.15), 2); flags.append("front_clip_disagrees")
            elif d < -DELTA_FRONT: fmeth = fmeth + "+clip_agree"; fconf = round(min(0.85, fconf + 8 * -d), 2)
    if not has_hero: flags.append("no_hero_photo")
    if up != "y" and it.get("dims_source") == "glb_bbox": flags.append("catalog_dims_from_old_bbox")
    # dims after the transform (metres): width x, depth z, height y, from the sampled points
    P = np.load(PTS / f"{iid}.npz")["p"].astype(np.float64) @ R_full(up, yaw).T
    e = P.max(0) - P.min(0)
    conf = round(min(uconf, fconf) if needs_front else uconf, 2)
    return {"up": up, "front_yaw_deg": int(yaw), "method": f"up:{umeth}; front:{fmeth}", "confidence": conf, "up_confidence": uconf, "front_confidence": fconf,
            "flags": sorted(set(flags)), "dims_after_m": [round(float(e[0]), 3), round(float(e[2]), 3), round(float(e[1]), 3)]}

def stage_final():
    G = json.load(open(CACHE / "geo.json")); C = json.load(open(CACHE / "clip.json")) if (CACHE / "clip.json").exists() else {}
    F = json.load(open(CACHE / "feat.json")); its = {i["id"]: i for i in items()}
    O = {iid: finalize_one(iid, G[iid], C.get(iid), F[iid], its[iid]) for iid in sorted(G)}
    json.dump(O, open(H / "orient.json", "w"), indent=0)
    print("up", collections.Counter(o["up"] for o in O.values()))
    print("changed up vs geometry", sum(O[i]["up"] != G[i]["up"] for i in O), " front flips by clip", sum("clip_flip" in O[i]["method"] for i in O))
    print("yaw", collections.Counter(o["front_yaw_deg"] for o in O.values()))

# ---------------------------------------------------------------- rendering (playwright + orient/render.html)
BASE = os.environ.get("ORIENT_BASE", "http://127.0.0.1:8798")   # any static server rooted at app/ (proxy.py on 8765 works too)
REND = CACHE / "renders"
def rpath(iid, up, yaw, tag=""): return REND / f"{iid}__{up}__{yaw}{tag}.png"

def render_jobs(jobs, n_pages=8, size=256, timeout_s=60):
    """jobs: {iid: [(up, yaw), ...]} -> PNGs in cache/renders (skips existing)."""
    import asyncio, base64
    from playwright.async_api import async_playwright
    REND.mkdir(parents=True, exist_ok=True)
    todo = [(iid, [c for c in cs if not rpath(iid, *c).exists()]) for iid, cs in jobs.items()]
    todo = [t for t in todo if t[1]]
    print("render:", len(todo), "models,", sum(len(t[1]) for t in todo), "shots", flush=True)
    if not todo: return
    q = asyncio.Queue()
    for t in todo: q.put_nowait(t)
    t0 = time.time(); done = [0]
    async def worker(browser, k):
        page = None
        async def fresh():
            nonlocal page
            if page: await page.close()
            page = await browser.new_page(viewport={"width": size, "height": size})
            for att in range(3):
                try:
                    await page.goto(f"{BASE}/furnish/designer/orient/render.html"); await page.wait_for_function("window.orientReady === true", timeout=60000); return
                except Exception as e:
                    print("page init retry", k, str(e)[:80], flush=True); await asyncio.sleep(2)
        if q.empty(): return
        await fresh(); n = 0
        while not q.empty():
            iid, cs = q.get_nowait()
            try:
                for att in range(3):
                    try:
                        await asyncio.wait_for(page.evaluate("u => window.orientLoad(u)", f"/furnish/designer/models_opt/{iid}.glb"), timeout_s); break
                    except Exception as e:
                        if att == 2 or "fetch" not in str(e): raise
                        await asyncio.sleep(1)
                for up, yaw in cs:
                    url = await page.evaluate("([u, y, s]) => window.orientShot(u, y, s)", [up, yaw, size])
                    rpath(iid, up, yaw).write_bytes(base64.b64decode(url.split(",", 1)[1]))
            except Exception as e:
                print("render fail", iid, str(e)[:120], flush=True); await fresh()
            n += 1; done[0] += 1
            if n % 60 == 0: await fresh()   # keep GPU memory bounded
            if done[0] % 100 == 0: print("  rendered", done[0], round(time.time() - t0), "s", flush=True)
    async def main():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", args=["--use-angle=swiftshader", "--use-gl=angle", "--enable-unsafe-swiftshader"])   # plain --use-gl=swiftshader loses the WebGL context on this Chrome
            await asyncio.gather(*[worker(browser, k) for k in range(n_pages)])
            await browser.close()
    asyncio.run(main())
    print("render done", round(time.time() - t0), "s", flush=True)

# ---------------------------------------------------------------- contact sheets
THUMB = H / "palette" / "thumbs"
def hero(iid, size):
    from PIL import Image
    p = THUMB / f"{iid}.jpg"
    if not p.exists():
        it = ITEMS.get(iid) or {}; im = it.get("image")
        p = APP / im if im else None
    from PIL import ImageOps
    if p and pathlib.Path(p).exists():
        return ImageOps.pad(Image.open(p).convert("RGB"), (size, size), color=(255, 255, 255))
    return Image.new("RGB", (size, size), (235, 235, 235))
ITEMS = {}
def sheet(rows, out, size=200, cols=3):
    """rows: [(iid, [img paths...], caption)] -> grid of [hero | renders...] cells."""
    from PIL import Image, ImageDraw
    if not ITEMS: ITEMS.update({i["id"]: i for i in items()})
    nimg = max(len(r[1]) for r in rows) + 1; cw = nimg * size; ch = size + 28
    nrow = math.ceil(len(rows) / cols); W = Image.new("RGB", (cols * cw + (cols - 1) * 8, nrow * ch), (255, 255, 255)); dr = ImageDraw.Draw(W)
    for k, (iid, imgs, cap) in enumerate(rows):
        x0 = (k % cols) * (cw + 8); y0 = (k // cols) * ch
        W.paste(hero(iid, size), (x0, y0))
        for j, ip in enumerate(imgs):
            im = Image.open(ip).convert("RGB").resize((size, size)) if pathlib.Path(ip).exists() else Image.new("RGB", (size, size), (255, 200, 200))
            W.paste(im, (x0 + (j + 1) * size, y0))
        dr.rectangle([x0, y0, x0 + cw - 1, y0 + size - 1], outline=(180, 180, 180))
        dr.text((x0 + 3, y0 + size + 2), f"{k}: {iid[4:40]}", fill=(0, 0, 0)); dr.text((x0 + 3, y0 + size + 14), cap[:70], fill=(90, 0, 0))
    W.save(out); return out

# ---------------------------------------------------------------- stage: sheets (hero | before | after)
def stage_sheets(n="40", seed="7"):
    O = json.load(open(H / "orient.json")); its = items(); random.seed(int(seed))
    pick = random.sample([i["id"] for i in its], int(n))
    changed = [i for i in sorted(O) if O[i]["up"] != "y"]; random.seed(3); chg = random.sample(changed, min(20, len(changed)))
    flipped = [i for i in sorted(O) if "clip_flip" in O[i]["method"]]; random.seed(4); flp = random.sample(flipped, min(20, len(flipped)))
    jobs = {}
    for i in pick + chg + flp: jobs.setdefault(i, set()).update({("y", 0), (O[i]["up"], O[i]["front_yaw_deg"])})
    render_jobs({k: sorted(v) for k, v in jobs.items()}, n_pages=8, size=192)
    SH = OUT / "sheets"; SH.mkdir(exist_ok=True)
    for f in SH.glob("*.png"): f.unlink()
    def rows(ids): return [(i, [rpath(i, "y", 0), rpath(i, O[i]["up"], O[i]["front_yaw_deg"])], f"up {O[i]['up']} yaw {O[i]['front_yaw_deg']} c{O[i]['confidence']} " + O[i]['method'].replace('up:', '').replace('; front:', ' | ').replace('geometry', 'geo')[:48]) for i in ids]
    for k in range(0, len(pick), 10): sheet(rows(pick[k:k + 10]), SH / f"random_{k // 10 + 1:02d}.png", size=180, cols=2)
    for k in range(0, len(chg), 10): sheet(rows(chg[k:k + 10]), SH / f"up_changed_{k // 10 + 1:02d}.png", size=180, cols=2)
    for k in range(0, len(flp), 10): sheet(rows(flp[k:k + 10]), SH / f"front_clip_flip_{k // 10 + 1:02d}.png", size=180, cols=2)
    json.dump({"random": pick, "up_changed": chg, "front_by_clip": flp}, open(CACHE / "sheet_ids.json", "w"), indent=0)
    print("sheets written", len(list(SH.glob("*.png"))))

if __name__ == "__main__":
    globals()["stage_" + sys.argv[1]](*sys.argv[2:])
