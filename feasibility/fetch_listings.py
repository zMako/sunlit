"""Download photos from SF Craigslist rental listings into listings/<id>/."""
import json, re, sys, time, pathlib, requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
ROOT = pathlib.Path(__file__).parent / "listings"
LINKS = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "sf_links.txt"
links = [l.strip() for l in (LINKS).read_text().splitlines() if l.strip()]
want = int(sys.argv[1]) if len(sys.argv) > 1 else 6
MIN_PHOTOS, MAX_PHOTOS = int(__import__("os").environ.get("MIN_PHOTOS", 8)), int(__import__("os").environ.get("MAX_PHOTOS", 24))
got = 0
for url in links:
    if got >= want:
        break
    try:
        html = requests.get(url, headers=UA, timeout=20).text
    except Exception as e:
        print("fail", url, e); continue
    m = re.search(r"imgList = (\[.*?\]);", html, re.S)
    if not m:
        print("no imgList", url); continue
    imgs = json.loads(m.group(1))
    if not (MIN_PHOTOS <= len(imgs) <= MAX_PHOTOS):
        print(f"skip {len(imgs)} photos", url); continue
    title = re.search(r"<span id=\"titletextonly\">(.*?)</span>", html)
    title = title.group(1) if title else ""
    addr = re.search(r'class="mapaddress">(.*?)</div>', html, re.S)
    addr = re.sub("<.*?>", "", addr.group(1)).strip() if addr else ""
    lat = re.search(r'data-latitude="([-\d.]+)"', html); lon = re.search(r'data-longitude="([-\d.]+)"', html)
    pid = url.rstrip("/").split("/")[-1]
    d = ROOT / pid; d.mkdir(exist_ok=True)
    n = 0
    for i, im in enumerate(imgs):
        full = im["url"].replace("_600x450", "_1200x900")
        for cand in (full, im["url"]):
            r = requests.get(cand, headers=UA, timeout=20)
            if r.ok and len(r.content) > 10000:
                (d / f"{i:02d}.jpg").write_bytes(r.content); n += 1; break
        time.sleep(0.2)
    (d / "meta.json").write_text(json.dumps({"url": url, "title": title, "address": addr,
        "lat": lat.group(1) if lat else None, "lon": lon.group(1) if lon else None, "n_photos": n}, indent=1))
    print(f"OK {pid} {n} photos | {title} | {addr}")
    got += 1
print("FETCH_DONE", got)
