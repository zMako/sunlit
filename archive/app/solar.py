"""Solar position (NOAA algorithm). sun_position(lat, lon, dt_utc) -> (azimuth_deg from N clockwise, elevation_deg)."""
import math, datetime as _dt

def _jd(dt):
    return dt.timestamp() / 86400.0 + 2440587.5

def sun_position(lat, lon, dt_utc):
    jc = (_jd(dt_utc) - 2451545.0) / 36525.0
    L0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    M = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    Mr = math.radians(M)
    C = (math.sin(Mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + math.sin(2 * Mr) * (0.019993 - 0.000101 * jc) + math.sin(3 * Mr) * 0.000289)
    true_long = L0 + C
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(eps / 2)) ** 2
    eqt = 4 * math.degrees(y * math.sin(2 * math.radians(L0)) - 2 * e * math.sin(Mr) + 4 * e * y * math.sin(Mr) * math.cos(2 * math.radians(L0))
                           - 0.5 * y * y * math.sin(4 * math.radians(L0)) - 1.25 * e * e * math.sin(2 * Mr))
    minutes = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60
    tst = (minutes + eqt + 4 * lon) % 1440
    ha = tst / 4 - 180 if tst / 4 >= 0 else tst / 4 + 180
    latr, declr, har = map(math.radians, (lat, decl, ha))
    cos_zen = math.sin(latr) * math.sin(declr) + math.cos(latr) * math.cos(declr) * math.cos(har)
    zen = math.degrees(math.acos(max(-1, min(1, cos_zen))))
    # refraction (approx)
    el = 90 - zen
    if el > 85: refr = 0
    elif el > 5: te = math.tan(math.radians(el)); refr = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5
    elif el > -0.575: refr = 1735 + el * (-518.2 + el * (103.4 + el * (-12.79 + el * 0.711)))
    else: refr = -20.772 / math.tan(math.radians(el))
    el += refr / 3600
    az = math.degrees(math.acos(max(-1, min(1, ((math.sin(latr) * cos_zen) - math.sin(declr)) / (math.cos(latr) * math.sin(math.radians(zen)))))))
    az = (az + 180) % 360 if ha > 0 else (540 - az) % 360
    return az, el

def sun_vector(az, el):
    """Unit vector toward the sun in ENU (x east, y north, z up)."""
    a, e = math.radians(az), math.radians(el)
    return (math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e))

if __name__ == "__main__":
    import zoneinfo
    tz = zoneinfo.ZoneInfo("America/Los_Angeles")
    for d, h in ((_dt.date(2026, 10, 23), 12), (_dt.date(2026, 12, 21), 12), (_dt.date(2026, 6, 21), 12), (_dt.date(2026, 12, 21), 16)):
        t = _dt.datetime(d.year, d.month, d.day, h, 0, tzinfo=tz).astimezone(_dt.timezone.utc)
        az, el = sun_position(37.7965, -122.4176, t); print(d, f"{h}:00 PT  az={az:.1f} el={el:.1f}")
