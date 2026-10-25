"""Step 1: parse ABO listings -> raw/cand.json (English, has 3dmodel_id, product_type counts)."""
import gzip, json, glob, collections, pathlib
H = pathlib.Path(__file__).resolve().parent; out = []; allpt = collections.Counter(); ptm = collections.Counter()
def en(l):
    for x in l or []:
        if x.get("language_tag", "").startswith("en"): return x["value"]
for f in sorted(glob.glob(str(H / "raw/x/listings/metadata/listings_*.json.gz"))):
    for line in gzip.open(f, "rt", encoding="utf-8"):
        j = json.loads(line); pt = (j.get("product_type") or [{}])[0].get("value")
        allpt[pt] += 1
        if not j.get("3dmodel_id"): continue
        ptm[pt] += 1
        name = en(j.get("item_name"))
        if not name: continue
        out.append({"item_id": j["item_id"], "pt": pt, "name": name, "model": j["3dmodel_id"], "dims": j.get("item_dimensions"),
            "brand": en(j.get("brand")), "color": en(j.get("color")) or None, "bullets": [x["value"] for x in j.get("bullet_point", []) if x.get("language_tag", "").startswith("en")],
            "img": j.get("main_image_id"), "kw": [x["value"] for x in j.get("item_keywords", []) if x.get("language_tag", "").startswith("en")][:15],
            "node": [n.get("node_name") for n in j.get("node", [])][:1], "country": j.get("country")})
json.dump(out, open(H / "raw/cand.json", "w"))
print("with 3dmodel by pt (all langs):", ptm.most_common()); print("english+model:", len(out), collections.Counter(o["pt"] for o in out).most_common())
