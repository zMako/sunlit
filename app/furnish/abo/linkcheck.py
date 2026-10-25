"""Mark which Amazon ASIN links are live (GET, paced 3 s, stops after 20 consecutive non-200/404 responses = bot wall).
Dead ones get product_url replaced by the search URL. Resumable via raw/links.json. Usage: linkcheck.py [max]"""
import sys, json, time, pathlib, requests
HERE = pathlib.Path(__file__).resolve().parent; CAT = HERE.parent / "catalog.json"; STATE = HERE / "raw" / "links.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36", "Accept-Language": "en-US"}
state = json.load(open(STATE)) if STATE.exists() else {}; c = json.load(open(CAT)); n = 0; bad = 0; limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9
for it in c["items"]:
    if it.get("source") != "amazon-abo": continue
    asin = it["id"].split("-", 1)[1]
    if asin in state: it["link_live"] = state[asin]; continue
    if n >= limit: continue
    try: r = requests.get(f"https://www.amazon.com/dp/{asin}", headers=UA, timeout=20, allow_redirects=True); code = r.status_code; live = code == 200 and "captcha" not in r.text[:5000].lower()
    except Exception: code, live = 0, False
    bad = bad + 1 if code not in (200, 404) else 0
    state[asin] = live; it["link_live"] = live; n += 1
    if n % 25 == 0: json.dump(state, open(STATE, "w")); print(f"[links] {n} checked, live so far {sum(state.values())}", flush=True)
    if bad >= 20: print("[links] bot wall, stopping", flush=True); break
    time.sleep(3)
for it in c["items"]:
    if it.get("source") == "amazon-abo" and it.get("link_live") is False and it.get("search_url"): it["product_url_dead"] = it.get("product_url"); it["product_url"] = it["search_url"]
json.dump(state, open(STATE, "w")); json.dump(c, open(CAT, "w"), indent=1); print(f"[links] done: {len(state)} checked, {sum(state.values())} live")
