import sys, pathlib, zipfile, re, json, html
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common_dl import *
import requests
B = "string"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
SHARE = "https://shareapi.mediaflow.com"
S = requests.Session(); S.headers.update({"User-Agent": UA})

def js(method, url, **kw):
    common._wait(url.split("/")[2])
    r = S.request(method, url, timeout=60, **kw)
    return r

def products_list():
    r = get("https://www.stringfurniture.com/en/professionals/3d-images", cache=R / "3d-images.html")
    t = html.unescape(r.text)
    i = t.find('"products":[')
    dec = json.JSONDecoder(); arr, _ = dec.raw_decode(t[i + len('"products":'):])
    out = []
    for p in arr:
        c = p["content"]
        out.append({"name": p["name"], "slug": p["slug"], "tags": p.get("tag_list", []), "image": (c.get("image") or {}).get("filename"), "share": (c.get("document") and None) or c.get("external_document"), "pg": c.get("sub_title")})
    return out

def share_files(code):
    cp = R / "cache" / f"share_{code}.json"
    if cp.exists(): return json.load(open(cp))
    tok = js("POST", f"{SHARE}/1/oauth2/token", json={"grant_type": "refresh_token", "refresh_token": code}).json()["access_token"]
    hd = {"Authorization": "Bearer " + tok}
    fl = js("GET", f"{SHARE}/1/files?lang=en", headers=hd).json()
    res = []
    for f in fl:
        d = js("POST", f"{SHARE}/1/file/{f['id']}/downloads?lang=en&sendemail=false", headers=hd, json={"ids": [f["id"]]}).json()
        orig = [x for x in d if x.get("format") == "original"]
        res.append({"id": f["id"], "filename": f["filename"], "size": f["filesize"], "desc": f.get("description"), "url": orig[0]["downloadURL"] if orig else None})
    cp.parent.mkdir(parents=True, exist_ok=True); json.dump(res, open(cp, "w")); return res

def transfer_files(link):
    m = re.search(r"icatserver\.io/mail/([0-9a-f-]+)/([0-9a-f-]+)\?signature=(\w+)", link)
    ten, tid, sig = m.groups(); cp = R / "cache" / f"tr_{tid}.json"
    if cp.exists(): return json.load(open(cp))
    d = js("GET", f"https://api.icatserver.io/v1/transfer/{tid}?signature={sig}", headers={"X-tenant": ten, "Accept": "application/json"}).json()["data"]
    res = [{"id": x["uuid"], "filename": x["name"], "size": x["filesize"], "desc": "", "url": x["files"]["original"]["url"]} for x in d["media"]]
    cp.parent.mkdir(parents=True, exist_ok=True); json.dump(res, open(cp, "w")); return res

if __name__ == "__main__":
    ps = products_list(); print(len(ps), "products")
    for p in ps:
        m = re.search(r"\?([A-Z0-9]+)$", p["share"] or "")
        p["code"] = m.group(1) if m else None
        if not p["code"]:
            if "icatserver" in (p["share"] or ""):
                p["code"] = "T" + re.search(r"/mail/[0-9a-f-]+/([0-9a-f]{8})", p["share"]).group(1)
                fl = transfer_files(p["share"])
            else: print("no share", p["name"]); continue
        else: fl = share_files(p["code"])
        p["files"] = fl
        for f in fl:
            if f["url"] and f["size"] < 300e6:
                dest = R / "files" / p["code"] / f["filename"]
                dl = download(f["url"], dest, session=S)
                print(p["name"], f["filename"], f["size"], dl if dl in (None, "BIG") else "ok", flush=True)
                if dl and dl != "BIG" and dest.suffix == ".zip":
                    ex = R / "files" / p["code"] / "x"
                    if not ex.exists():
                        ex.mkdir(); 
                        try: zipfile.ZipFile(dest).extractall(ex)
                        except Exception as e: print("unzip fail", e)
    json.dump(ps, open(R / "products.json", "w"), indent=1)
