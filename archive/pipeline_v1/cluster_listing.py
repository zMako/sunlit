"""Cluster a listing's photos into rooms: python cluster_listing.py <photo_dir> -> prints clusters, writes clusters.json next to photos."""
import sys, json, pathlib, numpy as np, recon
d = pathlib.Path(sys.argv[1]); paths = recon.filter_photos(sorted(str(p) for p in d.glob("*.jpg")))
P = recon.run(paths); M, N = recon.consistency(P); comps = recon.cluster(M, N)
names = [pathlib.Path(p).name for p in paths]
out = [{"room": k, "images": [names[i] for i in c], "idx": c} for k, c in enumerate(comps)]
json.dump(out, open(d / "clusters.json", "w"), indent=1)
for c in out: print(f"room {c['room']}: {c['images']}")
print("isolated:", sum(len(c["idx"]) == 1 for c in out), "of", len(paths))
