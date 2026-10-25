"""Step 3: download GLB (<=40 MB) + small image per selected item. Resumable (skips existing files; state in raw/state.json). Paced.
   ../../../feasibility/.venv/bin/python -I download.py [max_items=400]"""
import json, csv, gzip, sys, time, pathlib, requests
H = pathlib.Path(__file__).resolve().parent; B = "https://amazon-berkeley-objects.s3.amazonaws.com/"; MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 400
SEL = json.load(open(H / "raw/selected.json")); IMG = {r["image_id"]: r["path"] for r in csv.DictReader(gzip.open(H / "raw/images.csv.gz", "rt"))}
ST = H / "raw/state.json"; state = json.load(open(ST)) if ST.exists() else {}   # item_id -> "ok" | "skip:<why>"
(H / "models").mkdir(exist_ok=True); (H / "images").mkdir(exist_ok=True)
S = requests.Session()
def fetch(url, dest, maxb=None):
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i in range(4):
        try:
            with S.get(url, stream=True, timeout=30) as r:
                if r.status_code != 200: return f"http{r.status_code}"
                if maxb and int(r.headers.get("Content-Length", 0)) > maxb: return "toobig"
                with open(tmp, "wb") as f:
                    for ch in r.iter_content(1 << 16): f.write(ch)
            tmp.rename(dest); return "ok"
        except requests.RequestException: time.sleep(3 * (i + 1))
    return "neterr"
cats = {}
for o in SEL: cats.setdefault(o["category"], []).append(o)
order = []  # round-robin by rank/target so every category fills proportionally
for c, L in cats.items():
    prim = sorted([o for o in L if not o["spare"]], key=lambda o: o["rank"]); n = len(prim)
    for o in prim: order.append(((o["rank"] + .5) / n, o))
order.sort(key=lambda x: x[0]); spares = {c: [o for o in sorted(L, key=lambda o: o["rank"]) if o["spare"]] for c, L in cats.items()}
def good(o): return (H / f"models/{o['item_id']}.glb").exists() and (H / f"images/{o['item_id']}.jpg").exists()
def try_item(o):
    i = o["item_id"]
    if good(o): return True
    if state.get(i, "").startswith("skip"): return False
    ip = IMG.get(o["img"])
    if not ip: state[i] = "skip:noimg"; return False
    r = fetch(B + "3dmodels/original/" + o["mpath"], H / f"models/{i}.glb", 40e6)
    if r != "ok": state[i] = "skip:" + r; return False
    r = fetch(B + "images/small/" + ip, H / f"images/{i}.jpg")
    if r != "ok": state[i] = "skip:img" + r; (H / f"models/{i}.glb").unlink(missing_ok=True); return False
    state[i] = "ok"; time.sleep(0.4); return True
done = 0; chosen = []
for _, o in order:
    if done >= MAX: break
    cand = o
    while cand is not None:
        ok = try_item(cand); json.dump(state, open(ST, "w"))
        if ok: chosen.append(cand["item_id"]); done += 1; print(done, cand["category"], cand["item_id"], flush=True); break
        cand = spares[o["category"]].pop(0) if spares[o["category"]] else None
json.dump(chosen, open(H / "raw/chosen.json", "w")); print("done", done)
