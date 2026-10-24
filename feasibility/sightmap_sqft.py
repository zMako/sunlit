"""Per-plan square footage for Greystar buildings from SightMap (the plan-image provider; robots.txt allows /app and /embed).
The asset key in the plan image URL (cdn.sightmap.com/assets/xx/yy/<key>/...) is also the embed key; the embed page names
the JSON API; units carry area (sq ft) and floor_plan_id; floor plans carry image_url. We match our stored plan files to
floor plans by image URL (or by name) and record the median unit area per plan in meta.json floorplans[].sqft.
Usage: sightmap_sqft.py [gs-id ...] (default: all gs-* listings). Paced 1 s per request."""
import sys, re, json, glob, gzip, time, pathlib, statistics as st, requests
ROOT = pathlib.Path(__file__).resolve().parent; UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"}

def api_for(key):
    r = requests.get(f"https://sightmap.com/embed/{key}", headers=UA, timeout=20)
    m = re.search(r"https://sightmap\.com/app/api/v1/[a-z0-9]+/sightmaps/\d+", r.text)
    if not m: return None
    r = requests.get(m.group(0), headers=dict(UA, Accept="application/json"), timeout=20); raw = r.content
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)["data"]

def main():
    lids = sys.argv[1:] or [pathlib.Path(p).name for p in sorted(glob.glob(str(ROOT / "listings/gs-*")))]
    for lid in lids:
        mp = ROOT / "listings" / lid / "meta.json"
        if not mp.exists(): continue
        meta = json.load(open(mp)); fps = meta.get("floorplans", [])
        # plan image urls were not stored; recover the sightmap asset key from the Greystar page cached in the plan link? No: refetch the page once.
        try: page = requests.get(meta["url"], headers=UA, timeout=25).text
        except Exception as e: print(f"[sqft] {lid}: page fetch failed {e}"); continue
        keys = sorted(set(re.findall(r"cdn\.sightmap\.com/assets/[a-z0-9]{2}/[a-z0-9]{2}/([a-z0-9]+)/", page)))
        urls_by_id = {}
        for m in re.finditer(r'\{\\"id\\":\\"(\d+)\\",\\"bathroomCount\\":\d+,\\"bedroomCount\\":\d+,\\"label\\":\\"([^"\\]+)\\"(?:,\\"imageUrl\\":\\"([^"\\]+)\\")?', page): urls_by_id[m.group(1)] = (m.group(2), m.group(3))
        if not keys: print(f"[sqft] {lid}: no sightmap key"); continue
        found = 0
        for key in keys:
            try: d = api_for(key)
            except Exception as e: print(f"[sqft] {lid}: api {key} failed {e}"); continue
            if not d: continue
            areas = {}
            for u in d.get("units", []):
                if u.get("area") and u.get("floor_plan_id"): areas.setdefault(str(u["floor_plan_id"]), []).append(float(u["area"]))
            by_img = {fp.get("image_url", ""): (str(fp["id"]), fp.get("name")) for fp in d.get("floor_plans", [])}
            by_name = {}
            for fp in d.get("floor_plans", []):
                nm = fp.get("name"); nm = json.loads(nm).get("name") if isinstance(nm, str) and nm.startswith("{") else nm
                by_name.setdefault(str(nm).strip().lower(), str(fp["id"]))
            for f in fps:
                gid = f.get("id"); label, img = urls_by_id.get(str(gid), (f.get("name"), None))
                smid = by_img.get(img, (None,))[0] if img else None
                if smid is None and label: smid = by_name.get(str(label).strip().lower())
                if smid and smid in areas:
                    f["sqft"] = round(st.median(areas[smid])); f["sqft_n_units"] = len(areas[smid]); f["sqft_source"] = f"sightmap {key}"; found += 1
            time.sleep(1)
        json.dump(meta, open(mp, "w"), indent=1); print(f"[sqft] {lid}: {found}/{len(fps)} plans got sqft -> {[ (f.get('name'), f.get('sqft')) for f in fps if f.get('sqft')][:6]}")

if __name__ == "__main__": main()
