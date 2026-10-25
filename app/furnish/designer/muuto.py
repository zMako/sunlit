"""Muuto: 3D zips from Muuto's public Digital Showroom (download.muuto.com, Vocast/Presscloud; linked from every muuto.com product page as '2D, 3D & Revit files'; enforceLogin=0, anonymous).
Same host-key front-end API as HAY. OBJ preferred (3DS fallback via parse3ds.py if present)."""
import sys, re, json, zipfile, pathlib, requests, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common
from common import *
RAW = H / "raw/muuto"; API = "https://presscloud.com/api/digitalshowroom/1/"; HD = {"Authorization": "HOSTKEY download.muuto.com", "Accept": "application/json", "User-Agent": UA}; ACC = 533197669002671
def search(q):
    common._wait("presscloud.com")
    return requests.post(API + "search", json=dict(accountkey=ACC, output="showroom", query=q), headers=HD, timeout=60).json().get("file", [])
def listing():
    f = RAW / "listing.json"
    if f.exists(): return json.load(open(f))
    seen = {}
    for q in ["3D", "obj", "3ds"]:
        for x in search(q):
            if any(t.get("name") == "3D files" for t in x.get("tagsimpel", [])) and x["filename"].lower().endswith(".zip"): seen[x["KEY"]] = x
    z = []
    for x in seen.values():
        tg = {}
        for t in x["tagsimpel"]: tg.setdefault(t["filetagcategory"], []).append(t["name"])
        z.append({"KEY": x["KEY"], "filename": x["filename"], "imageurl": x["imageurl"], "filesize": x["filesize"], "tags": tg})
    json.dump(z, open(f, "w"), indent=1); return z
def download(x):
    p = RAW / "files" / re.sub(r"[^\w.-]", "_", x["imageurl"].split("/")[-1])
    if p.exists() and p.stat().st_size == x["filesize"]: return p
    common._wait("assets.presscloud.com")
    with requests.get("https://assets.presscloud.com" + x["imageurl"], stream=True, headers={"User-Agent": UA}, timeout=300) as r:
        if r.status_code != 200: return None
        with open(p, "wb") as fh:
            for ch in r.iter_content(1 << 20): fh.write(ch)
    return p
def image(fam):
    for x in search(fam):
        if x.get("contenttype") == "image/jpeg" and fam.lower() in " ".join(t.get("name", "") for t in x.get("tagsimpel", [])).lower():
            v = [v for v in x.get("variants", []) if v.get("contenttype") == "image/jpeg"]
            return "https://assets.presscloud.com" + (v[-1]["imageurl"] if v else x["imageurl"])
    return None
def build():
    L = listing(); jobs = []; imgs = {}
    for x in L:
        p = download(x)
        if not p: continue
        try: zf = zipfile.ZipFile(p)
        except Exception: continue
        names = [n for n in zf.namelist() if not n.endswith("/") and ".." not in n and "__MACOSX" not in n]
        objs = [n for n in names if n.lower().endswith(".obj")]; fm = ".obj"
        if not objs: objs = [n for n in names if n.lower().endswith(".3ds")]; fm = ".3ds"
        d = RAW / "x" / p.stem; d.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.lower().endswith((fm, ".mtl", ".jpg", ".png")): zf.extract(n, d)
        for n in objs[:14]: jobs.append((x, d / n, fm))
    print(len(L), "zips", len(jobs), "meshes", flush=True); items = []
    def one(j):
        x, p, fm = j; tg = x["tags"]; fam = (tg.get("Product family") or [x["filename"].replace("-3D.zip", "")])[0]
        stem = p.stem.replace("Muuto", "").replace("_", " ").strip(); sl = slug(stem)
        dm = re.search(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)(?:\s*x\s*(\d+(?:[.,]\d+)?))?\s*cm", p.parent.parent.name + " " + p.stem)
        listed = None
        if dm:
            a, b = float(dm.group(1).replace(",", ".")) / 100, float(dm.group(2).replace(",", ".")) / 100
            listed = (a, b, float(dm.group(3)) / 100 if dm.group(3) else None)
        pid = f"dsg-muuto-{slug(fam)}-{sl}"[:110]
        ptype = (tg.get("Product type") or [""])[0]
        cat = categorize(ptype, fam, stem)
        inf = process_model(pid, p, listed, category=cat if cat != "other" else None)
        if not inf: return None
        if fam not in imgs: imgs[fam] = image(fam)
        im = save_image(imgs[fam], f"{pid}.jpg", "muuto") if imgs.get(fam) else None
        name = fam if slug(fam) in sl else f"{fam} {stem}"
        return make_item("Muuto", name[:90], designer=", ".join(tg.get("Designers", [])) or None, category=cat, w=listed[0] if listed else None, d=listed[1] if listed else None,
                         product_url=f"https://www.muuto.com/product/{fam.replace(' ', '-')}/", description=f"{name} by Muuto. {ptype}. Designer: {', '.join(tg.get('Designers', []))}.", image=im, model=inf, pid=pid,
                         source_formats=[fm[1:].upper()], extra={"model_formats": [fm[1:].upper()], "collection": fam})
    with cf.ThreadPoolExecutor(3) as ex:
        for n, it in enumerate(ex.map(one, jobs)):
            if it: items.append(it)
            if n % 40 == 0: save_items("Muuto", items); print(n, len(jobs), len(items), flush=True)
    save_items("Muuto", items); print("done", len(items))
if __name__ == "__main__": build()
