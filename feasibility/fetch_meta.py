"""Re-fetch posting text for kept listings: total square feet (attribute block), bedrooms/baths, body text, dimension mentions."""
import json, re, sys, pathlib, requests, html as H
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
L = pathlib.Path("listings")
for d in sorted(p for p in L.iterdir() if p.is_dir() and (p / "KEEP").exists()):
    m = json.load(open(d / "meta.json")); 
    try: page = requests.get(m["url"], headers=UA, timeout=20).text
    except Exception as e: print(d.name[:6], "fetch failed", e); continue
    body = re.search(r'<section id="postingbody">(.*?)</section>', page, re.S); body = H.unescape(re.sub(r"<[^>]+>", " ", body.group(1))) if body else ""
    body = re.sub(r"\s+", " ", body).strip()
    attrs = " ".join(H.unescape(re.sub(r"<[^>]+>", " ", a)) for a in re.findall(r'<div class="attrgroup">(.*?)</div>', page, re.S)); attrs = re.sub(r"\s+", " ", attrs)
    sqft = re.search(r"(\d{3,5})\s*ft2", attrs + " " + body); br = re.search(r"(\d+)BR", attrs); ba = re.search(r"(\d+(?:\.\d)?)Ba", attrs)
    dims = re.findall(r"(\d{1,2}(?:\.\d)?)\s*[x×']\s*(\d{1,2}(?:\.\d)?)\s*(?:ft|feet|')?", body)
    m.update({"sqft_total": int(sqft.group(1)) if sqft else None, "bedrooms": int(br.group(1)) if br else None, "bathrooms": float(ba.group(1)) if ba else None, "body": body[:4000], "attrs": attrs[:500], "dimension_mentions": dims[:10]})
    json.dump(m, open(d / "meta.json", "w"), indent=1)
    print(f"{d.name[:6]} | sqft {m['sqft_total']} | {m['bedrooms']}BR/{m['bathrooms']}BA | dims in body {dims[:4]} | body {len(body)} chars")
