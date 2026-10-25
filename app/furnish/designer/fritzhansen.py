"""Fritz Hansen: public Asset Bank download centre (downloads.fritzhansen.com), anonymous 'Download original' flow (no login).
Stage 1 crawl search -> asset ids -> titles/descriptions; stage 2 download best mesh per product; stage 3 build items. Resumable."""
import sys, re, json, html, time, zipfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
import requests
B = "https://downloads.fritzhansen.com/assetbank-fritzhansen"; RAW = H / "raw/fritz-hansen"; (RAW / "files").mkdir(parents=True, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = UA
def assets():
    f = RAW / "assets.json"
    if f.exists(): return json.load(open(f))
    ids = {}
    for kw in ["obj", "fbx", "3ds", "dae", "2D, 3D & Revit files", "3D"]:
        for p in range(0, 40):
            r = get(f"{B}/action/search?keywords={requests.utils.quote(kw)}&page={p}", cache=cpath("fritz-hansen", f"s{kw}{p}"), session=S)
            if not r: break
            new = [i for i in re.findall(r"viewAsset\?id=(\d+)", r.text) if i not in ids]
            for i in new: ids[i] = None
            if not new: break
    out = {}
    for i in ids:
        r = get(f"{B}/action/viewAsset?id={i}", cache=cpath("fritz-hansen", f"a{i}"), session=S)
        if not r: continue
        t = r.text
        title = html.unescape(re.search(r"<title>(.*?)</title>", t, re.S).group(1)); title = title.split("Asset details")[-1].strip(" -\n\t\r")
        d = re.search(r'id="attr_4">\s*(.*?)\s*</div>', t, re.S)
        out[i] = {"title": title, "desc": html.unescape(re.sub(r"<[^>]+>", "", d.group(1))).strip() if d else ""}
    json.dump(out, open(f, "w"), indent=1); return out
def fetch(aid):
    """anonymous 'Download original' -> bytes + filename"""
    t = S.get(f"{B}/action/viewAsset?id={aid}").text
    sc = re.search(r'springCsrfToken = "([^"]+)"', t).group(1); time.sleep(DELAY)
    r = S.post(f"{B}/go/download/original?_csrf={sc}", json={"assetIds": [int(aid)], "usageTypeId": None, "details": ""}, timeout=300)
    fn = re.search(r"filename%3D%22([^%]+)%22", r.url); fn = requests.utils.unquote(fn.group(1)) if fn else f"{aid}.bin"
    return (r.content if r.status_code == 200 else None), fn
FMT = {"OBJ": 0, "FBX": 1, "3DS": 2}
def run():
    A = assets(); groups = {}
    for i, a in A.items():
        m = re.match(r"(OBJ|FBX|3DS|3D Studio Max|3ds)\s*-\s*(.+)", a["title"], re.I)
        if m:
            f = "3DS" if m.group(1).lower().startswith(("3d", "3ds")) else m.group(1).upper(); groups.setdefault(m.group(2).strip(), {})[f] = i
    print(len(A), "assets;", len(groups), "products with OBJ/FBX/3DS", flush=True)
    items = []; rep = {"formats": {}, "bytes_o": 0, "bytes_n": 0, "fail": 0, "mismatch": 0}
    for n, (prod, fm) in enumerate(sorted(groups.items())):
        f = min(fm, key=lambda k: FMT[k]); aid = fm[f]; pid = f"dsg-fritz-hansen-{slug(prod)}"
        raw = [p for p in (RAW / "files").glob(f"{aid}_*")]
        if not raw:
            data = None
            for _try in range(3):
                try: data, fn = fetch(aid); break
                except Exception as e: print("retry", aid, e, flush=True); time.sleep(10); S.cookies.clear()
            if not data: rep["fail"] += 1; continue
            p = RAW / "files" / f"{aid}_{fn}"; p.write_bytes(data); time.sleep(DELAY); raw = [p]
        p = raw[0]
        if p.suffix.lower() == ".zip":
            d = RAW / "files" / f"x{aid}"; d.mkdir(exist_ok=True)
            with zipfile.ZipFile(p) as z:
                for nm in z.namelist():
                    if nm.lower().endswith((".obj", ".fbx", ".3ds", ".mtl", ".png", ".jpg")) and ".." not in nm: z.extract(nm, d)
            c = [q for e in (".obj", ".fbx", ".3ds") for q in d.rglob("*" + e)]
            if not c: rep["fail"] += 1; continue
            p = c[0]
        desc = A[aid]["desc"]; m = re.match(r"(.+?) by (.+?) in (\d{4})", desc)
        info = process_model(pid, p, None)
        if not info: rep["fail"] += 1; print("fail", prod); continue
        rep["formats"][f] = rep["formats"].get(f, 0) + 1; rep["bytes_o"] += info["model_bytes_orig"]; rep["bytes_n"] += info["model_bytes"]
        name = prod
        items.append(dict(brand="Fritz Hansen", name=name, designer=m.group(2) if m else None, year=int(m.group(3)) if m else None, model=info, aid=aid, fmt=f, desc=desc))
        print(n, pid, f, info["dims"], flush=True)
    json.dump({"items": items, "rep": rep}, open(RAW / "stage2.json", "w"), indent=1, default=str)
def image_for(prod):
    """first non-3D image asset found by searching the model code"""
    code = prod.split(",")[-1].strip().split("/")[0].strip()
    r = get(f"{B}/action/search?keywords={requests.utils.quote(code)}", cache=cpath("fritz-hansen", "img" + code), session=S)
    if not r: return None
    for m in re.finditer(r'asset-link-(\d+)".*?<img[^>]*src="(https://[^"]+)"', r.text, re.S):
        a = get(f"{B}/action/viewAsset?id={m.group(1)}", cache=cpath("fritz-hansen", "a" + m.group(1)), session=S)
        if a and re.search(r"<title>[^<]*(Details of the image|Packshot|Studio|Product)", a.text, re.I) and not re.search(r"<title>[^<]*(OBJ|FBX|3DS|SketchUp|Revit|AutoCAD|2D)", a.text):
            return html.unescape(m.group(2))
    return None
def items():
    d = json.load(open(RAW / "stage2.json")); out = []
    for x in d["items"]:
        desc = x["desc"]; m = re.match(r"(.+?) by (.+?) in (\d{4})\.?\s*(?:Model:\s*(.+?)\.?)?\s*$", desc)
        typ = m.group(1).strip() if m else x["name"].split(",")[0]
        code = x["name"].split(",", 1)[-1].strip()
        name = f"{typ[0].upper()+typ[1:]} {code}" if code and code.lower() not in typ.lower() else typ
        pid = f"dsg-fritz-hansen-{slug(x['name'])}"
        img = None; iu = image_for(x["name"])
        if iu: img = save_image(iu, f"{pid}.jpg", "fritz-hansen")
        it = make_item("Fritz Hansen", name, designer=x["designer"], year=x["year"], category=categorize(name, x["name"]), model=x["model"], pid=pid,
                       product_url="https://www.fritzhansen.com/en/stores", buy_url="https://www.fritzhansen.com/en/stores", description=desc, image=img,
                       source_formats=[x["fmt"]], extra={"model_formats": [x["fmt"]], "model_code": code})
        out.append(it)
    save_items("Fritz Hansen", out); print(len(out), "items")
if __name__ == "__main__": (items() if "items" in sys.argv else run())
