"""Direct-sun hours for a window: ray-cast from the window against extruded building footprints, every N minutes for a year."""
import json, math, datetime as dt, pathlib, sys, numpy as np, zoneinfo
from solar import sun_position, sun_vector

def load_block(path):
    d = json.load(open(path)); return d

def terrain_blocked(origin, dirs, terrain, max_dist=300.0, step=4.0):
    """March each ray over the block heightfield; blocked where the ray dips under the terrain."""
    H = np.asarray(terrain["heights"]); x0, n0, cell = terrain["x0"], terrain["n0"], terrain["cell"]
    T = len(dirs); blocked = np.zeros(T, bool); ox, oy, oz = origin
    for k in np.arange(step, max_dist, step):
        x = ox + dirs[:, 0] * k; y = oy + dirs[:, 1] * k; z = oz + dirs[:, 2] * k
        i = np.clip(((y - n0) / cell).astype(int), 0, H.shape[0] - 1); j = np.clip(((x - x0) / cell).astype(int), 0, H.shape[1] - 1)
        inside = (x >= x0) & (x < x0 + cell * H.shape[1]) & (y >= n0) & (y < n0 + cell * H.shape[0])
        blocked |= inside & (z < H[i, j])
    return blocked

def ray_blocked(origin, dirs, buildings, max_dist=400.0, terrain=None):
    """origin (3,), dirs (T,3) unit ENU. Returns bool (T,) blocked by any prism (or the terrain)."""
    T = len(dirs); blocked = np.zeros(T, bool)
    if terrain is not None: blocked |= terrain_blocked(origin, dirs, terrain)
    ox, oy, oz = origin
    for b in buildings:
        ring = np.asarray(b["ring"]); zb, zt = b["ground"], b["ground"] + b["height"]
        # quick reject by bounding circle
        c = ring.mean(0); R = np.max(np.linalg.norm(ring - c, axis=1)) + 1
        d2 = c - origin[:2]; dist_c = np.hypot(*d2)
        if dist_c > max_dist: continue
        # walls: for each edge (p,q), ray (ox,oy)+t*(dx,dy) intersects segment; height at t within [zb,zt]
        dx, dy = dirs[:, 0], dirs[:, 1]
        for i in range(len(ring) - 1):
            px, py = ring[i]; qx, qy = ring[i + 1]; ex, ey = qx - px, qy - py
            den = dx * ey - dy * ex
            ok = np.abs(den) > 1e-9
            t = np.where(ok, ((px - ox) * ey - (py - oy) * ex) / np.where(ok, den, 1), -1)
            s = np.where(ok, ((px - ox) * dy - (py - oy) * dx) / np.where(ok, den, 1), -1)
            hit = ok & (t > 0.01) & (s >= 0) & (s <= 1)
            z = oz + t * dirs[:, 2]
            blocked |= hit & (z >= zb) & (z <= zt)
        # roof: intersect with plane z = zt, point in polygon
        dz = dirs[:, 2]; okr = np.abs(dz) > 1e-9
        t = np.where(okr, (zt - oz) / np.where(okr, dz, 1), -1); valid = okr & (t > 0.01)
        if valid.any():
            X = ox + t * dx; Y = oy + t * dy
            inside = np.zeros(T, bool)
            for i in range(len(ring) - 1):
                px, py = ring[i]; qx, qy = ring[i + 1]
                cond = ((py > Y) != (qy > Y)) & (X < (qx - px) * (Y - py) / ((qy - py) + 1e-12) + px)
                inside ^= cond
            blocked |= valid & inside
    return blocked

def year_sun_hours(lat, lon, window_pos, window_normal, buildings, step_min=15, year=2026, min_el=3.0, max_incidence=85.0, terrain=None, horizon=None):
    """Returns dict month -> mean direct-sun hours per day, plus per-day array."""
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    n = np.asarray(window_normal, float); n /= np.linalg.norm(n)
    start = dt.datetime(year, 1, 1, tzinfo=tz); T = int(365 * 24 * 60 / step_min)
    times = [start + dt.timedelta(minutes=step_min * k) for k in range(T)]
    az_el = np.array([sun_position(lat, lon, t.astimezone(dt.timezone.utc)) for t in times])
    vec = np.array([sun_vector(a, e) for a, e in az_el])
    up = az_el[:, 1] > min_el
    if horizon:  # distant terrain: sun must clear the horizon profile at its azimuth
        step = horizon["az_step"]; prof = horizon["horizon_deg"]
        hz = np.array([prof[str(int(a // step) * step % 360)] for a in az_el[:, 0]]); up &= az_el[:, 1] > hz + 0.5
    facing = (vec @ n) > math.cos(math.radians(max_incidence))
    cand = up & facing
    blocked = np.zeros(T, bool)
    if cand.any():
        blocked[cand] = ray_blocked(np.asarray(window_pos, float), vec[cand], buildings, terrain=terrain)
    sunlit = cand & ~blocked
    doy = np.array([t.timetuple().tm_yday for t in times]); month = np.array([t.month for t in times])
    hours_per_day = np.bincount(doy, weights=sunlit * step_min / 60, minlength=367)[1:366]
    unblocked_per_day = np.bincount(doy, weights=cand * step_min / 60, minlength=367)[1:366]
    per_month = {m: float(np.mean(hours_per_day[[d - 1 for d in range(1, 366) if month[np.searchsorted(doy, d)] == m]])) for m in range(1, 13)}
    return {"per_month_hours": per_month, "per_day_hours": hours_per_day.tolist(), "per_day_unobstructed": unblocked_per_day.tolist(),
            "annual_hours": float(hours_per_day.sum()), "annual_unobstructed": float(unblocked_per_day.sum())}

if __name__ == "__main__":
    blk = load_block(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).parent / "block.json")
    import time
    for name, normal, h in (("south", (0, -1, 0), 9), ("north", (0, 1, 0), 9), ("east", (1, 0, 0), 9), ("west", (-1, 0, 0), 9), ("south 1st floor", (0, -1, 0), 2)):
        t0 = time.time()
        r = year_sun_hours(blk["lat"], blk["lon"], (0, 0, h), normal, blk["buildings"])
        pm = r["per_month_hours"]
        print(f"{name:16s} window @ {h} m: annual {r['annual_hours']:.0f} h (unobstructed {r['annual_unobstructed']:.0f}) | "
              + " ".join(f"{m}:{pm[m]:.1f}" for m in range(1, 13)) + f" | {time.time()-t0:.1f}s")
