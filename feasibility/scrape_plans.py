"""Headed Chrome (your installed Chrome, persistent profile) paced like a person: collect SF rental properties on
Apartments.com, save floor plan images (with dimensions where printed), square footage, and unit photos.

Run it yourself from the project root:
    feasibility/.venv/bin/python feasibility/scrape_plans.py 40
A Chrome window opens; if a captcha appears, solve it in that window and the script continues.
Output: feasibility/plans/<property>/meta.json, plan_*.png|jpg, photo_*.jpg
"""
import sys, re, json, time, random, pathlib, hashlib, requests
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "plans"; OUT.mkdir(exist_ok=True); PROFILE = HERE / ".chrome-profile"
SEARCH = sys.argv[2] if len(sys.argv) > 2 else "https://www.apartments.com/san-francisco-ca/"
MAXP = int(sys.argv[1]) if len(sys.argv) > 1 else 3
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36", "Referer": "https://www.apartments.com/"}

def pause(a=2.5, b=6.0): time.sleep(random.uniform(a, b))
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]

def collect_property_links(page, n):
    links = []; pno = 1
    while len(links) < n and pno <= 12:
        page.goto(SEARCH if pno == 1 else f"{SEARCH}{pno}/", wait_until="domcontentloaded"); pause(3, 6)
        for _ in range(random.randint(3, 6)): page.mouse.wheel(0, random.randint(600, 1400)); pause(0.6, 1.5)
        hrefs = page.eval_on_selector_all("a[href*='apartments.com/']", "els => els.map(e => e.href)")
        for h in hrefs:
            if re.match(r"https://www\.apartments\.com/[a-z0-9-]+/[a-z0-9]{7}/?$", h) and h not in links: links.append(h)
        pno += 1
    return links[:n]

def scrape_property(page, url):
    page.goto(url, wait_until="domcontentloaded"); pause(3, 6)
    for _ in range(random.randint(4, 8)): page.mouse.wheel(0, random.randint(500, 1200)); pause(0.5, 1.2)
    name = page.title(); html = page.content()
    addr = page.eval_on_selector("h1, .propertyAddressContainer", "e => e.innerText") if page.query_selector("h1, .propertyAddressContainer") else ""
    imgs = page.eval_on_selector_all("img", "els => els.map(e => ({src: e.currentSrc || e.src, alt: e.alt || ''}))")
    plans = [i for i in imgs if re.search(r"floorplan|floor-plan|floor_plan", (i["src"] + " " + i["alt"]), re.I)]
    photos = [i for i in imgs if re.search(r"images1\.apartments\.com|cdn\.apartments\.com", i["src"]) and not re.search(r"floorplan", i["src"] + i["alt"], re.I) and "logo" not in i["src"].lower()]
    sqft = sorted(set(int(x.replace(",", "")) for x in re.findall(r"([\d,]{3,5})\s*(?:sq\s*ft|Sq Ft|sqft|square feet)", html)))
    dims = re.findall(r"(\d{1,2})'\s*(?:(\d{1,2})\")?\s*[x×]\s*(\d{1,2})'\s*(?:(\d{1,2})\")?", html)
    beds = re.findall(r"(\d|Studio)\s*(?:bd|bed)", html, re.I)
    return {"url": url, "name": name, "address": addr.strip()[:200], "sqft_values": sqft[:12], "dimension_mentions": len(dims),
            "plan_images": [p["src"] for p in plans][:12], "photo_images": [p["src"] for p in photos][:60], "beds_mentions": beds[:12]}

def download(urls, folder, prefix, maxn):
    folder.mkdir(parents=True, exist_ok=True); n = 0
    for u in urls[:maxn]:
        try:
            r = requests.get(u, headers=UA, timeout=30)
            if r.ok and len(r.content) > 8000:
                ext = ".png" if "png" in r.headers.get("Content-Type", "") else ".jpg"
                (folder / f"{prefix}_{n:02d}{ext}").write_bytes(r.content); n += 1
        except Exception: pass
        time.sleep(random.uniform(0.3, 0.9))
    return n

if __name__ == "__main__":
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=False, viewport={"width": 1380, "height": 900}, locale="en-US")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        links = collect_property_links(page, MAXP); print(f"[scrape] {len(links)} property links")
        kept = 0
        for url in links:
            try: d = scrape_property(page, url)
            except Exception as e: print("[scrape] failed", url, type(e).__name__); continue
            sid = slug(d["name"])[:40] + "-" + hashlib.sha1(url.encode()).hexdigest()[:6]; folder = OUT / sid
            np_ = download(d["plan_images"], folder, "plan", 12) if d["plan_images"] else 0
            nph = download(d["photo_images"], folder, "photo", 40) if d["photo_images"] else 0
            d.update({"n_plan_files": np_, "n_photo_files": nph}); folder.mkdir(exist_ok=True); json.dump(d, open(folder / "meta.json", "w"), indent=1); kept += 1
            print(f"[scrape] {sid}: plans {np_} photos {nph} sqft {d['sqft_values'][:4]} dims {d['dimension_mentions']} | {d['name'][:50]}")
            pause(4, 9)
        ctx.close(); print(f"[scrape] done, {kept} properties saved under {OUT}")
