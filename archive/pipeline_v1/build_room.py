"""Build one room: python build_room.py <photo_dir> <room_name> [cluster_index|'all'|comma list] [ceil_m]
Writes app/rooms/<room_name>.glb/.json and copies photos to app/rooms/<room_name>_photos/."""
import sys, os, json, pathlib, shutil, numpy as np, recon, geometry, export
d = pathlib.Path(sys.argv[1]); name = sys.argv[2]; which = sys.argv[3] if len(sys.argv) > 3 else "0"; ceil_m = float(sys.argv[4]) if len(sys.argv) > 4 else 2.6
ROOMS = pathlib.Path(__file__).resolve().parents[1] / "rooms"
paths = recon.filter_photos(sorted(str(p) for p in d.glob("*.jpg")))
if which == "all": sel = paths
elif "," in which or which.endswith(".jpg"): sel = [str(d / w.strip()) for w in which.split(",")]
else:
    cj = d / "clusters.json"
    if not cj.exists():
        P0 = recon.run(paths); M, N = recon.consistency(P0); comps = recon.cluster(M, N)
        json.dump([{"room": k, "images": [pathlib.Path(paths[i]).name for i in c], "idx": c} for k, c in enumerate(comps)], open(cj, "w"), indent=1)
    cl = json.load(open(cj))[int(which)]; sel = [str(d / n) for n in cl["images"]]
gen_masks = None
if os.environ.get("GEN", "0") == "1":
    import outpaint; gen_dir = ROOMS / f"{name}_gen"; outs = outpaint.outpaint_room(sel, gen_dir)
    sel = [o[0] for o in outs]; gen_masks = [o[1] for o in outs]
P = recon.run(sel)
# second pass: drop photos that do not agree with the rest of the cluster (prevents floating fragments)
if len(sel) >= 3:
    M, N = recon.consistency(P); best = [max([min(M[i, j], M[j, i]) for j in range(len(sel)) if j != i and N[i, j] >= 2000 and N[j, i] >= 2000] or [0]) for i in range(len(sel))]
    keep = [i for i, b in enumerate(best) if b >= 0.35]
    if len(keep) < len(sel) and len(keep) >= 1:
        print(f"[build] dropping {[pathlib.Path(sel[i]).name for i in range(len(sel)) if i not in keep]} (best mutual consistency {[round(best[i],2) for i in range(len(sel)) if i not in keep]})")
        sel = [sel[i] for i in keep]; P = recon.run(sel)
room = geometry.clean_room(P, ceil_m=ceil_m)
if gen_masks:
    # per-pixel provenance at reconstruction resolution: True where the pixel was generated
    from PIL import Image as _Im
    S_, H_, W_ = room["labels"].shape; gm = np.zeros((S_, H_, W_), bool)
    for i_, mp in enumerate(gen_masks[:S_]): gm[i_] = np.asarray(_Im.open(mp).convert("L").resize((W_, H_), _Im.NEAREST)) > 127
    room["generated"] = gm
    # safety: generated pixels that reconstruct as objects (not wall/floor/ceiling) are not trusted as geometry
    drop = gm & (room["labels"] == geometry.OTHER); room["good"] &= ~drop
    print(f"[outpaint] generated pixel fraction {gm.mean():.2f}; generated-but-object pixels discarded {drop.mean():.3f}")
import layout, export_layout, trimesh
carved = layout.carve(room)
V, EL = layout.general_polygon(carved["region"], carved["lo"], room["planes"])
if len(sel) == 1 and V is not None: V, EL = layout.close_behind_camera(V, EL, room, room["planes"]); print(f"[layout] single photo: carved polygon closed 1.5 m behind the camera ({len(V)} vertices)")
if V is None: raise SystemExit("[build] polygon failed")
edges = layout.edges_of(V, EL); moved = layout.snap_to_edges(room, edges)
print(f"[layout] wall directions {room['stats']['wall_dirs_deg']}; polygon edges inferred (no plane): {[k for k, e in enumerate(edges) if e['inferred']]}")
openings = layout.detect_openings(room, edges)
if os.environ.get("FIT", "0") == "1":
    import fit as F, copy
    door_boxes = [(o["img"], *o["box"]) for o in openings if o["kind"] == "door"]
    rf = F.RoomFit(room, P, V, stride=4, door_boxes=door_boxes, edges=edges)
    L0, info0 = rf.loss(); print(f"[fit] before: depth med log-err per photo {np.round(info0['depth_med_logerr'], 3).tolist()} free-viol {info0['free_viol']:.4f}")
    passages = F.fit_two_pass(rf, iters=int(os.environ.get("FIT_ITERS", "300")))
    L1, info1 = rf.loss(); print(f"[fit] after:  depth med log-err per photo {np.round(info1['depth_med_logerr'], 3).tolist()} free-viol {info1['free_viol']:.4f} scale {info1['scale']:.3f}")
    V1 = rf.polygon(); print(f"[fit] edge offsets moved by {np.round(np.abs(rf.off.detach().numpy() - rf.off0.numpy()), 2).tolist()} m; angles by {np.round(np.degrees(np.abs(rf.phi.detach().numpy() - rf.phi0.numpy())), 1).tolist()}°; cam moves {np.round(np.linalg.norm(rf.dc.detach().numpy(), axis=1), 2).tolist()} m")
    from shapely.geometry import Polygon as _Poly
    try: ok_poly = _Poly(V1).is_valid and 0.33 < _Poly(V1).area / max(_Poly(V).area, 1e-6) < 3.0
    except Exception: ok_poly = False
    if not ok_poly: print("[fit] fitted polygon invalid or degenerate; keeping the carved polygon, using refined poses"); V1 = V
    room = rf.apply(); V = V1; edges = layout.edges_of(V, EL); moved = layout.snap_to_edges(room, edges); openings = layout.detect_openings(room, edges)
    # merge see-through passages with detected doors on the same edge
    for p_ in passages:
        if not any(o["kind"] == "door" and o["edge"] == p_["edge"] and min(o["s1"], p_["s1"]) - max(o["s0"], p_["s0"]) > 0.2 for o in openings): openings.append(p_)
    room["fit"] = {"before": info0, "after": info1, "passages": len(passages)}
if os.environ.get("POLISH", "0") == "1":
    import polish; pdir = ROOMS / f"{name}_polish"; pdir.mkdir(exist_ok=True)
    frames = polish.wall_frames(edges, room["ceil_m"]); acc = polish.cast_pixels(room, P, frames, room["ceil_m"], stride=1)
    parts_ = [acc[f["k"]]["col"][acc[f["k"]]["n_at"] > 0] / acc[f["k"]]["n_at"][acc[f["k"]]["n_at"] > 0][:, None] for f in frames if (acc[f["k"]]["n_at"] > 0).any()]
    wpx = room["rgb"][room["labels"] == geometry.WALL]
    wall_col = np.median(np.concatenate(parts_), 0).astype(np.uint8) if parts_ else (np.median(wpx, 0).astype(np.uint8) if len(wpx) > 100 else np.array([220, 216, 208], np.uint8))
    pol = {"walls": [], "openings": []}
    from PIL import Image as _Im
    for f in frames:
        A = acc[f["k"]]; prior = [(o["s0"], o["s1"], o["sill_m"], o["sill_m"] + o["height_m"]) for o in openings if o["edge"] == f["k"]]
        img, seen = polish.wall_texture(A, f, room["ceil_m"], wall_col); ops, score = polish.detect_openings_tex(A, f, room["ceil_m"], prior, tex_img=img)
        _Im.fromarray(img).save(pdir / f"wall_{f['k']}.png"); _Im.fromarray((np.clip(score, 0, 1) * 255).astype(np.uint8)).save(pdir / f"open_{f['k']}.png")
        for j, o in enumerate(ops):
            ov, has = polish.outside_view(A, o["tex_box"]); o["outside_seen"] = round(has, 2); o["outside_file"] = f"{name}_polish/outside_{f['k']}_{j}.png"; _Im.fromarray(ov).save(pdir / f"outside_{f['k']}_{j}.png")
        pol["walls"].append({"k": f["k"], "len": f["len"], "seen_frac": float(seen.mean()), "file": f"{name}_polish/wall_{f['k']}.png"}); pol["openings"] += ops
    # ceiling colour from ceiling pixels; floor texture at 1 cm; export the polished shell
    cpx = room["rgb"][room["labels"] == geometry.CEIL]; room["ceil_colour"] = np.median(cpx, 0).astype(int).tolist() if len(cpx) > 100 else [236, 236, 232]
    textures = {f["k"]: np.asarray(_Im.open(pdir / f"wall_{f['k']}.png").convert("RGB")) for f in frames}
    outside = {}
    for f in frames:
        for j, o in enumerate([o for o in pol["openings"] if o["edge"] == f["k"]]): outside[(f["k"], j)] = np.asarray(_Im.open(pdir / f"outside_{f['k']}_{j}.png").convert("RGB"))
    ftex_hi = layout.floor_texture(room, V, res=0.01); ftex_hi["img"] = polish.flat_field(ftex_hi["img"], np.ones(ftex_hi["img"].shape[:2], bool), sigma_px=60)
    import polish_export; pol["glb"] = polish_export.export_polished(room, V, frames, pol, textures, outside, ftex_hi, ROOMS, name)
    json.dump(pol, open(pdir / "polish.json", "w"), indent=1)
    print(f"[polish] {len(frames)} walls; openings: " + "; ".join(f"wall {o['edge']} {o['kind']} {o['width_m']}x{o['height_m']} sill {o['sill_m']} beyond {o['beyond']} bright {o['bright']}" for o in pol["openings"]))
wtex = layout.wall_textures(room, edges); ftex = layout.floor_texture(room, V)
meta = export.export(room, ROOMS, name, sel, extra=lambda scene: export_layout.add_layout(scene, V, edges, room["ceil_m"], wtex, ftex, openings))
export_layout.plan_image(carved, V, edges, room["cams"], openings, ROOMS / f"{name}_plan.png")
meta["polygon"] = V.round(3).tolist(); meta["edges"] = edges; meta["area_m2"] = round(float(layout.poly_area(V)), 2)
meta["windows"] = [o for o in openings if o["kind"] == "window"]; meta["doors"] = [o for o in openings if o["kind"] in ("door", "passage")]
meta["wall_seen_frac"] = [round(t["seen_frac"], 2) for t in wtex]; meta["wall_generated_frac"] = [round(t.get("generated_frac", 0.0), 2) for t in wtex]
meta["generated"] = bool(gen_masks); meta["generated_fraction"] = float(room["generated"].mean()) if gen_masks else 0.0
import suncue; meta["sun_patches"] = suncue.detect_sun_patches(room, meta)
import fuse; meta["fused"] = fuse.run(room, P, ROOMS, name, shell=(V, room["ceil_m"]))
if os.environ.get("OBJ", "0") == "1":
    import objects; meta["objects"] = objects.run(room, V, edges, ROOMS / f"{name}_objects.json")
print(f"[suncue] {len(meta['sun_patches'])} sun patches: " + "; ".join(f"img {p['img']} via edge {p['window_edge']} el {p['el_deg']}° az_rel {p['az_rel_deg']}° x{p['brightness_ratio']}" for p in meta["sun_patches"]))
if "fit" in room: meta["fit"] = room["fit"]
def _san(o):
    import math
    if isinstance(o, float): return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict): return {k: _san(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_san(v) for v in o]
    return o
json.dump(_san(meta), open(ROOMS / f"{name}.json", "w"), indent=1)
print(f"[layout] polygon {len(V)} vertices, area {meta['area_m2']} m2, {len(edges)} walls, snapped {moved} wall px, {len(meta['windows'])} windows, {len(meta['doors'])} doors, wall seen {meta['wall_seen_frac']}")
pd = ROOMS / f"{name}_photos"; pd.mkdir(exist_ok=True)
for i, p in enumerate(sel): shutil.copy(p, pd / f"{i}.jpg")
st = room["stats"]
print(f"[build] {name}: {len(sel)} photos | ceiling {st['ceil_h_m']:.2f} m | manhattan {st['manhattan_deg']:.1f}° | cam heights {st['cam_heights_m']} | "
      f"labels {{floor {st['label_frac']['floor']:.2f}, ceil {st['label_frac']['ceil']:.2f}, wall {st['label_frac']['wall']:.2f}}} | walls {st['n_wall_planes']} | wall resid {st['wall_resid_m_before']} -> {st['wall_resid_m_after']}")
