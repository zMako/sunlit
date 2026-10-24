import json, pathlib, numpy as np
rows = []
for d in sorted(pathlib.Path("out").iterdir()):
    if not (d / "analysis.json").exists() or not (d / "regcheck.json").exists() or d.name.startswith(("smoke", "sub_")): continue
    a = json.load(open(d / "analysis.json")); r = json.load(open(d / "regcheck.json")); st = json.load(open(d / "stats.json"))
    meta = json.load(open(pathlib.Path("listings") / d.name / "meta.json"))
    S = st["n_images"]
    # connected components over consistent pairs
    adj = {i: set() for i in range(S)}
    for i, j, n, m in r["pairs"]:
        if m >= 0.5: adj[i].add(j); adj[j].add(i)
    seen, comps = set(), []
    for i in range(S):
        if i in seen: continue
        stack, comp = [i], set()
        while stack:
            k = stack.pop()
            if k in seen: continue
            seen.add(k); comp.add(k); stack.extend(adj[k] - seen)
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)
    ch = np.array(a["camera_heights_m_if_ceiling_2.6"])
    doors = np.array(a["door_heights_m_if_ceiling_2.6"]); doors_ok = int(np.sum(np.abs(doors - 2.03) / 2.03 <= 0.25))
    wins = a["windows"]; wins_vert = [w for w in wins if w["normal_horizontality_deg"] >= 75]
    sized = [w for w in wins_vert if w["width_m"] and 0.4 <= w["width_m"] <= 4 and w["height_m"] and 0.5 <= w["height_m"] <= 3]
    rows.append({"id": d.name[:6], "title": meta["title"][:38], "imgs": S, "sec": st["inference_s"],
                 "rooms>=3": sum(len(c) >= 3 for c in comps), "biggest": len(comps[0]), "isolated": sum(len(c) == 1 for c in comps),
                 "cam_h_med": round(float(np.median(ch)), 2), "cam_h_iqr": round(float(np.subtract(*np.percentile(ch, [75, 25]))), 2),
                 "doors_ok/all": f"{doors_ok}/{len(doors)}", "win_dets": len(wins), "win_on_wall": len(wins_vert), "win_sized": len(sized),
                 "win_w_med": round(float(np.median([w["width_m"] for w in sized])), 2) if sized else None})
import pandas as pd
pd.set_option("display.width", 250); print(pd.DataFrame(rows).to_string(index=False))
