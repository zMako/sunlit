"""Poliform (www.poliform.it): product pages list public s3 3D files (FBX/OBJ/3DM/MAX/SKP/DWG) behind a lead-form modal in the UI (no login);
file URLs are plain data-file-url attributes in the HTML. Stage 'dl': fetch pages (cached) + FBX/OBJ files. Stage 'build': FBX -> per-variant GLB -> items."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

import common as _c
def blender_convert(src, dst):   # same as common.blender_convert but tolerant of non-UTF8 Blender output
    p = subprocess.run([BLENDER, "-b", "-noaudio", "-P", str(H / "blender_convert.py"), "--", str(src), str(dst)], capture_output=True, text=True, errors="replace", timeout=900)
    return p.returncode == 0 and pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 1000
_c.blender_convert = blender_convert
B = "poliform"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
def pages():
    r = get("https://www.poliform.it/sitemap-pages-en-1.xml", cache=R / "cache/sitemap_en.xml")
    u = re.findall(r"<loc>(.*?)</loc>", r.text)
    return [x for x in u if re.match(r"https://www\.poliform\.it/en/products/[^/]+/$", x)]
def page_files(x):
    r = get(x, cache=cpath(B, x))
    if not r: return None, []
    f = re.findall(r'data-file-url="([^"]+)"[^>]*data-file-title="([^"]*)"', r.text)
    f += [(a, b) for b, a in re.findall(r'data-file-title="([^"]*)"[^>]*data-file-url="([^"]+)"', r.text)]
    return r.text, sorted(set(f))
def download(url, dst, cap=300e6):
    dst = pathlib.Path(dst)
    if dst.exists() and dst.stat().st_size > 1000: return dst
    host = url.split("/")[2]
    from common import _wait, _S
    _wait(host)
    with _S.get(url, stream=True, timeout=120) as r:
        if r.status_code != 200: print("dl fail", r.status_code, url); return None
        if int(r.headers.get("content-length", 0)) > cap: print("too big", url); return None
        tmp = dst.with_suffix(dst.suffix + ".part")
        with open(tmp, "wb") as fh:
            for ch in r.iter_content(1 << 20): fh.write(ch)
        tmp.rename(dst)
    return dst
if __name__ == "__main__" and sys.argv[1:2] == ["dl"]:
    for x in pages():
        t, fl = page_files(x)
        for u, title in fl:
            ext = u.rsplit(".", 1)[-1].lower()
            if ext == "fbx" or (ext == "obj"):   # FBX preferred (units/axes in the file); OBJ kept as fallback
                download(u, R / "files" / u.split("/")[-1])

# ------------------------- build stage -------------------------
import numpy as np
WORDS = [("nightcomplement", "bedside table"), ("mirror", "mirror"), ("bench", "bench"), ("pouf", "pouf"), ("desk", "desk"), ("daybed", "sofa"), ("screen", "other"), ("diningtable", "dining table"), ("coffeetable", "coffee table"), ("sidetable", "side table"), ("bedsidetable", "bedside table"), ("nighttable", "bedside table"),
         ("diningchair", "dining chair"), ("writingdesk", "desk"), ("armchair", "armchair"), ("lowtable", "coffee table"), ("consolle", "console"), ("bookcase", "bookcase"),
         ("poufs", "pouf"), ("sofas", "sofa"), ("stool", "stool"), ("sideboard", "sideboard"), ("wardrobe", "wardrobe"), ("bed", "bed"), ("table", "table"), ("chair", "chair")]
def pretty_type(t):
    t = t.lower()
    for k, v in WORDS:
        if k in t: return v
    return t
def clusters(sc):
    """group top-level nodes of a trimesh Scene into side-by-side variants (clusters of overlapping xz footprints). Returns list of (name, trimesh.Scene)"""
    import trimesh
    g = sc.graph; ch = {}
    for a, b, _ in g.to_edgelist(): ch.setdefault(a, []).append(b)
    def desc(n):
        o = []
        for c in ch.get(n, []): o.append(c); o += desc(c)
        return o
    tops = ch.get(g.base_frame, [])
    groups = []
    for t in tops:
        nodes = [t] + desc(t); geoms = []
        for n in nodes:
            if n in g.nodes_geometry:
                T, gn = g[n]; geoms.append((n, gn, T))
        if not geoms: continue
        pts = []
        for n, gn, T in geoms:
            m = sc.geometry[gn]; bb = m.bounds; c = np.array([[x, y, z, 1] for x in bb[:, 0] for y in bb[:, 1] for z in bb[:, 2]]) @ T.T; pts.append(c[:, :3])
        pts = np.vstack(pts); groups.append({"name": t, "geoms": geoms, "min": pts.min(0), "max": pts.max(0)})
    # union-find on xz overlap
    P = list(range(len(groups)))
    def f(i):
        while P[i] != i: P[i] = P[P[i]]; i = P[i]
        return i
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            a, b = groups[i], groups[j]
            ox = min(a["max"][0], b["max"][0]) - max(a["min"][0], b["min"][0]); oz = min(a["max"][2], b["max"][2]) - max(a["min"][2], b["min"][2])
            if ox > 0 and oz > 0:
                sa = (a["max"][0] - a["min"][0]) * (a["max"][2] - a["min"][2]); sb = (b["max"][0] - b["min"][0]) * (b["max"][2] - b["min"][2])
                if ox * oz > 0.1 * min(sa, sb): P[f(i)] = f(j)
    cl = {}
    for i, gr in enumerate(groups): cl.setdefault(f(i), []).append(gr)
    out = []
    for k, grs in cl.items():
        s = trimesh.Scene()
        for gr in grs:
            for n, gn, T in gr["geoms"]: s.add_geometry(sc.geometry[gn], node_name=n, geom_name=gn, transform=T)
        big = max(grs, key=lambda gr: np.prod(gr["max"] - gr["min"]))
        out.append((big["name"], s))
    return out
def meta(x, html_text):
    t = html_text
    og = lambda p: (re.search(r'<meta property="og:%s" content="([^"]*)"' % p, t) or [None, None])[1]
    import html as H_
    desc = H_.unescape(og("description") or ""); img = og("image")
    title = H_.unescape(og("title") or "")
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", t, flags=re.S); body = re.sub(r"\s+", " ", H_.unescape(body))
    m = re.search(r"Designed by (.+?)(?:, (\d{4}))? Type ([A-Za-z ]+?) (?:Structure|Frame|Base|Top|Seat|Legs|Cover|Upholster)", body)
    designer = year = typ = None
    if m: designer, year, typ = m.group(1).strip()[:80], (int(m.group(2)) if m.group(2) else None), m.group(3).strip()
    else:
        m2 = re.search(r"Designed by ([^,.]{3,60})(?:, (\d{4}))?", body)
        if m2: designer, year = m2.group(1).strip(), (int(m2.group(2)) if m2.group(2) else None)
    mat = None
    if m:
        j = body.find(m.group(0)); seg = body[j + len(m.group(0)) - 10: j + 700]
        seg = re.split(r"COVER FINISHES|FINISHES|Fabrics|Leather\b|Category:", seg)[0]
        mat = re.sub(r"\s+", " ", seg).strip()[:240] or None
    tip = re.findall(r'data-tipologia="([^"]*)"', t); col = re.findall(r'data-collezione="([^"]*)"', t)
    return {"desc": desc, "image": img, "title": title, "designer": designer, "year": year, "type": typ, "materials": mat, "tipologia": tip[0] if tip else None, "collezione": col[0] if col else None}
def build(limit=None):
    import trimesh
    items = []; rep = {"products_listed": 0, "with_3d_found": 0, "models_converted": 0, "formats_found": {}, "dim_mismatches": 0, "bytes_orig": 0, "bytes_opt": 0}
    t0 = time.time(); seen = set(); notes = []
    P_ = pages(); rep["products_listed"] = len(P_)
    for x in P_:
        txt, fl = page_files(x)
        if not txt: continue
        for u, title in fl:
            e = u.rsplit(".", 1)[-1].lower(); rep["formats_found"][e] = rep["formats_found"].get(e, 0) + 1
        fb = [u for u, t_ in fl if u.lower().endswith(".fbx")]
        if not fb: continue
        rep["with_3d_found"] += 1; md = meta(x, txt); pslug = x.rstrip("/").split("/")[-1]
        for u in fb:
            raw = R / "files" / u.split("/")[-1]
            if not raw.exists(): continue
            vdir = R / "variants" / raw.stem; marker = vdir / "done.json"
            if marker.exists(): res = json.load(open(marker))
            else:
                vdir.mkdir(parents=True, exist_ok=True); tmp = vdir / "all.glb"
                if not (tmp.exists() or blender_convert(raw, tmp)): notes.append(f"blender failed {raw.name}"); json.dump([], open(marker, "w")); continue
                try: sc = trimesh.load(str(tmp), force="scene"); cl = clusters(sc)
                except Exception as ex: notes.append(f"parse failed {raw.name}: {ex}"); continue
                res = []
                for name, s in cl:
                    e_ = s.extents; w, d, h = float(e_[0]), float(e_[2]), float(e_[1])
                    res.append({"node": name, "w": w, "d": d, "h": h, "area": w * d})
                # choose up to 3 distinct-dims variants spread by footprint
                res.sort(key=lambda r: r["area"]); keep = []; seenk = set()
                for r in res:
                    k = (round(r["w"] * 20), round(r["d"] * 20), round(r["h"] * 20))
                    if k in seenk: continue
                    seenk.add(k); keep.append(r)
                if len(keep) > 3: keep = [keep[0], keep[len(keep) // 2], keep[-1]]
                byname = {n: s for n, s in cl}
                for i, r in enumerate(keep):
                    fn = vdir / f"v{i}.glb"; byname[r["node"]].export(str(fn)); r["glb"] = str(fn)
                res = keep; json.dump(res, open(marker, "w"))
            for i, r in enumerate(res):
                w, d, h = r["w"], r["d"], r["h"]
                if not (0.1 < max(w, d, h) < 7 and h < 3.5 and min(w, d, h) > 0.01):
                    notes.append(f"rejected implausible dims {raw.name}:{r['node']} {w:.2f}x{d:.2f}x{h:.2f}"); continue
                stem = re.sub(r"^Poliform[-_]", "", raw.stem, flags=re.I); st = [q for q in re.split(r"[-_]+", stem) if q and not re.fullmatch(r"v\d+|\d+|chart|1|2", q, re.I)]
                ti = next((k for k, q in enumerate(st) if any(q.lower().startswith(w) for w, _ in WORDS)), None)
                prod = " ".join(st[:ti] if ti else st[:1]).title() or pslug.title(); typ = pretty_type(st[ti]) if ti is not None else (md["type"] or "").lower()
                if ti is None and len(st) > 1: typ = pretty_type(" ".join(st[1:]))
                name = f"{prod} {typ}".strip()
                ntoks = [q for q in re.split(r"_+", r["node"]) if q]
                lab = [q.lower() for q in ntoks[2:] if re.fullmatch(r"[A-Za-z]{3,12}", q) and q.lower() not in ("poliform",)]
                dimlab = f"{round(w*100)}x{round(d*100)}x{round(h*100)}"; var = dimlab + (" " + " ".join(lab[:2]) if lab else "")
                pid = f"dsg-poliform-{slug(name)}-{slug(dimlab)}"
                if pid in seen: pid += "-" + slug(" ".join(lab[:2]) or str(i))
                if pid in seen: pid += f"-{i}"
                seen.add(pid)
                info = process_model(pid, r["glb"], (w, d, h))
                if not info: notes.append(f"process failed {pid}"); continue
                rep["models_converted"] += 1; rep["bytes_orig"] += info.get("model_bytes_orig", 0); rep["bytes_opt"] += info.get("model_bytes", 0)
                im = save_image(md["image"], f"{pid}.jpg", "Poliform") if md["image"] else None
                cat = categorize(typ, name, md["type"] or "", md["tipologia"] or "")
                items.append(make_item("Poliform", name, designer=md["designer"], category=cat, w=round(w, 3), d=round(d, 3), h=round(h, 3), model=info, product_url=x,
                      buy_url="https://www.poliform.it/en/monobrand-stores/", image=im, description=md["desc"], materials=md["materials"], year=md["year"],
                      source_formats=["fbx"], variant=var, pid=pid, extra={"listed_dims_m": None, "dims_note": "dims measured from the downloaded FBX (Poliform lists none on the page)", "model_formats": ["fbx"], "collection": md["collezione"], "source_file": u}))
            save_items("Poliform", items)
            if limit and len(items) >= limit: break
        if limit and len(items) >= limit: break
    rep.update(brand="Poliform", items=len(items), price_coverage=0, how_3d_exposed="Product pages embed public s3.poliform.it file URLs (data-file-url: FBX/OBJ/3DM/MAX/SKP/DWG) in the Downloads tab; UI wraps them in a lead-form modal, no login needed for the URLs. FBX holds several size/finish variants laid out side by side; split by footprint clustering.",
               walled=False, login_gated=False, notes="; ".join(notes[:60]), minutes=round((time.time() - t0) / 60, 1))
    json.dump(rep, open(R.parent / "report_poliform.json", "w"), indent=1)
    return rep
if __name__ == "__main__" and sys.argv[1:2] == ["build"]:
    print(build(int(sys.argv[2]) if len(sys.argv) > 2 else None))
