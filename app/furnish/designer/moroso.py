"""Moroso (www.moroso.it): public /downloads page lists direct links (no login) to 3D zips (materiali/3d/*.zip, some .3ds), 2D dwg, BIM, spec sheets.
Stage 'dl' downloads the 3D zips; stage 'build' converts and builds items."""
import sys, os, html; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

import common as _c
def blender_convert(src, dst):   # same as common.blender_convert but tolerant of non-UTF8 Blender output
    p = subprocess.run([BLENDER, "-b", "-noaudio", "-P", str(H / "blender_convert.py"), "--", str(src), str(dst)], capture_output=True, text=True, errors="replace", timeout=900)
    return p.returncode == 0 and pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 1000
_c.blender_convert = blender_convert

import struct
def read3ds(path):
    """minimal 3DS reader (Blender 5 has no 3ds importer): returns trimesh.Trimesh (Z-up -> Y-up applied)."""
    import numpy as np, trimesh
    data = pathlib.Path(path).read_bytes(); meshes = []
    def walk(off, end, cur):
        while off + 6 <= end:
            cid, ln = struct.unpack_from("<HI", data, off)
            if ln < 6: break
            body = off + 6; nxt = off + ln
            if cid in (0x4D4D, 0x3D3D, 0x4000): 
                if cid == 0x4000:   # object: name (cstring) then children
                    z = data.index(b"\0", body); walk(z + 1, nxt, cur)
                else: walk(body, nxt, cur)
            elif cid == 0x4100: m = {"v": None, "f": None, "M": None}; meshes.append(m); walk(body, nxt, m)
            elif cid == 0x4110 and cur is not None:
                n = struct.unpack_from("<H", data, body)[0]; cur["v"] = np.frombuffer(data, "<f4", n * 3, body + 2).reshape(-1, 3).astype(float)
            elif cid == 0x4120 and cur is not None:
                n = struct.unpack_from("<H", data, body)[0]; cur["f"] = np.frombuffer(data, "<u2", n * 4, body + 2).reshape(-1, 4)[:, :3].astype(int)
            elif cid == 0x4160 and cur is not None:
                cur["M"] = np.frombuffer(data, "<f4", 12, body).reshape(4, 3).astype(float)
            off = nxt
    walk(0, len(data), None)
    parts = []
    for m in meshes:
        if m["v"] is None or m["f"] is None or len(m["f"]) == 0: continue
        v = m["v"]
        if m["M"] is not None:   # local matrix maps world->local in 3ds; vertices are stored local, apply inverse to get world
            M = np.eye(4); M[:3, :4] = m["M"].T
            try: v = (np.linalg.inv(M) @ np.c_[v, np.ones(len(v))].T).T[:, :3]
            except Exception: pass
        if m["f"].max() >= len(v): continue
        parts.append(trimesh.Trimesh(v, m["f"], process=False))
    if not parts: raise ValueError("no mesh")
    t = trimesh.util.concatenate(parts); t.vertices = t.vertices[:, [0, 2, 1]] * [1, 1, -1]
    return t
def to_glb_3ds(src, dst):
    import trimesh
    t = read3ds(src); pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)
    trimesh.Scene([t]).export(str(dst)); return True
B = "moroso"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
def entries():
    r = get("https://www.moroso.it/downloads", cache=R / "cache/downloads.html")
    t = r.text; out = []
    for m in re.finditer(r'<a class="dl-entry-link[^>]*href="([^"]+)"[^>]*>\s*(.*?)\s*<span class="dl-entry-tipologia[^>]*>\s*(.*?)\s*</span>', t, re.S):
        out.append({"url": m.group(1), "name": html.unescape(re.sub(r"\s+", " ", m.group(2))).strip(), "type": html.unescape(re.sub(r"\s+", " ", m.group(3))).strip()})
    return out
def download(url, dst, cap=300e6):
    dst = pathlib.Path(dst)
    if dst.exists() and dst.stat().st_size > 1000: return dst
    from common import _wait, _S
    _wait(url.split("/")[2])
    with _S.get(url, stream=True, timeout=120) as r:
        if r.status_code != 200: print("dl fail", r.status_code, url); return None
        if re.search(r"text/html", r.headers.get("content-type", "")): print("html instead", url); return None
        if int(r.headers.get("content-length", 0)) > cap: print("too big", url); return None
        tmp = dst.with_suffix(dst.suffix + ".part")
        with open(tmp, "wb") as fh:
            for ch in r.iter_content(1 << 20): fh.write(ch)
        tmp.rename(dst)
    return dst
if __name__ == "__main__" and sys.argv[1:2] == ["dl"]:
    E = entries(); print(len(E)); seen = set()
    for e in E:
        if "/materiali/3d/" in e["url"] and e["url"] not in seen:
            seen.add(e["url"]); download(e["url"], R / "files" / e["url"].split("/")[-1])

# ------------------------- build stage -------------------------
import zipfile
def product_pages():
    out = {}
    for s in ["prodotti-sitemap.xml", "prodotti-sitemap2.xml"]:
        r = get("https://moroso.it/" + s, cache=R / f"cache/{s}")
        if not r: continue
        for u in re.findall(r"<loc>(.*?)</loc>", r.text):
            m = re.match(r"https://moroso\.it/en/prodotti/([^/]+)/$", u)
            if m: out[m.group(1)] = u
    return out
def parse_page(u):
    r = get(u, cache=cpath(B, u))
    if not r: return None
    t = r.text; og = lambda p: html.unescape((re.search(r'<meta property="og:%s" content="([^"]*)"' % p, t) or [0, ""])[1])
    desc = og("description"); img = og("image")
    body = html.unescape(re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", t, flags=re.S)))
    m = re.search(r"\n?([^.]{1,60}?) by ([^,]{2,60}), (\d{4})", body)
    designer = year = None
    m = re.search(r"(?:^|\s)by ([A-Z][^,]{2,60}), (\d{4})", body)
    if m: designer, year = m.group(1).strip(), int(m.group(2))
    j = body.find(" by ")
    seg = body[j:j + 1500] if m else body[:1500]
    seg = seg.split("Configure your product")[0].split("Materials Designer")[0]
    # sizes: "cm 200x300", "W 90 D 80 H 70", "cm 90x80xH 70" ...
    dims = re.findall(r"(\d{2,3}(?:[.,]\d)?)\s*[x×]\s*(\d{2,3}(?:[.,]\d)?)(?:\s*[x×]\s*(?:H\s*)?(\d{2,3}(?:[.,]\d)?))?", seg)
    return {"desc": desc, "image": img, "designer": designer, "year": year, "text": seg[:600], "dims_raw": dims}
def cvt(x): return float(str(x).replace(",", "."))
def build(limit=None):
    import trimesh
    t0 = time.time(); items = []; notes = []; fmts = {}; rep = {"models_converted": 0, "bytes_orig": 0, "bytes_opt": 0, "dim_mismatches": 0}
    E = entries(); byurl = {}
    for e in E:
        if "/materiali/3d/" in e["url"]: byurl.setdefault(e["url"], []).append(e)
    pp = product_pages(); seen = set()
    rep["products_listed"] = len(pp)
    for url, es in byurl.items():
        fn = R / "files" / url.split("/")[-1]
        if not fn.exists(): continue
        ext = fn.suffix.lower().lstrip("."); fmts[ext] = fmts.get(ext, 0) + 1
        d = R / "extract" / fn.stem; meshes = []
        if ext == "zip":
            if not d.exists():
                d.mkdir(parents=True)
                try:
                    with zipfile.ZipFile(fn) as z:
                        for n in z.namelist():
                            if n.startswith("__MACOSX") or n.endswith("/") or "/." in n or n.split("/")[-1].startswith("."): continue
                            if n.split(".")[-1].lower() in ("3ds", "obj", "fbx", "mtl", "jpg", "png", "dae", "glb", "gltf", "tga", "bmp", "jpeg"):
                                z.extract(n, d)   # zipfile sanitises '..' components
                except Exception as ex: notes.append(f"bad zip {fn.name}: {ex}"); continue
            meshes = [p for p in d.rglob("*") if p.suffix.lower() in (".3ds", ".obj", ".fbx", ".dae", ".glb")]
            for p in meshes: fmts[p.suffix.lower().lstrip(".") + "(in zip)"] = fmts.get(p.suffix.lower().lstrip(".") + "(in zip)", 0) + 1
        elif ext in ("3ds", "obj", "fbx"): meshes = [fn]
        if not meshes: notes.append(f"no mesh in {fn.name}"); continue
        base = es[0]["name"]; types = sorted({e["type"] for e in es})
        sl = slug(base); page = pp.get(sl) or pp.get(sl.replace("-", "")) or next((v for k, v in pp.items() if k.startswith(sl)), None)
        md = parse_page(page) if page else None
        meshes.sort(key=lambda p: p.name)
        for i, mp in enumerate(meshes[:4]):
            pid = f"dsg-moroso-{slug(base)}-{slug(fn.stem if len(es)==1 else '')}-{slug(mp.stem)}".replace("--", "-").strip("-")
            pid = re.sub(r"-+", "-", pid)
            if pid in seen: continue
            seen.add(pid)
            if mp.suffix.lower() == ".3ds":
                g3 = R / "glb3ds" / (pid + ".glb")
                try: to_glb_3ds(mp, g3)
                except Exception as ex: notes.append(f"3ds parse failed {mp.name}: {ex}"); continue
                info = process_model(pid, g3, None)
            else: info = process_model(pid, mp, None)
            if not info: notes.append(f"process failed {mp.name} ({fn.name})"); continue
            w, dd, h = info["dims"]
            if not (0.1 < max(w, dd, h) < 7 and min(w, dd, h) > 0.01 and h < 3.5):
                notes.append(f"implausible dims {pid} {info['dims']}"); (H / "models" / f"{pid}.glb").unlink(missing_ok=True); (H / "models_opt" / f"{pid}.glb").unlink(missing_ok=True); continue
            rep["models_converted"] += 1; rep["bytes_orig"] += info.get("model_bytes_orig", 0); rep["bytes_opt"] += info.get("model_bytes", 0)
            img = save_image(md["image"], f"{pid}.jpg", "Moroso") if md and md["image"] else None
            cat = categorize(*types, base, fn.stem)
            tcat = {"Poltrone": "armchair", "Divani": "sofa", "Sedie": "dining_chair", "Sgabelli": "stool", "Tavolini": "coffee_table", "Tavoli": "dining_table", "Pouf": "ottoman"}
            for ty in types:
                if ty in tcat: cat = tcat[ty]; break
            it = make_item("Moroso", base, designer=md and md["designer"], category=cat, w=round(w, 3), d=round(dd, 3), h=round(h, 3), model=info, product_url=page or "https://www.moroso.it/downloads",
                           buy_url="https://moroso.it/en/find-a-store/", image=img, description=(md and md["desc"]) or "", year=md and md["year"], source_formats=[mp.suffix.lower().lstrip(".")],
                           variant=(mp.stem if len(meshes) > 1 else None), pid=pid, extra={"listed_dims_m": None, "dims_note": "dims measured from the 3D file (unit auto-detected); page text: " + ((md or {}).get("text", "")[:200]), "model_formats": [mp.suffix.lower().lstrip(".")], "types": types, "source_file": url})
            items.append(it)
        save_items("Moroso", items)
    rep.update(brand="Moroso", with_3d_found=len(byurl), items=len(items), formats_found=fmts, price_coverage=0, walled=False, login_gated=False,
               how_3d_exposed="Public https://www.moroso.it/downloads page lists direct links to materiali/3d/*.zip (3DS inside) and .3ds; no login. Product pages via prodotti sitemap.", notes="; ".join(notes[:50]), minutes=round((time.time() - t0) / 60, 1))
    json.dump(rep, open(R.parent / "report_moroso.json", "w"), indent=1); return rep
if __name__ == "__main__" and sys.argv[1:2] == ["build"]:
    print(build())
