"""Louis Poulsen: public download-center API (commerce.louispoulsen.com/api/downloadcenter/list?type=fbx) lists per-variant FBX files without login.
Product data (designer, dims, colour, EUR price by SAP number) comes from the product pages' embedded JSON. Run louis_poulsen_fetch.py first (caches pages)."""
import sys; sys.path.insert(0, "/Users/maciejkopiec/sunlit/app/furnish/designer")
from common import *
import html as _html
BR = "Louis Poulsen"; B = "louis-poulsen"; R = H / "raw" / B; (R / "files").mkdir(parents=True, exist_ok=True)
C = R / "cache"
CAT_BY_PATH = [("pendants", "pendant_lamp"), ("table-lamps", "table_lamp"), ("portable-lamps", "table_lamp"), ("floor-lamps", "floor_lamp"), ("suspended", "pendant_lamp")]

def load_pages():
    pages = {}; sap = {}
    for f in C.glob("*.html"):
        t = f.read_text(errors="replace").replace('\\"', '"').replace("\\\\", "\\")
        for m in re.finditer(r'"sapId":"(\d+)","dimensions":[^{}]*?"price":(\{"amount":[\d.]+,"currency":"\w+"\})', t):
            sap[m.group(1)] = json.loads(m.group(2))
        m = re.search(r'name="Files3D" value="([^"]*)"', t.replace('\\"', '"'))
        raw = f.read_text(errors="replace")
        m = re.search(r'name="Files3D" value="([^"]*)"', raw)
        if not m: continue
        can = re.search(r'rel="canonical" href="([^"]*)"', raw); can = can.group(1) if can else None
        for pid in set(re.findall(r"(\d{5})-\d+-01:\d+", m.group(1))):
            i = t.find('"variants":[{"id":"%s-' % pid)
            if i < 0: continue
            try: arr, _ = json.JSONDecoder().raw_decode(t[i + len('"variants":'):])
            except Exception: continue
            title = re.search(r"<title>([^<]*)</title>", raw); title = _html.unescape(title.group(1)).split("|")[0].strip() if title else None
            md = re.search(r'<meta name="description" content="([^"]*)"', raw); md = _html.unescape(md.group(1)) if md else ""
            des = re.search(r'Design by</div><a[^>]*>([^<]+)<', raw)
            if pid not in pages or len(arr) > len(pages[pid]["variants"]):
                pages[pid] = {"url": can, "title": title, "desc": md, "designer": _html.unescape(des.group(1)) if des else None, "variants": {v["sapMaterialNumber"]: v for v in arr}}
    return pages, sap

def mm(x):
    try: return float(re.sub(r"[^\d.]", "", str(x))) / 1000 or None
    except Exception: return None

def main():
    t0 = time.time()
    lst = get("https://commerce.louispoulsen.com/api/downloadcenter/list?type=fbx&locale=en", cache=cpath(B, "list-fbx", "json")).json()
    dcp = {p["id"]: p["name"] for p in get("https://commerce.louispoulsen.com/api/downloadcenter/products?locale=en", cache=cpath(B, "dcprods", "json")).json()}
    pages, sap = load_pages()
    items = []; notes = []; rep = dict(conv=0, mism=0, price=0, bo=0, bp=0)
    seen_pid = set()
    for n, f in enumerate(lst):
        fid = f["id"]; pid, s = fid.split("-")[0], fid.split("-")[1]
        pg = pages.get(pid)
        if not pg: notes.append(f"no page for product {pid} {dcp.get(pid)}"); continue
        v = pg["variants"].get(s)
        raw_name = re.sub(r"^\d+_", "", f["displayName"]).rsplit(".", 1)[0]
        base = pg["title"] or dcp.get(pid) or raw_name
        size = v.get("sizeText") if v else None; col = v.get("colorText") if v else None
        variant = " ".join(x for x in (size, col) if x) or raw_name
        name = base
        iid = f"dsg-louis-poulsen-{slug(base)}-{s}"
        dst = R / "files" / f"{pid}-{s}.fbx"
        r = get("https://commerce.louispoulsen.com" + f["downloadUrl"], cache=dst, binary=True)
        if not r: notes.append(f"download failed {fid}"); continue
        w = mm(v.get("width")) if v else None; d_ = mm(v.get("length")) if v else None; h = mm(v.get("height")) if v else None
        pend = "pendant" in base.lower() or "/pendants/" in (pg["url"] or "")
        listed = (w, d_, h) if (w or d_ or h) else None
        if pend: listed = (w, d_, None) if (w or d_) else None   # listed height is shade only; FBX includes the suspension cord
        info = process_model(iid, dst, listed)
        if not info: notes.append(f"convert failed {fid} {raw_name}"); continue
        dm = info["dims"]
        bad = False
        if listed:
            def off(a, b): return b and abs(math.log(max(a, 1e-6) / b)) > math.log(1.35)
            e1 = any(off(a, b) for a, b in zip(dm, listed))
            e2 = any(off(a, b) for a, b in zip((dm[1], dm[0], dm[2]), listed))
            bad = e1 and e2
        if pend and listed and h and dm[2] < h * 0.8: bad = True
        if bad:
            rep["mism"] += 1; notes.append(f"dim mismatch {iid}: listed {listed} model {dm}")
            for q in (H / "models" / f"{iid}.glb", H / "models" / f"{iid}.json", H / "models_opt" / f"{iid}.glb"): q.unlink(missing_ok=True)
            continue
        rep["conv"] += 1; rep["bo"] += info["model_bytes_orig"]; rep["bp"] += info["model_bytes"]
        p = sap.get(s); price = p["amount"] if p else None; cur = p["currency"] if p else None
        if price: rep["price"] += 1
        img = None
        if v and v.get("media"):
            for m in v["media"]:
                if not m.get("isVideo"):
                    img = save_image(m["url"], iid + ".jpg", BR)
                    if img: break
        path = (pg["url"] or "")
        cat = next((c for k, c in CAT_BY_PATH if f"/{k}/" in path), None) or ("pendant_lamp" if "pendant" in base.lower() else None) or "other"
        mats = "; ".join(x for x in (v.get("otherInformationText") if v else None,) if x)[:300] or None
        desc = pg["desc"]
        it = make_item(BR, f"{base} {variant}".strip() if variant else base, designer=pg["designer"], category=cat, w=w, d=d_, h=h, price=price, currency=cur,
                       price_source="brand shop EUR" if price else None, product_url=pg["url"], buy_url=pg["url"], image=img, model=info, description=desc, materials=mats,
                       colours=[col] if col else None, year=None, source_formats=["fbx"], pid=iid,
                       extra={"listed_dims_m": {"w": w, "d": d_, "h": h}, "model_formats": ["fbx"], "variant": variant, "sap": s})
        items.append(it)
        if len(items) % 5 == 0: save_items(BR, items)
    save_items(BR, items)
    rep = {"brand": BR, "products_listed": len(dcp), "with_3d_found": len(lst), "models_converted": rep["conv"], "items": len(items), "formats_found": {"fbx": len(lst)},
           "price_coverage": rep["price"], "how_3d_exposed": "Public Download Center JSON API (commerce.louispoulsen.com/api/downloadcenter/list?type=fbx + /download), per-variant FBX, no login (also revit/ifc/dxf types)",
           "walled": False, "login_gated": False, "notes": "; ".join(notes)[:3000], "dim_mismatches": rep["mism"], "bytes_orig": rep["bo"], "bytes_opt": rep["bp"], "minutes": round((time.time() - t0) / 60, 1)}
    json.dump(rep, open(R.parent / "report_louis-poulsen.json", "w"), indent=1); print(rep)
if __name__ == "__main__": main()
