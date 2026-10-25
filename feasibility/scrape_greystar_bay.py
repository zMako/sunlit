"""Greystar properties in the inner Bay Area around SF (Oakland, Berkeley, Emeryville, Alameda, Daly City, San Mateo...),
same source and rules as scrape_greystar.py (robots.txt allows everything but /api/*), floor plans only: the library is
about plans, so no photos are downloaded. Writes feasibility/listings/gs-<id>/ exactly like scrape_greystar.py.

    feasibility/.venv/bin/python feasibility/scrape_greystar_bay.py [max_properties]

Paced 2-4 s per page, ~0.5 s per image. Re-runs skip done folders."""
import sys, re, time, random
ARGS = sys.argv[1:]; sys.argv = sys.argv[:1]   # scrape_greystar reads argv[1] at import
import scrape_greystar as G
CITIES = ["oakland", "berkeley", "emeryville", "alameda", "daly-city", "san-mateo", "burlingame", "millbrae", "san-bruno", "south-san-francisco", "redwood-city", "foster-city", "san-leandro", "brisbane", "pacifica"]
MAXP = int(ARGS[0]) if ARGS else 99

def bay_properties():
    pdp = G.get("https://www.greystar.com/sitemap-pdp.xml").text
    urls = {}
    for u, city, pid in re.findall(r"<loc>(https://www\.greystar\.com/[^<]*?-((?:" + "|".join(CITIES) + r"))-ca/p_(\d+))</loc>", pdp):
        urls.setdefault(pid, (u, city))
    img = G.get("https://www.greystar.com/sitemap-pdp-images.xml").text
    images = {}
    for block in re.findall(r"<url>(.*?)</url>", img, re.S):
        m = re.search(r"/p_(\d+)</loc>", block)
        if m and m.group(1) in urls: images[m.group(1)] = re.findall(r"<image:loc>([^<]+)</image:loc>", block)
    return urls, images

if __name__ == "__main__":
    urls, images = bay_properties(); print(f"[gs-bay] {len(urls)} properties: " + ", ".join(sorted(set(c for _, c in urls.values()))), flush=True)
    for pid, (url, city) in list(urls.items())[:MAXP]:
        plan_imgs = [u for u in images.get(pid, []) if re.search(r"greystarprod/\d+-?PL\d*$", u) or "floorplan" in u.lower()]   # plans only, no photos
        G.scrape(pid, url, plan_imgs); time.sleep(random.uniform(2, 4))
    print("[gs-bay] done")
