"""Pipeline 2 room build (fast tier): photos -> recon -> segmentation -> seg-driven geometry -> floor footprint polygon ->
openings from masks -> fit -> export + metrics. Usage: build_room2.py <photo_dir> <room_name> <photo list|cluster idx> [ceil_m]"""
import sys, os, json, time, pathlib, shutil, numpy as np
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parents[0] / "pipeline")); sys.path.insert(0, str(HERE))
import recon, geometry, layout, export, export_layout, seg as S, layout2
from PIL import Image
ROOMS = HERE.parents[0] / "rooms"

def build(photo_dir, name, which, ceil_m=2.6, fit=True, quiet=False, room_label=""):
    t0 = time.time(); d = pathlib.Path(photo_dir); log = []
    VAR = os.environ.get("VARIANT", ""); A = VAR == "A"
    if VAR and not name.endswith("_" + VAR): name = f"{name}_{VAR}"
    paths = recon.filter_photos(sorted(str(p) for p in d.glob("*.jpg")))
    if "," in which or which.endswith(".jpg"): sel = [str(d / w.strip()) for w in which.split(",")]
    elif which == "all": sel = paths
    else: cl = json.load(open(d / "clusters.json"))[int(which)]; sel = [str(d / n) for n in cl["images"]]
    P = recon.run(sel)
    if len(sel) >= 2:   # geometry may only split a semantic group: keep the largest mutually consistent subset
        M, N = recon.consistency(P); n = len(sel)
        seg0 = [S.segment(p)[0] for p in sel]; Hh, Ww = P["conf"].shape[1:]
        R0 = geometry.gravity_frame(P["extrinsic"]); up = R0[1]
        flo = []
        for i in range(n):
            s_i = np.asarray(Image.fromarray(seg0[i]).resize((Ww, Hh), Image.NEAREST)) == S.FLOOR; ys = (P["world_points"][i][s_i] @ up); flo.append(float(np.median(ys)) if s_i.sum() > 500 else None)
        camd = lambda i, j: float(np.linalg.norm(P["cam_centers"][i] - P["cam_centers"][j]))
        def agree(i, j):   # overlap, or the same floor level and a plausible camera spacing (VGGT places non-overlapping views by room context)
            if N[i, j] >= 2000 and N[j, i] >= 2000 and min(M[i, j], M[j, i]) >= 0.35: return True
            return flo[i] is not None and flo[j] is not None and abs(flo[i] - flo[j]) < 0.12 * max(1e-6, abs(flo[i]) + abs(flo[j]) + 0.5) and camd(i, j) < 7.0
        adj = {i: {j for j in range(n) if j != i and agree(i, j)} for i in range(n)}
        seen, comps = set(), []
        for i in range(n):
            if i in seen: continue
            st, comp = [i], []
            while st:
                k = st.pop()
                if k in seen: continue
                seen.add(k); comp.append(k); st.extend(adj[k] - seen)
            comps.append(sorted(comp))
        wallpx = [int((S.segment(p)[0] == S.WALL).sum()) for p in sel]
        best = max(comps, key=lambda c: (len(c), sum(wallpx[i] for i in c)))
        if len(best) < n:
            log.append(f"split: kept photos {[pathlib.Path(sel[i]).name for i in best]}, dropped {[pathlib.Path(sel[i]).name for i in range(n) if i not in best]} (no overlap and floor levels disagree)")
            sel = [sel[i] for i in best]; P = recon.run(sel)
    segl = np.stack([np.asarray(Image.fromarray(S.segment(p)[0]).resize((P["conf"].shape[2], P["conf"].shape[1]), Image.NEAREST)) for p in sel])
    vlm = None
    plan_path, plan_room = os.environ.get("PLAN_JSON"), os.environ.get("PLAN_ROOM")
    if plan_path and plan_room:   # floor plan read by plan_reader.py: printed dimensions are ground truth for the unmeasured sides
        pr = next((r for r in json.load(open(plan_path))["rooms"] if r["name"].lower() == plan_room.lower()), None)
        if pr and pr.get("width_m") and pr.get("depth_m"):
            vlm = {"shape": pr["shape"], "width_m": pr["width_m"], "depth_m": pr["depth_m"], "ceiling_m": None, "size_confidence": 1.0, "source": "floor_plan"}; log.append(f"plan room '{plan_room}' {pr['width_m']}x{pr['depth_m']} m")
    if vlm is None and os.environ.get("VLM", "1") == "1":
        try:
            import vlm_structure; vlm = vlm_structure.structure(sel, room_label); log.append(f"vlm {vlm['shape']} {vlm['width_m']}x{vlm['depth_m']} m ceil {vlm['ceiling_m']} conf {vlm['size_confidence']}")
            if vlm and vlm.get("ceiling_m") and 2.2 <= vlm["ceiling_m"] <= 3.6: ceil_m = float(vlm["ceiling_m"])
        except Exception as e: log.append(f"vlm failed: {type(e).__name__}")
    hs = {"h": 1.0}
    def geom(ceil):
        room = geometry.clean_room(P, ceil_m=ceil, seg=segl, h_scale=hs["h"]); room["seg"] = segl
        fp = layout2.floor_footprint(room, segl)
        if os.environ.get("RECT", "1") == "1": V, EL, ax = layout2.rect_room(room, segl, vlm=vlm, strict_vlm=A); room["rect_axes"] = ax
        else: V, EL = layout2.polygon_from_cell(fp, room["strong_planes"])
        if V is None: return room, fp, None, None, None, []
        edges = layout.edges_of(V, EL); layout.snap_to_edges(room, edges)
        ops = layout2.openings_by_rays(room, segl, V, edges, P) if A else layout2.openings_from_masks(room, segl, edges, P)
        return room, fp, V, EL, edges, ops
    room, fp, V, EL, edges, openings = geom(ceil_m)
    if V is None: return {"name": name, "ok": False, "error": "polygon failed", "floor_cells": fp["floor_cells"]}
    if A and vlm and (room.get("rect_axes") or {}).get("dbg", {}).get("strict"):
        # Path A horizontal scale: VGGT's horizontal extent vs the VLM / plan size. Measured wall pairs give a ratio; the
        # cameras (which must fit inside with 0.5 m to spare) give an upper bound. Rebuild the geometry at that scale.
        dbg0 = room["rect_axes"]["dbg"]; cands = []; upper = 1.3
        for ax in (0, 1):
            D0 = min(max(dbg0["dim_for"][ax], 1.8), 9.0)
            if dbg0["pair_measured"][ax] and dbg0["span0"][ax] > 1.0: cands.append(D0 / dbg0["span0"][ax])
            if dbg0["cam_spread"][ax] > 0.5: upper = min(upper, (D0 - 1.0) / dbg0["cam_spread"][ax])
        s_h = float(np.median(cands)) if cands else 1.0; s_h = float(np.clip(min(s_h, upper), 0.55, 1.3))
        if abs(s_h - 1.0) > 0.05:
            hs["h"] = s_h; log.append(f"h_scale {s_h:.2f} (pairs {[round(c, 2) for c in cands]}, camera bound {upper:.2f})")
            room, fp, V, EL, edges, openings = geom(ceil_m)
            if V is None: return {"name": name, "ok": False, "error": "polygon failed after h_scale"}
    if (d / "plans").exists() and not (plan_path and plan_room) and os.environ.get("PLAN", "1") == "1" and V is not None and room.get("rect_axes"):
        try:   # the listing carries floor plans: pick the plan room that agrees with the measured rectangle, then rebuild with its dimensions
            import plan_match
            rtype = room_label.split(":")[0].strip().lower() if room_label else "other"
            meta0 = json.load(open(d / "meta.json")) if (d / "meta.json").exists() else {}
            cands = plan_match.candidates(d, rtype, meta0.get("sqft_total")); ax = room["rect_axes"]
            pm = plan_match.match(cands, ax["spans"][0], ax["spans"][1], ax["axis_measured"][0], ax["axis_measured"][1], sum(1 for o in openings if o["kind"] == "window"))
            if pm:
                vlm = dict(vlm or {}, **pm); log.append(f"plan {pm['plan']} '{pm['plan_room']}' {pm['width_m']}x{pm['depth_m']} m ({pm['source']}, {pm['n_candidates']} cands, score {pm['score']})")
                room, fp, V, EL, edges, openings = geom(ceil_m)
                if V is None: return {"name": name, "ok": False, "error": "polygon failed after plan"}
            else: log.append(f"plan: no {rtype} candidates with dimensions")
        except Exception as e: log.append(f"plan match failed: {type(e).__name__} {e}")
    # metric scale from doors: standard door 2.03 m. If the measured doors disagree with the assumed ceiling by >5%, redo geometry at the implied ceiling.
    dh = [o["height_m"] for o in openings if o["kind"] == "door" and 1.3 < o["height_m"] < 2.7 and o["width_m"] < 1.4]
    if dh:
        s_ = 2.03 / float(np.median(dh))
        if 0.8 < s_ < 1.3 and abs(s_ - 1) > 0.05:
            ceil_m = round(ceil_m * s_, 2); log.append(f"scale from {len(dh)} door(s): ceiling {ceil_m} m"); room, fp, V, EL, edges, openings = geom(ceil_m)
            if V is None: return {"name": name, "ok": False, "error": "polygon failed after rescale"}
    if fit and A and abs(hs["h"] - 1.0) > 0.05: fit = False; log.append("fit skipped (h_scale)")
    if fit and len(sel) >= 1:
        import fit as F
        door_boxes = []
        rf = F.RoomFit(room, P, V, stride=4, door_boxes=door_boxes, edges=edges)
        if A and vlm and room.get("rect_axes", {}).get("dim_for"):   # Path A: walls may leave their VLM / plan size only slightly
            import torch; ax_ = room["rect_axes"]; frac = 0.05 if vlm.get("source") == "floor_plan" else 0.10; lims = []
            for e in edges:
                nn = np.array(e["n"]); k_ax = 0 if abs(nn @ np.array(ax_["u"])) > abs(nn @ np.array(ax_["v"])) else 1; lims.append(frac * float(ax_["dim_for"][k_ax]))
            rf.off_lim = torch.tensor(lims, dtype=torch.float64); log.append(f"fit walls clamped to +-{frac:.0%} of VLM size")
        L0, i0 = rf.loss(); passages = F.fit_two_pass(rf, iters=250); L1, i1 = rf.loss()
        V1 = rf.polygon()
        from shapely.geometry import Polygon as _P
        try: okp = _P(V1).is_valid and 0.33 < _P(V1).area / max(_P(V).area, 1e-6) < 3.0
        except Exception: okp = False
        if okp: V = V1
        room = rf.apply(); edges = layout.edges_of(V, EL); layout.snap_to_edges(room, edges); openings = layout2.openings_by_rays(room, segl, V, edges, P) if A else layout2.openings_from_masks(room, segl, edges, P)
        for p_ in passages:
            if not any(o["kind"] == "door" and o["edge"] == p_["edge"] and min(o["s1"], p_["s1"]) - max(o["s0"], p_["s0"]) > 0.2 for o in openings): openings.append(p_)
        log.append(f"fit depth err {np.nanmedian(i0['depth_med_logerr']):.3f}->{np.nanmedian(i1['depth_med_logerr']):.3f}")
    if os.environ.get("PANO", "0") == "1":
        import pano; faces = pano.render_faces(room, P, V, sel, projective=A); st = pano.save_faces(faces, ROOMS / f"{name}_pano"); pano.contact_sheet(ROOMS / f"{name}_pano", ROOMS / f"{name}_pano_sheet.png")
        log.append("pano seen " + " ".join(f"{k}:{v['seen_frac']:.2f}" for k, v in st.items()))
    wtex = layout.wall_textures(room, edges); ftex = layout.floor_texture(room, V)
    meta = export.export(room, ROOMS, name, sel, extra=lambda sc: export_layout.add_layout(sc, V, edges, room["ceil_m"], wtex, ftex, openings))
    export_layout.plan_image(fp, V, edges, room["cams"], openings, ROOMS / f"{name}_plan.png")
    doors = [o for o in openings if o["kind"] == "door"]; door_h = [o["height_m"] for o in doors]
    from shapely.geometry import Polygon
    if vlm:
        from shapely.geometry import Polygon as _PP; a_m = _PP(V).area; a_v = float(vlm["width_m"]) * float(vlm["depth_m"]); ratio = a_m / max(a_v, 1e-6)
        meta["vlm"] = {k: vlm.get(k) for k in ("shape", "width_m", "depth_m", "ceiling_m", "size_confidence", "wall_colour", "wall_colour_rgb", "floor_material", "floor_colour_rgb", "notes", "walls", "source")}; meta["vlm_area_ratio"] = round(ratio, 2)
        if ratio > 1.6 or ratio < 0.6: log.append(f"WARNING measured/VLM area ratio {ratio:.2f}")
    meta.update({"polygon": V.round(3).tolist(), "edges": edges, "area_m2": round(float(Polygon(V).area), 2), "windows": [o for o in openings if o["kind"] == "window"], "doors": doors,
                 "inferred_edges": [k for k, e in enumerate(edges) if e["inferred"]], "door_height_check_m": [round(h, 2) for h in door_h], "build_s": round(time.time() - t0, 1), "pipeline": 2})
    pd = ROOMS / f"{name}_photos"; pd.mkdir(exist_ok=True)
    for i, p in enumerate(sel): shutil.copy(p, pd / f"{i}.jpg")
    def _san(o):
        import math
        if isinstance(o, float): return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, dict): return {k: _san(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [_san(v) for v in o]
        return o
    json.dump(_san(meta), open(ROOMS / f"{name}.json", "w"), indent=1)
    res = {"name": name, "ok": True, "n_photos": len(sel), "area_m2": meta["area_m2"], "measured_sides": room.get("rect_axes", {}).get("measured_sides"), "vlm_sides": room.get("rect_axes", {}).get("vlm_sides"), "vlm_area_ratio": meta.get("vlm_area_ratio"), "n_walls": len(edges), "n_inferred": len(meta["inferred_edges"]), "n_windows": len(meta["windows"]), "n_doors": len(doors),
           "rect_dbg": room.get("rect_axes", {}).get("dbg"), "spans": room.get("rect_axes", {}).get("spans"), "axis_measured": room.get("rect_axes", {}).get("axis_measured"), "door_h": meta["door_height_check_m"], "wall_dirs": room["stats"]["wall_dirs_deg"], "cam_h": room["stats"]["cam_heights_m"], "s": meta["build_s"], "log": log}
    if not quiet: print(f"[p2] {name}: {len(sel)} photos, {len(edges)} walls ({len(meta['inferred_edges'])} inferred), {meta['area_m2']} m2, {len(meta['windows'])} windows, {len(doors)} doors (heights {meta['door_height_check_m']}), dirs {room['stats']['wall_dirs_deg']}, {meta['build_s']}s " + "; ".join(log))
    return res

if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "0", float(sys.argv[4]) if len(sys.argv) > 4 else 2.6, fit=os.environ.get("FIT", "1") == "1", room_label=os.environ.get("ROOM_LABEL", ""))
