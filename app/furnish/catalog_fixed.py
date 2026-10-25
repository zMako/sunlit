"""catalog.json -> catalog_fixed.json for the gallery and anything else that wants the catalogue the way the planner sees it:
place.fix_item applied (canonical dims, repaired categories), plus per-item notes on how the viewer will dress and orient it."""
import json, pathlib, place
H = pathlib.Path(__file__).parent
def main():
    c = json.load(open(H / "catalog.json")); pal = json.load(open(H / "designer" / "palette.json")) if (H / "designer" / "palette.json").exists() else {}
    bt = json.load(open(H / "designer" / "brand_textures.json")) if (H / "designer" / "brand_textures.json").exists() else {}
    orient = place._orient(); out = []
    for raw in c["items"]:
        i = place.fix_item(raw); o = orient.get(i["id"]); b = bt.get(i["id"]); p = pal.get(i["id"])
        i["dressing"] = ("brand texture" if b and b.get("has_uv") and not b.get("multi_material") else "photo palette" if p else "brand colour" if b else "product words") if i["id"].startswith("dsg-") else "own textures"
        i["orient"] = {"up": o["up"], "front_yaw_deg": o["front_yaw_deg"], "confidence": o.get("confidence"), "method": o.get("method")} if o else None
        i["raw_dims"] = [raw.get("width_m"), raw.get("depth_m"), raw.get("height_m")]; i["raw_category"] = raw.get("category")
        out.append(i)
    json.dump({"items": out, "n": len(out)}, open(H / "catalog_fixed.json", "w"))
    print(len(out), "items ->", H / "catalog_fixed.json")
if __name__ == "__main__": main()
