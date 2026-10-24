"""Sun-patch cue: direct-sun patches on the floor in a photo give the sun direction in room coordinates.
For each patch: the window it came through, elevation (window height over horizontal distance) and azimuth relative to the
window's outward normal. Orientation candidates are then scored by whether the sun can ever be there at this latitude."""
import numpy as np, cv2
from geometry import FLOOR

def detect_sun_patches(room, meta, min_px=1500):
    pts, rgb, labels = room["pts"], room["rgb"], room["labels"]; S, H, W = labels.shape; out = []
    wins = meta.get("windows", [])
    if not wins: return out
    for i in range(S):
        fl = labels[i] == FLOOR
        if fl.sum() < 3000: continue
        L = cv2.cvtColor(rgb[i], cv2.COLOR_RGB2GRAY).astype(np.float32); med = np.median(L[fl])
        bright = fl & (L > max(1.45 * med, med + 40)) & (L > 170)
        bright = cv2.morphologyEx(bright.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, lab, st, cen = cv2.connectedComponentsWithStats(bright)
        for j in range(1, n):
            if st[j, cv2.CC_STAT_AREA] < min_px: continue
            m = lab == j; P = pts[i][m]; c = np.median(P, 0)
            # the window this light came through: nearest window by horizontal distance whose outward normal points away from the patch
            best = None
            for w in wins:
                wc = np.array(w["center"]); nrm = np.array(w["normal"]); dh = np.array([c[0] - wc[0], c[2] - wc[2]])
                inward = -np.array([nrm[0], nrm[2]])
                dist = np.linalg.norm(dh); depth_in = dh @ inward
                if depth_in < 0.3: continue
                if best is None or dist < best[0]: best = (dist, w, dh, inward, depth_in, wc)
            if best is None: continue
            dist, w, dh, inward, depth_in, wc = best
            el = np.degrees(np.arctan2(wc[1] - c[1], dist))                # sun elevation from window centre to patch
            along = np.array([inward[1], -inward[0]])                       # along-wall direction (right-handed with inward)
            az_rel = np.degrees(np.arctan2(dh @ along, depth_in))           # 0 = sun straight in through the window; + = from the right of the outward normal
            out.append({"img": i, "px": int(st[j, cv2.CC_STAT_AREA]), "patch_center": c.round(2).tolist(), "window_edge": w["edge"], "window_center": [round(v, 2) for v in wc.tolist()],
                        "el_deg": round(float(el), 1), "az_rel_deg": round(float(az_rel), 1), "brightness_ratio": round(float(np.median(L[m]) / med), 2)})
    return out

def sun_envelope(lat, lon, year=2026, step_min=10):
    """Max solar elevation reachable per 5-degree azimuth bin over the year (local sun path envelope)."""
    import datetime as dt, zoneinfo, sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); from solar import sun_position
    tz = zoneinfo.ZoneInfo("America/Los_Angeles"); env = np.full(72, -90.0)
    for d in range(0, 365, 4):
        for k in range(0, 24 * 60, step_min):
            t = dt.datetime(year, 1, 1, tzinfo=tz) + dt.timedelta(days=d, minutes=k); az, el = sun_position(lat, lon, t.astimezone(dt.timezone.utc))
            b = int(az // 5) % 72; env[b] = max(env[b], el)
    return env

def score_candidates(patches, candidates, env, tol_deg=6.0):
    """For each facade candidate bearing, fraction of patches whose implied sun direction is reachable."""
    res = []
    for cnd in candidates:
        ok = 0; details = []
        for p in patches:
            az = (cnd["bearing"] + p["az_rel_deg"]) % 360; b = int(az // 5) % 72; reach = env[b] >= p["el_deg"] - tol_deg
            ok += int(reach); details.append({"az": round(az, 1), "el": p["el_deg"], "max_el_there": round(float(env[b]), 1), "ok": bool(reach)})
        res.append({"edge": cnd["edge"], "bearing": cnd["bearing"], "street": cnd.get("street"), "feasible": int(ok), "of": len(patches), "details": details})
    return res
