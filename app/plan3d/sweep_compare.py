"""Compare two sweep.json files: per-building ok / rooms>=2 / doors>0 / windows>0 counts and the deltas, plus totals for plans
with a 2-6 m2 room (a bathroom, areas after the rescale.py area rule; computed from areas_m2, or re-derived when absent) and
plans with more than 16 rooms."""
import sys, json, collections, pathlib
HERE = pathlib.Path(__file__).resolve().parent
A = json.load(open(sys.argv[1])); B = json.load(open(sys.argv[2]))
def bath(r):
    if "bath_2_6" in r: return bool(r["bath_2_6"])
    return None
def summ(rows):
    by = collections.defaultdict(lambda: [0, 0, 0, 0, 0])   # n, ok, rooms>=2, doors>0, windows>0
    for r in rows:
        lid = r["unit"].rsplit("_plan_", 1)[0]; s = by[lid]; s[0] += 1
        if r["status"] == "ok": s[1] += 1; s[2] += r["rooms"] >= 2; s[3] += r["door"] > 0; s[4] += r["window"] > 0
    return by
a, b = summ(A), summ(B)
print(f"{'listing':10s} {'n':>3} | {'ok':>5} {'rooms>=2':>9} {'doors>0':>9} {'win>0':>9}")
tot = [0] * 10
for lid in sorted(set(a) | set(b)):
    x, y = a.get(lid, [0] * 5), b.get(lid, [0] * 5)
    print(f"{lid:10s} {y[0]:3d} | {x[1]:2d}>{y[1]:2d} {x[2]:3d}>{y[2]:3d}   {x[3]:3d}>{y[3]:3d}   {x[4]:3d}>{y[4]:3d}")
    for i in range(1, 5): tot[i] += x[i]; tot[i + 5] += y[i]
print(f"TOTAL ok {tot[1]}>{tot[6]}  rooms>=2 {tot[2]}>{tot[7]}  doors>0 {tot[3]}>{tot[8]}  windows>0 {tot[4]}>{tot[9]}")
def extra(rows):
    ok = [r for r in rows if r["status"] == "ok"]; bt = [bath(r) for r in ok]
    return (sum(1 for v in bt if v) if all(v is not None for v in bt) else "n/a"), sum(1 for r in ok if r["rooms"] > 16), sum(1 for r in ok if r.get("bad_polygons", 0) > 0) if all("bad_polygons" in r for r in ok) else "n/a"
ea, eb = extra(A), extra(B)
print(f"TOTAL with a 2-6 m2 room {ea[0]}>{eb[0]}  rooms>16 {ea[1]}>{eb[1]}  plans with invalid/overlapping polygons {ea[2]}>{eb[2]}")
