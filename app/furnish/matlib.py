"""Material library builder/loader. CC0 PBR materials from ambientCG + Poly Haven (+ generated plain paints).
Usage: matlib.py build   (resumable; paces 0.5 s between downloads; logs to materials/download.log)
       matlib.py reindex (rebuild index.json from folders, keeps clip cache)
"""
import io, json, os, re, sys, time, zipfile, glob, colorsys
import requests, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
MAT = os.path.join(ROOT, "materials")
INDEX = os.path.join(MAT, "index.json")
LOG = os.path.join(MAT, "download.log")
UA = "sunlit-calhacks-demo/0.1 (CC0 texture fetch, paced 0.5s)"
S = requests.Session(); S.headers["User-Agent"] = UA
PACE = 0.5

def log(*a):
    m = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(m, flush=True)
    with open(LOG, "a") as f: f.write(m + "\n")

def get(url, **kw):
    for i in range(3):
        try:
            t0 = time.time()
            r = S.get(url, timeout=(10, 20), stream=True, **kw)
            buf = b""
            for ch in r.iter_content(65536):
                buf += ch
                if time.time() - t0 > 60: raise TimeoutError("total time cap")
            r._content = buf
            time.sleep(PACE)
            if r.status_code == 200: return r
            log("HTTP", r.status_code, url)
            if r.status_code in (429, 503): time.sleep(10 * (i + 1))
            else: return None
        except Exception as e:
            log("ERR", url, e); time.sleep(5)
    return None

def save_img(im, path, maxpx=1024):
    im = im.convert("RGB")
    if max(im.size) > maxpx:
        s = maxpx / max(im.size); im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im.save(path, quality=90)

def finish(d):
    im = Image.open(os.path.join(d, "color.jpg")).convert("RGB")
    t = im.copy(); w = min(t.size); t = t.crop(((t.width - w) // 2, (t.height - w) // 2, (t.width + w) // 2, (t.height + w) // 2)).resize((256, 256), Image.LANCZOS)
    t.save(os.path.join(d, "thumb.jpg"), quality=88)

# ---- selection -------------------------------------------------------------
# (displayCategory list, our category, count)
BAD = {"Tiles138"}  # download mirror stalls on this one
CG_PLAN = [
    (["Wood Floor"], "wood_floor", 74), (["Planks"], "wood_floor", 10), (["Bamboo"], "wood_floor", 4),
    (["Tiles"], "tile", 50), (["Terrazzo"], "tile", 8), (["Porcelain"], "tile", 3),
    (["Carpet"], "carpet", 16), (["Tatami"], "carpet", 3),
    (["Painted Plaster"], "plaster", 18), (["Plaster"], "plaster", 7), (["Wallpaper"], "plaster", 6), (["Paint"], "paint", 6),
    (["Concrete"], "concrete", 18), (["Bricks"], "brick", 14), (["Painted Bricks"], "brick", 4),
    (["Marble"], "stone", 14), (["Granite"], "stone", 10), (["Travertine"], "stone", 5), (["Onyx"], "stone", 4),
    (["Chipboard"], "laminate", 8), (["Painted Wood"], "laminate", 14), (["Wood"], "laminate", 10), (["Plastic"], "laminate", 6),
    (["Fabric"], "fabric", 20), (["Leather"], "fabric", 5),
    (["Metal"], "metal", 12), (["Painted Metal"], "metal", 5), (["Sheet Metal"], "metal", 2),
]
PH_PLAN = [  # (required category tag, our category, count, blocked tags)
    ("plaster", "plaster", 40, ["outdoor"]), ("plaster-concrete", "plaster", 20, ["outdoor"]), ("tiles", "tile", 30, []), ("fabric", "fabric", 30, []),
    ("carpet", "carpet", 10, []), ("brick", "brick", 20, []), ("concrete", "concrete", 20, []),
    ("metal", "metal", 20, []), ("wood", "wood_floor", 30, ["outdoor", "raw wood", "bark"]), ("leather", "fabric", 6, []),
    ("marble", "stone", 10, []), ("granite", "stone", 10, []), ("rock", "stone", 15, ["outdoor", "terrain"]),
    ("raw wood", "laminate", 25, ["bark"]), ("floor", "tile", 15, ["outdoor", "wood", "terrain", "road"]),
]
PAINTS = {  # plain painted walls (generated, CC0)
    "off_white": (243, 241, 235), "white": (250, 250, 248), "warm_white": (238, 230, 214), "greige": (186, 176, 162),
    "light_grey": (206, 206, 204), "sage": (160, 174, 148), "navy": (40, 52, 82), "terracotta": (190, 110, 84),
    "beige": (208, 190, 160), "cream": (232, 220, 190), "charcoal": (64, 66, 70), "pale_blue": (178, 202, 218),
}

def process_cg_zip(z, d):
    names = z.namelist()
    def pick(*pats):
        for p in pats:
            for n in names:
                if re.search(p, n, re.I): return n
    maps = {"color": pick(r"_Color\.jpg$"), "normal": pick(r"_NormalGL\.jpg$", r"_Normal\.jpg$"), "roughness": pick(r"_Roughness\.jpg$")}
    if not maps["color"]: return False
    for k, n in maps.items():
        if n: save_img(Image.open(io.BytesIO(z.read(n))), os.path.join(d, k + ".jpg"))
    return True

def build():
    os.makedirs(MAT, exist_ok=True)
    meta = {}
    mp = os.path.join(MAT, "meta.json")
    if os.path.exists(mp): meta = json.load(open(mp))
    # ambientCG
    assets = []
    for off in ([] if os.environ.get('SKIP_CG') else range(0, 2100, 250)):
        r = get(f"https://ambientcg.com/api/v2/full_json?type=Material&include=downloadData,imageData&limit=250&offset={off}")
        if not r: continue
        assets += r.json().get("foundAssets", [])
    log("ambientCG assets listed:", len(assets))
    used = set()
    for cats, ours, n in ([] if os.environ.get('SKIP_CG') else CG_PLAN):
        c = [a for a in assets if a["displayCategory"] in cats and a["assetId"] not in used and a["assetId"] not in BAD][:n]
        for a in c:
            used.add(a["assetId"])
            aid = a["assetId"]; d = os.path.join(MAT, aid)
            meta[aid] = dict(id=aid, name=a["displayName"], category=ours, source="ambientcg", license="CC0", url=a["shortLink"])
            if os.path.exists(os.path.join(d, "thumb.jpg")): continue
            dl = [x for x in a["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"] if x["attribute"] == "1K-JPG"]
            if not dl: log("no 1K-JPG", aid); continue
            os.makedirs(d, exist_ok=True)
            r = get(dl[0]["downloadLink"])
            if not r: continue
            try:
                ok = process_cg_zip(zipfile.ZipFile(io.BytesIO(r.content)), d)
                if ok: finish(d); log("ok", aid, ours)
                else: log("no color map", aid)
            except Exception as e: log("fail", aid, e)
        json.dump(meta, open(mp, "w"), indent=1)
    # Poly Haven
    r = get("https://api.polyhaven.com/assets?t=textures")
    ph = r.json() if r else {}
    log("polyhaven assets:", len(ph))
    for tag, ours, n, block in PH_PLAN:
        c = [k for k, v in ph.items() if tag in v["categories"] and not any(b in v["categories"] for b in block) and "ph_" + k not in meta][:n]
        for k in c:
            aid = "ph_" + k; d = os.path.join(MAT, aid)
            meta[aid] = dict(id=aid, name=ph[k]["name"], category=ours, source="polyhaven", license="CC0", url=f"https://polyhaven.com/a/{k}")
            if os.path.exists(os.path.join(d, "thumb.jpg")): continue
            r = get(f"https://api.polyhaven.com/files/{k}")
            if not r: continue
            f = r.json(); os.makedirs(d, exist_ok=True)
            try:
                for ours_k, keys in (("color", ["Diffuse", "Color"]), ("normal", ["nor_gl"]), ("roughness", ["Rough"])):
                    for kk in keys:
                        u = f.get(kk, {}).get("1k", {}).get("jpg", {}).get("url")
                        if u:
                            rr = get(u)
                            if rr: save_img(Image.open(io.BytesIO(rr.content)), os.path.join(d, ours_k + ".jpg"))
                            break
                if os.path.exists(os.path.join(d, "color.jpg")): finish(d); log("ok", aid, ours)
                else: log("no color", aid)
            except Exception as e: log("fail", aid, e)
        json.dump(meta, open(mp, "w"), indent=1)
    # generated paints
    rng = np.random.RandomState(0)
    for nm, rgb in PAINTS.items():
        aid = "paint_" + nm; d = os.path.join(MAT, aid)
        meta[aid] = dict(id=aid, name="Paint " + nm.replace("_", " "), category="paint", source="generated", license="CC0 (generated flat colour)", url="")
        if os.path.exists(os.path.join(d, "thumb.jpg")): continue
        os.makedirs(d, exist_ok=True)
        from scipy.ndimage import gaussian_filter
        h = gaussian_filter(rng.normal(0, 1, (512, 512)), 1.2)
        n = (gaussian_filter(rng.normal(0, 1, (512, 512)), 0.8) * 1.5)[..., None]
        Image.fromarray(np.clip(np.array(rgb)[None, None] + n, 0, 255).astype(np.uint8)).save(os.path.join(d, "color.jpg"), quality=92)
        gy, gx = np.gradient(h); nrm = np.stack([-gx * 3, -gy * 3, np.ones_like(h)], -1); nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
        Image.fromarray(((nrm * 0.5 + 0.5) * 255).astype(np.uint8)).save(os.path.join(d, "normal.jpg"), quality=90)
        Image.new("RGB", (512, 512), (200, 200, 200)).save(os.path.join(d, "roughness.jpg"), quality=90)
        finish(d)
    json.dump(meta, open(mp, "w"), indent=1)
    reindex()

def load_index():
    return json.load(open(INDEX))

def reindex():
    meta = json.load(open(os.path.join(MAT, "meta.json")))
    old = {m["id"]: m for m in (load_index() if os.path.exists(INDEX) else [])}
    out = []
    for aid, m in sorted(meta.items()):
        d = os.path.join(MAT, aid)
        if not os.path.exists(os.path.join(d, "thumb.jpg")): continue
        m = dict(m)
        m["mean_rgb"] = [round(float(x), 1) for x in np.asarray(Image.open(os.path.join(d, "color.jpg")).convert("RGB")).reshape(-1, 3).mean(0)]
        m["maps"] = [k for k in ("color", "normal", "roughness") if os.path.exists(os.path.join(d, k + ".jpg"))]
        if aid in old and "clip" in old[aid]: m["clip"] = old[aid]["clip"]
        out.append(m)
    json.dump(out, open(INDEX, "w"))
    import collections
    log("index:", len(out), dict(collections.Counter(m["category"] for m in out)))

if __name__ == "__main__":
    {"build": build, "reindex": reindex}[sys.argv[1]]()
