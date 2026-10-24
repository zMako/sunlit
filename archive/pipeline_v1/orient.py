"""Phase 4 orientation: match the room's window wall to a street facade, place the room and its windows in world ENU,
and compute year sun-hours per window against the block (own building excluded)."""
import sys, json, math, pathlib, numpy as np
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import sunhours

def window_wall(meta):
    """Pick the room edge carrying the most window area; return edge index and its outward normal (room frame xz)."""
    V = np.array(meta["polygon"]); cen = V.mean(0); best = None
    def plausible(w):  # drop mirror/TV-like detections: high sill and nearly square and large
        return not (w["sill_m"] > 1.0 and w["width_m"] > 1.4 and 0.8 < w["width_m"] / max(w["height_m"], 0.1) < 1.25)
    wins = [w for w in meta["windows"] if plausible(w)] or meta["windows"]
    def key(w): return w["edge"] if w["edge"] >= 0 else ("plane", round(w["normal"][0]), round(w["normal"][2]))
    for e_key in set(key(w) for w in wins):
        ws = [w for w in wins if key(w) == e_key]; score = sum(w["width_m"] * w["height_m"] for w in ws) + 1.0 * len(ws)
        if best is None or score > best[0]: best = (score, e_key, ws)
    if best is None: return None
    score, e_key, ws = best
    if isinstance(e_key, tuple):  # virtual wall from a fitted plane: normal from the windows, midpoint from their centres
        n = np.array([ws[0]["normal"][0], ws[0]["normal"][2]]); c = np.mean([[w["center"][0], w["center"][2]] for w in ws], 0)
        if n @ (c - cen) < 0: n = -n
        return {"edge": -1, "normal_room": n.tolist(), "mid": c.tolist(), "len": 3.0, "window_area": score}
    e = meta["edges"][e_key]; a, b = np.array(e["a"]), np.array(e["b"]); mid = (a + b) / 2
    n = np.array(e["n"], float) if "n" in e else np.array([1.0 if e["axis"] == 0 else 0.0, 1.0 if e["axis"] == 2 else 0.0])
    if n @ (mid - cen) < 0: n = -n
    return {"edge": e_key, "normal_room": n.tolist(), "mid": mid.tolist(), "len": e["len"], "window_area": score}

def room_to_world(meta, site, facade, ww):
    """Yaw so the window wall's outward normal (room xz) points along the facade bearing; translate the wall midpoint onto the facade midpoint."""
    n = np.array(ww["normal_room"]); room_bearing = math.degrees(math.atan2(n[0], -n[1])) % 360   # room frame: x east-ish, z south-ish (three.js), bearing of normal
    yaw = (facade["bearing"] - room_bearing) % 360
    a, b = np.array(facade["a"]), np.array(facade["b"]); fmid = (a + b) / 2
    def to_world(p_room):   # room (x, z) -> ENU (east, north): rotate by yaw about up, then translate
        x, z = p_room; e_, n_ = x, -z  # room x->east, z->south, before yaw
        r = math.radians(yaw); e2 = e_ * math.cos(r) + n_ * math.sin(r); n2 = -e_ * math.sin(r) + n_ * math.cos(r)
        return np.array([e2, n2])
    mid_w = to_world(ww["mid"]); shift = fmid - mid_w
    T = lambda p: to_world(p) + shift; T.shift = shift; return yaw, T

def choose_facade(meta, site, cands):
    """Score facade candidates with the sun-patch cue; fall back to the address-street facade."""
    import suncue
    patches = meta.get("sun_patches", []); hint = meta.get("claude_side")
    if hint in (None, "unknown"):
        dirs = meta.get("stats", {}).get("wall_dirs_deg", [])
        if any(min(abs(d - m) for m in (0, 90, 180)) > 15 for d in dirs): hint = "street"   # a bay almost always faces the street in SF
    if not patches:
        scored = [{"edge": c["edge"], "bearing": c["bearing"], "feasible": None, "of": 0} for c in cands]
        street_idx = [k for k, c in enumerate(cands) if c.get("is_address_street")] or [0]
        if hint == "street": return street_idx[0], scored, "no sun patches; Claude says street side"
        if hint == "back":
            sb = cands[street_idx[0]]["bearing"]; back = min(range(len(cands)), key=lambda k: abs(((cands[k]["bearing"] - sb + 180) % 360) - 180) if k != street_idx[0] else 999)
            if abs(((cands[back]["bearing"] - sb + 180) % 360) - 180) < 45: return back, scored, "no sun patches; Claude says back side"
        if hint in ("side_lightwell", "unknown", "corner", None): return None, scored, f"no sun patches; side {hint or 'unknown'}: orientation not determined"
        return street_idx[0], scored, "no sun patches; address street"
    env = suncue.sun_envelope(site["lat"], site["lon"]); scored = suncue.score_candidates(patches, cands, env)
    best = max(range(len(cands)), key=lambda k: (scored[k]["feasible"], -k))
    return best, scored, "sun-patch cue"

def place(meta, site, facade_index=None, floor_height=3.0):
    ww = window_wall(meta)
    if ww is None: raise RuntimeError("room has no windows to orient by")
    cands = site["facades_street"] or site["facades_all"]
    if facade_index is None: facade_index, scored, how = choose_facade(meta, site, cands)
    else: scored, how = None, "forced"
    if facade_index is None: return {"undetermined": True, "how": how, "candidates": [{"edge": f["edge"], "bearing": f["bearing"], "street": f["street"]} for f in cands], "scores": scored, "windows": [], "window_wall": ww}
    facade = cands[facade_index]
    yaw, T = room_to_world(meta, site, facade, ww)
    import register
    reg = register.register(meta, site, ww, facade, yaw)
    if reg:
        yaw = reg["yaw"]; T = register.transform_fn(yaw, reg["shift"]); T.shift = reg["shift"]
        print(f"[register] facade edge {facade['edge']}: yaw {yaw:.1f}°, slide {reg['slide_m']:.2f} m of {facade['len']} m, depth {reg['depth_m']:+.2f} m, inside lot {reg['inside']:.2f}, exterior on boundary {reg['on_boundary']:.2f}")
    floor = site["floor"] if isinstance(site["floor"], int) else max(1, site.get("storeys_est", 1))
    z0 = site["building"]["ground"] + (floor - 1) * floor_height
    poly_world = [T(p).round(2).tolist() for p in meta["polygon"]]
    wins = []
    for w in meta["windows"]:
        c = np.array(w["center"]); cw = T([c[0], c[2]]); n = np.array(w["normal"]); nw_ = T([c[0] + n[0], c[2] + n[2]]) - cw
        bearing = math.degrees(math.atan2(nw_[0], nw_[1])) % 360
        wins.append({**w, "world_en": cw.round(2).tolist(), "z_m": round(z0 + c[1], 2), "bearing": round(bearing, 1), "normal_en": (nw_ / np.linalg.norm(nw_)).round(3).tolist()})
    return {"yaw_deg": round(yaw, 1), "shift_en": [round(float(v), 3) for v in T.shift], "registration": {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in (reg or {}).items()}, "facade": facade, "floor": floor, "z0_m": round(z0, 2), "polygon_world": poly_world, "windows": wins, "window_wall": ww,
            "candidates": [{"edge": f["edge"], "bearing": f["bearing"], "street": f["street"]} for f in cands], "scores": scored, "how": how}

def sun_for_windows(site, placed, step_min=20):
    own = site["building"]["id"]; occluders = [b for b in site["buildings"] if b["id"] != own]
    out = []
    for w in placed["windows"]:
        e, n = w["world_en"]; normal = [w["normal_en"][0], w["normal_en"][1], 0.0]
        pos = (e + normal[0] * 0.3, n + normal[1] * 0.3, w["z_m"])  # just outside the facade so the own wall does not occlude
        r = sunhours.year_sun_hours(site["lat"], site["lon"], pos, normal, occluders, step_min=step_min, terrain=site.get("terrain"), horizon=site.get("horizon"))
        out.append({"edge": w["edge"], "bearing": w["bearing"], "width_m": w["width_m"], "height_m": w["height_m"], "sill_m": w["sill_m"],
                    "annual_hours": round(r["annual_hours"]), "annual_unobstructed": round(r["annual_unobstructed"]), "per_month_hours": {k: round(v, 1) for k, v in r["per_month_hours"].items()}})
    return out

if __name__ == "__main__":
    room_name, listing = sys.argv[1], sys.argv[2]; fi = int(sys.argv[3]) if len(sys.argv) > 3 else None
    meta = json.load(open(ROOT / "rooms" / f"{room_name}.json")); site = json.load(open(ROOT / "sites" / listing / "site.json"))
    placed = place(meta, site, fi); sun = sun_for_windows(site, placed) if not placed.get("undetermined") else []
    res = {"room": room_name, "listing": listing, **placed, "sun": sun}
    json.dump(res, open(ROOT / "rooms" / f"{room_name}_world.json", "w"), indent=1)
    if not placed.get("undetermined"):
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 7)); ax.set_facecolor("#111")
        for b_ in site["buildings"]: r_ = b_["ring"]; ax.fill([p[0] for p in r_], [p[1] for p in r_], color=(0.4, 0.4, 0.45), alpha=0.5, lw=0.3, ec="k")
        r_ = site["building"]["ring"]; ax.plot([p[0] for p in r_], [p[1] for p in r_], "-", color="orange", lw=2)
        PV = np.array(placed["polygon_world"] + placed["polygon_world"][:1]); ax.plot(PV[:, 0], PV[:, 1], "c-", lw=2)
        for w in placed["windows"]: ax.scatter(w["world_en"][0], w["world_en"][1], c="yellow", s=60, zorder=5)
        f = placed["facade"]; ax.plot([f["a"][0], f["b"][0]], [f["a"][1], f["b"][1]], "r--", lw=1.5)
        cx, cy = np.mean(PV[:, 0]), np.mean(PV[:, 1]); ax.set_xlim(cx - 18, cx + 18); ax.set_ylim(cy - 18, cy + 18); ax.set_aspect("equal")
        ax.set_title(f"{room_name}: room (cyan) in footprint (orange), facade (red), windows (yellow)"); plt.tight_layout(); plt.savefig(ROOT / "rooms" / f"{room_name}_site_plan.png", dpi=80); plt.close()
    if placed.get("undetermined"): print(f"[orient] {room_name}: {placed['how']}")
    elif placed["scores"]: print("[orient] candidates: " + "; ".join(f"edge {c['edge']} {c['bearing']}° {c.get('street')}: {c['feasible']}/{c['of']} patches feasible" for c in placed["scores"]) + f" -> chosen by {placed['how']}")
    if not placed.get("undetermined"): print(f"[orient] {room_name}: window wall edge {placed['window_wall']['edge']} -> facade edge {placed['facade']['edge']} bearing {placed['facade']['bearing']}° ({placed['facade']['street']}), yaw {placed['yaw_deg']}°, floor {placed['floor']} (z0 {placed['z0_m']} m); candidates {[(c['edge'], c['bearing']) for c in placed['candidates']]}")
    for s_ in sun: print(f"   window {s_['width_m']}x{s_['height_m']} m facing {s_['bearing']}°: {s_['annual_hours']} h/yr direct sun (unobstructed {s_['annual_unobstructed']}), Dec {s_['per_month_hours'][12]} h/day, Jun {s_['per_month_hours'][6]} h/day")
