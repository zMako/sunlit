"""HAY: 3D zips from HAY's public 'Digital Showroom' (hay.presscloud.com, the iframe on hay.com/professionals/downloads; the site's own front-end API, host-key auth, no login).
Stage 1: list '3D files' zips and download them. Stage 2 (build): per zip pick OBJ (else FBX, 3DS) members, convert, match hay.com product pages + DWR price."""
import sys, re, json, zipfile, pathlib, requests
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
RAW = H / "raw/hay"; API = "https://presscloud.com/api/digitalshowroom/1/"; HD = {"Authorization": "HOSTKEY hay.presscloud.com", "Accept": "application/json", "User-Agent": UA}
def listing():
    f = RAW / "listing.json"
    if f.exists(): return json.load(open(f))
    r = requests.post(API + "search", json=dict(accountkey=619592997100600, output="showroom", query="3D"), headers=HD).json()
    z = [{k: x[k] for k in ("KEY", "filename", "imageurl", "filesize", "created")} | {"tags": [t.get("name") for t in x.get("tagsimpel", [])]} for x in r["file"] if any(t.get("name") == "3D files" for t in x.get("tagsimpel", []))]
    json.dump(z, open(f, "w"), indent=1); return z
def download():
    for x in listing():
        p = RAW / "files" / re.sub(r"[^\w.-]", "_", x["imageurl"].split("/")[-1])
        if p.exists() and p.stat().st_size == x["filesize"]: continue
        if x["filesize"] > 400e6 and "Combinations" not in x["filename"]: pass
        import common; common._wait("assets.presscloud.com")
        with requests.get("https://assets.presscloud.com" + x["imageurl"], stream=True, headers={"User-Agent": UA}, timeout=300) as r:
            if r.status_code != 200: print("fail", x["filename"], r.status_code); continue
            with open(p, "wb") as fh:
                for ch in r.iter_content(1 << 20): fh.write(ch)
        print("got", p.name, p.stat().st_size, flush=True)

# ---------------- stage 2: build ----------------
import html as _h, concurrent.futures as cf
def site_pages():
    r = get("https://www.hay.com/sitemaps/sitemap-products.xml", cache=RAW / "sitemap-products.xml")
    out = {}
    for u in re.findall(r"<loc>([^<]+)</loc>", r.text): out.setdefault(slug(u.rstrip("/").split("/")[-1]), u)
    return out
def page(u):
    r = get(u, cache=cpath("hay", u))
    if not r: return {}
    t = r.text; d = {}
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
    if m:
        try: j = json.loads(m.group(1), strict=False); d["name"] = _h.unescape(j.get("name", "")); d["desc"] = _h.unescape(re.sub(r"<[^>]+>", " ", j.get("description", ""))); d["img"] = j.get("image")
        except Exception: pass
    m = re.search(r'id="designer">.*?<div class="prod-description">(.*?)</div>', t, re.S)
    if m:
        txt = _h.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        mm = re.match(r"^((?:[A-Z][\w'’.\-&ø]*\s?){1,5}?)\s+(?:is|was|are|were|has|have|founded|studied|born|began|graduated)\b", txt)
        d["designer"] = mm.group(1).strip() if mm else None
    m = re.search(r'<h1[^>]*>([^<]+)</h1>', t); d["h1"] = _h.unescape(m.group(1)).strip() if m else None
    return d
def build():
    pages = site_pages(); items = []; rep = {"formats": {}, "bo": 0, "bn": 0, "fail": 0, "mismatch": 0, "zips": 0, "members": 0}
    def fam_url(coll):
        k = slug(coll)
        for s_, u_ in pages.items():
            if s_ == k or s_.startswith(k + "-") or k.startswith(s_ + "-"): return u_
        return None; rep = {"formats": {}, "bo": 0, "bn": 0, "fail": 0, "mismatch": 0, "zips": 0, "members": 0}
    jobs = []
    for z in sorted((RAW / "files").glob("*.zip")):
        try: zf = zipfile.ZipFile(z)
        except Exception: print("bad zip", z); continue
        names = [n for n in zf.namelist() if not n.endswith("/") and "__MACOSX" not in n and ".." not in n]
        fm = None
        for e in (".obj", ".fbx", ".3ds"):
            c = [n for n in names if n.lower().endswith(e)]
            if c: fm = e; break
        if not fm: continue
        rep["zips"] += 1
        coll = re.sub(r"_?3D$", "", z.stem.replace("_", " ")).strip()
        d = RAW / "x" / z.stem; d.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.lower().endswith((fm, ".mtl", ".jpg", ".png")) and fm[1:].upper() in n.upper(): zf.extract(n, d)
        for n in c: jobs.append((coll, d / n, fm))
    print(len(jobs), "meshes in", rep["zips"], "zips", flush=True)
    def one(j):
        coll, p, fm = j
        stem = re.sub(r"\s*\b3D\b\s*$", "", p.stem).strip(); sl = slug(stem)
        dims = re.search(r"L(\d+)\s*x\s*W(\d+)\s*x\s*H(\d+)", stem, re.I)
        listed = (int(dims.group(2)) / 100, int(dims.group(1)) / 100, int(dims.group(3)) / 100) if dims else None
        base = re.sub(r"\s*L\d+\s*x\s*W\d+\s*x\s*H\d+", "", stem, flags=re.I).strip()
        u = pages.get(slug(base)) or pages.get(sl)
        pg = page(u) if u else {}
        pid = f"dsg-hay-{slug(coll) if slug(coll) not in sl else ''}{'-' if slug(coll) not in sl else ''}{sl}".replace("dsg-hay--", "dsg-hay-")
        nm = pg.get("h1") or pg.get("name") or (stem if (slug(coll) in sl or sl.split("-")[0] == slug(coll).split("-")[0]) else f"{coll} {stem}")
        fam = pg if pg else (page(fam_url(coll)) if fam_url(coll) else {})
        path = (u or fam_url(coll) or "").lower()
        cat = categorize(path.split("/hay/")[-1].replace("/", " "), nm, coll)
        info = process_model(pid, p, listed, category=cat if cat != "other" else None)
        if not info: return ("fail", pid)
        img = None
        if pg.get("img"):
            iu = pg["img"] if pg["img"].startswith("http") else "https://www.hay.com" + pg["img"]
            img = save_image(iu, f"{pid}.jpg", "hay")
        it = make_item("HAY", nm, designer=fam.get("designer"), category=cat, w=listed[0] if listed else None, d=listed[1] if listed else None, h=listed[2] if listed else None,
                       product_url=u or fam_url(coll) or "https://www.hay.com/", description=pg.get("desc") or fam.get("desc") or f"{nm} by HAY, part of the {coll} family.", image=img, model=info, pid=pid,
                       source_formats=[fm[1:].upper()], extra={"model_formats": [fm[1:].upper()], "collection": coll})
        return ("ok", it, fm)
    with cf.ThreadPoolExecutor(3) as ex:
        for n, r in enumerate(ex.map(one, jobs)):
            if r[0] == "fail": rep["fail"] += 1; continue
            it = r[1]; items.append(it); rep["formats"][r[2]] = rep["formats"].get(r[2], 0) + 1; rep["bo"] += it["model_bytes_orig"]; rep["bn"] += it["model_bytes"]
            if n % 40 == 0: save_items("HAY", items); print(n, len(jobs), len(items), flush=True)
    save_items("HAY", items); json.dump(rep, open(RAW / "build_rep.json", "w")); print("done", rep)
if __name__ == "__main__": (download() if "build" not in sys.argv else build())
