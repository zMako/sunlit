"""Reproducible pitch metrics for the plan -> 3D apartment engine. No Claude calls; nothing outside app/plan3d/metrics/ is written.
  python bench.py            aggregate the raw data in data/ (run any missing step first), print the table, write summary.json
  python bench.py --fresh    re-run every step: gs_accuracy.py, timing (30 plans), page timing (15 units), CubiCasa eval
  python bench.py --fresh=timing,page   re-run only some steps (gs, timing, page, cubicasa)
Steps: A breadth (sweep/sweep.json, layouts/), B speed (time_one.py per plan in a fresh process; page_time.py in headless
Chrome), C scale accuracy vs printed ground truth (gs_accuracy.py), D CubiCasa5K external benchmark (cubicasa_fetch.py +
cubicasa_eval.py). See METRICS.md for what each number means and its caveats."""
import sys, json, glob, pathlib, random, subprocess, statistics as st, collections, socket, shutil, tempfile
HERE = pathlib.Path(__file__).resolve().parent; P3 = HERE.parent; ROOT = P3.parents[1]; DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
PY = str(ROOT / "feasibility/.venv/bin/python"); SEED = 20261024
W_SRC = {"printed": 1.0, "scaled_from_plan": 0.6, "estimated": 0.3}   # plan_engine.reader_anchor weights
NET_OF_GROSS = 0.85                                                     # rescale.py: room polygons = 0.85 x listed (gross) sqft
fresh = next((a.split("=", 1)[1].split(",") if "=" in a else ["gs", "timing", "page", "cubicasa"] for a in sys.argv[1:] if a.startswith("--fresh")), [])
med = lambda x: st.median(x) if x else None
pct = lambda x: None if x is None else round(100 * x, 1)

# ------------------------------------------------------------------------------------------------ A: breadth
def breadth():
    plans = sorted(glob.glob(str(ROOT / "feasibility/listings/gs-*/plans/plan_*.[jp]*g")))
    sw = json.load(open(P3 / "sweep/sweep.json")); stat = collections.Counter(r["status"] for r in sw)
    idx = json.load(open(P3 / "layouts/index.json")); n_room = n_door = n_win = n_open = 0
    for e in idx:
        L = json.load(open(P3 / "layouts" / f"{e['unit']}.json")); n_room += len(L["rooms"])
        c = collections.Counter(o["type"] for o in L["openings"]); n_door += c["door"]; n_win += c["window"]; n_open += c["opening"]
    return {"plan_images": len(plans), "plan_buildings": len({pathlib.Path(p).parts[-3] for p in plans}), "listing_dirs_gs": len(glob.glob(str(ROOT / "feasibility/listings/gs-*"))),
            "sweep_rows": len(sw), "not_plan": stat["not_plan"], "readable": stat["ok"], "unreadable": stat["error"],
            "walkable_units": len(idx), "walkable_buildings": len({e["listing"] for e in idx}), "rooms": n_room, "doors": n_door, "windows": n_win, "openings": n_open,
            "scale_sources": dict(collections.Counter(((e.get("scale_from") or ["none"])[0]).split(" ")[0] for e in idx))}

# ------------------------------------------------------------------------------------------------ B: speed
def timing(n=30):
    f = DATA / "timing.json"
    if "timing" in fresh or not f.exists():
        plans = sorted(glob.glob(str(ROOT / "feasibility/listings/gs-*/plans/plan_*.[jp]*g"))); pick = random.Random(SEED).sample(plans, n); rows = []
        with tempfile.TemporaryDirectory() as tmp:
            for p in pick:
                import time; t0 = time.perf_counter()
                r = subprocess.run([PY, str(HERE / "time_one.py"), p, tmp], capture_output=True, text=True, cwd=str(HERE))
                wall = time.perf_counter() - t0
                try: row = json.loads(r.stdout.strip().splitlines()[-1])
                except Exception: row = {"unit": p, "ok": False, "error": (r.stderr or "")[-200:]}
                row["wall_s"] = round(wall, 3); rows.append(row); print(f"[timing] {row.get('unit')} ok={row.get('ok')} {wall:.2f}s", flush=True)
        json.dump(rows, open(f, "w"), indent=1)
    return json.load(open(f))

def page(n=15):
    f = DATA / "page.json"
    if "page" in fresh or not f.exists():
        units = [e["unit"] for e in json.load(open(P3 / "layouts/index.json"))]; pick = random.Random(SEED).sample(units, n)
        base, srv = "http://127.0.0.1:8765", None
        try: socket.create_connection(("127.0.0.1", 8765), timeout=1).close()     # the app proxy (README "Run it") if it is up
        except OSError:                                                            # else a plain static server over app/
            srv = subprocess.Popen([PY, "-m", "http.server", "8799", "--bind", "127.0.0.1", "--directory", str(P3.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); base = "http://127.0.0.1:8799"
            import time; time.sleep(1.5)
        try:
            r = subprocess.run([PY, str(HERE / "page_time.py"), base] + pick, capture_output=True, text=True, timeout=1800)
            rows = [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]
        finally:
            if srv: srv.terminate()
        for row in rows: row["server"] = base
        json.dump(rows, open(f, "w"), indent=1)
    return json.load(open(f))

# ------------------------------------------------------------------------------------------------ C: scale accuracy
def wmed(c):
    if not c: return None
    c = sorted(c); tot = sum(w for _, w in c); acc = 0
    for v, w in c:
        acc += w
        if acc >= tot / 2: return v
    return c[-1][0]

def cands(pairs, excl=None):
    out = []
    for p in pairs:
        if p["k"] == excl: continue
        w = W_SRC.get(p["src"], 0.3)
        if p["width_m"] and p["w_px"] > 5: out.append((p["width_m"] / p["w_px"], w))
        if p["depth_m"] and p["h_px"] > 5: out.append((p["depth_m"] / p["h_px"], w))
    return out

def room_err(p, mpp):   # orientation-free: shorter side vs shorter printed side, longer vs longer; area vs printed w x d
    a = sorted([p["w_px"] * mpp, p["h_px"] * mpp]); b = sorted([p["width_m"], p["depth_m"]])
    return [abs(a[0] / b[0] - 1), abs(a[1] / b[1] - 1)], abs(p["area_px"] * mpp ** 2 / (b[0] * b[1]) - 1)

def accuracy():
    f = DATA / "gs_accuracy.json"
    if "gs" in fresh or not f.exists(): subprocess.run([PY, str(HERE / "gs_accuracy.py")], check=True, cwd=str(HERE))
    d = json.load(open(f)); o = {}
    intr_d, intr_a, scale_e, loo_d, loo_a = [], [], [], [], []; u_intr, u_loo = set(), set()
    for r in d:
        pr = [p for p in r.get("pairs", []) if p["printed"]]
        if not pr: continue
        rect = [p for p in pr if p["shape"] == "rectangle"]
        if r.get("has_door_scale"):
            scale_e.append(abs(r["door_mpp"] / wmed(cands(pr)) - 1))
            for p in rect: de, ae = room_err(p, r["door_mpp"]); intr_d += de; intr_a.append(ae); u_intr.add(r["unit"])
        for p in rect:   # leave-one-room-out: scale from every OTHER reader room (engine weights), needs another printed room
            if not any(q["printed"] and q["k"] != p["k"] for q in r["pairs"]): continue
            de, ae = room_err(p, wmed(cands(r["pairs"], excl=p["k"]))); loo_d += de; loo_a.append(ae); u_loo.add(r["unit"])
    o["printed_plans"] = sum(1 for r in d if any(p["printed"] for p in r.get("pairs", [])))
    o["door_scale_vs_printed_scale"] = {"mape": pct(med(scale_e)), "n_plans": len(scale_e), "within_10pct": pct(sum(e <= 0.10 for e in scale_e) / max(1, len(scale_e)))}
    o["door_scale_room_dims"] = {"mape": pct(med(intr_d)), "n_dims": len(intr_d), "n_rooms": len(intr_a), "n_plans": len(u_intr), "area_mape": pct(med(intr_a))}
    o["printed_scale_room_dims_loo"] = {"mape": pct(med(loo_d)), "n_dims": len(loo_d), "n_rooms": len(loo_a), "n_plans": len(u_loo), "area_mape": pct(med(loo_a)),
                                        "within_10pct": pct(sum(e <= 0.10 for e in loo_d) / max(1, len(loo_d)))}
    sq = [r for r in d if r.get("sqft_gt") and r.get("has_door_scale")]
    e = [r["door_area_m2"] / (r["sqft_gt"] * 0.092903 * NET_OF_GROSS) - 1 for r in sq]
    o["door_scale_unit_area_vs_sqft"] = {"mape": pct(med([abs(x) for x in e])), "signed_median": pct(med(e)), "n_units": len(e),
                                         "within_20pct": pct(sum(abs(x) <= 0.2 for x in e) / max(1, len(e)))}
    o["units_no_door_scale"] = sum(1 for r in d if "has_door_scale" in r and not r["has_door_scale"])
    return o

# ------------------------------------------------------------------------------------------------ D: CubiCasa5K
def cubicasa():
    f = DATA / "cubicasa_results.json"
    if "cubicasa" in fresh or not f.exists():
        if not (DATA / "cubicasa5k" / "sample.txt").exists(): subprocess.run([PY, "-I", str(HERE / "cubicasa_fetch.py"), "100", "0"], check=True)
        subprocess.run([PY, str(HERE / "cubicasa_eval.py")], check=True, cwd=str(HERE))
    d = json.load(open(f)); ok = [r for r in d if r.get("ok")]
    ious = [x for r in ok for x in r["room_iou"]]
    S = lambda k: sum(r[k] for r in ok)
    return {"n_sample": len(d), "n_ran": len(ok), "n_rejected": len(d) - len(ok),
            "room_count_exact": pct(sum(r["pred_rooms"] == r["gt_rooms"] for r in ok) / max(1, len(ok))),
            "room_count_within1": pct(sum(abs(r["pred_rooms"] - r["gt_rooms"]) <= 1 for r in ok) / max(1, len(ok))),
            "room_count_mae": round(st.mean(abs(r["pred_rooms"] - r["gt_rooms"]) for r in ok), 2) if ok else None,
            "room_count_ratio_median": round(med([r["pred_rooms"] / max(1, r["gt_rooms"]) for r in ok]), 2) if ok else None,
            "gt_rooms": len(ious), "room_iou_mean": pct(st.mean(ious)) if ious else None, "room_iou_median": pct(med(ious)),
            "rooms_iou50": pct(sum(x >= 0.5 for x in ious) / max(1, len(ious))),
            "room_precision_iou50": pct(S("pred_rooms_matched") / max(1, S("pred_rooms"))),
            "interior_iou_mean": pct(st.mean(r["interior_iou"] for r in ok)) if ok else None, "wall_iou_mean": pct(st.mean(r["wall_iou"] for r in ok)) if ok else None,
            "gt_doors": S("gt_doors"), "gt_windows": S("gt_windows"),
            "door_recall": pct(S("door_found") / max(1, S("gt_doors"))), "door_recall_any_gap": pct(S("door_any_found") / max(1, S("gt_doors"))),
            "window_recall": pct(S("window_found") / max(1, S("gt_windows"))), "window_recall_any_gap": pct(S("window_any_found") / max(1, S("gt_windows"))),
            "door_precision": pct(S("pred_doors_correct") / max(1, S("pred_doors"))), "window_precision": pct(S("pred_windows_correct") / max(1, S("pred_windows"))),
            # Kalervo et al. 2019 (arXiv 1904.01920) Table 5/6, trained multi-task CNN, CubiCasa5K TEST split, pixel semantic segmentation
            "paper_rooms_miou_test": 57.5, "paper_rooms_polygonized_miou_test": 49.3, "paper_wall_iou_test": 73.0, "paper_window_iou_test": 66.8, "paper_door_iou_test": 53.6}

# ------------------------------------------------------------------------------------------------ main
def main():
    A = breadth(); T = timing(); Pg = page(); C = accuracy(); D = cubicasa()
    tok = [r for r in T if r.get("ok")]; walls = [r["wall_s"] for r in tok]; lay = [r["layout_s"] for r in tok]; rex = [r["rooms_export_s"] for r in tok]
    pok = [r for r in Pg if r.get("ok")]; ff = [r["first_frame_s"] for r in pok]
    e2e = med(walls) + med(ff) if walls and ff else None
    E = lambda key, value, unit, label, n, method: {"key": key, "value": value, "unit": unit, "label": label, "n": n, "method": method}
    out = [
        E("plans_processed", A["plan_images"], "plans", "floor plans processed", A["plan_buildings"], f"plan images scraped from {A['plan_buildings']} Greystar SF buildings, every one run through the classical reader (sweep/sweep.json): {A['readable']} readable, {A['unreadable']} unreadable, {A['not_plan']} not a plan"),
        E("walkable_units", A["walkable_units"], "apartments", "apartments rebuilt as walkable 3D", A["walkable_buildings"], f"units in layouts/index.json (layout with >= 2 rooms, opens in apartment.html), from {A['walkable_buildings']} buildings; {round(100 * A['walkable_units'] / max(1, A['plan_images'] - A['not_plan']))}% of the {A['plan_images'] - A['not_plan']} plan images"),
        E("rooms_detected", A["rooms"], "rooms", "rooms detected", A["walkable_units"], "sum of rooms over the walkable layouts"),
        E("doors_detected", A["doors"], "doors", "doors detected", A["walkable_units"], "openings of type door over the walkable layouts (plus %d cased openings)" % A["openings"]),
        E("windows_detected", A["windows"], "windows", "windows detected", A["walkable_units"], "openings of type window over the walkable layouts"),
        E("plan_to_layout_s", round(med(walls), 2) if walls else None, "s", "floor plan to 3D-ready layout, median", len(tok), f"wall clock of a fresh Python process per plan (imports + plan_engine geometry path = `layout --novlm` + rooms_export), 30 seeded random plans on an Apple-silicon laptop CPU, {len(T) - len(tok)} of 30 rejected (not a plan / < 2 rooms) and excluded; excludes the optional cached VLM naming/fixture call"),
        E("first_frame_s", round(med(ff), 2) if ff else None, "s", "page load to first rendered 3D frame, median", len(pok), "headless Chrome (Playwright) on apartment.html?quality=low, navigation start to the first presented frame of the built scene; software GL (SwiftShader), so a real GPU is faster"),
        E("plan_to_walkable_s", round(e2e, 1) if e2e else None, "s", "floor plan to walkable 3D apartment, median", min(len(tok), len(pok)), "sum of the two medians above (plan_to_layout_s + first_frame_s); geometry path, no VLM call"),
        E("door_scale_error", C["door_scale_vs_printed_scale"]["mape"], "%", "scale error from door widths alone (no printed dims)", C["door_scale_vs_printed_scale"]["n_plans"], "median |m_per_px(door width 0.86 m) / m_per_px(printed room dims) - 1| per plan, plans whose printed dimensions plan_reader transcribed"),
        E("printed_dims_room_error", C["printed_scale_room_dims_loo"]["mape"], "%", "room width/depth error vs printed dimensions", C["printed_scale_room_dims_loo"]["n_rooms"], f"median abs % error of each rectangular room's detected width and depth vs its printed dimensions, scale fitted on the OTHER rooms of the plan (leave-one-room-out), {C['printed_scale_room_dims_loo']['n_dims']} dimensions in {C['printed_scale_room_dims_loo']['n_plans']} plans"),
        E("door_scale_unit_area_error", C["door_scale_unit_area_vs_sqft"]["mape"], "%", "unit area error from door widths alone vs printed sq ft", C["door_scale_unit_area_vs_sqft"]["n_units"], f"median |sum of room areas at door scale / (0.85 x printed sq ft) - 1|, signed median {C['door_scale_unit_area_vs_sqft']['signed_median']}%; before the area rule (after it the error is 0 by construction)"),
        E("cubicasa_rooms_iou50", D["rooms_iou50"], "%", "CubiCasa5K rooms recovered (IoU >= 0.5), untrained", D["gt_rooms"], f"share of ground-truth indoor rooms in {D['n_ran']} seeded test-split plans whose best-overlapping detected room has IoU >= 0.5; classical vision, no training; the paper's trained CNN reports 57.5% room-class mIoU (different metric)"),
        E("cubicasa_door_recall", D["door_recall"], "%", "CubiCasa5K doors found, untrained", D["gt_doors"], f"GT doors with a detected door on the same wall line, {D['n_ran']} plans; window recall {D['window_recall']}%"),
    ]
    json.dump(out, open(HERE / "summary.json", "w"), indent=1)
    json.dump({"A_breadth": A, "B_speed": {"layout": {"n": len(tok), "n_failed": len(T) - len(tok), "median_wall_s": med(walls), "median_layout_s": med(lay), "median_rooms_export_s": med(rex), "max_wall_s": max(walls) if walls else None},
               "page": {"n": len(pok), "n_failed": len(Pg) - len(pok), "median_first_frame_s": med(ff), "min": min(ff) if ff else None, "max": max(ff) if ff else None, "server": Pg[0].get("server") if Pg else None}},
               "C_accuracy": C, "D_cubicasa": D}, open(HERE / "details.json", "w"), indent=1)
    print(f"{'key':28s} {'value':>8s} {'unit':10s} {'n':>5s}  label"); print("-" * 110)
    for e in out: print(f"{e['key']:28s} {str(e['value']):>8s} {e['unit']:10s} {str(e['n']):>5s}  {e['label']}")
    print("\nA", json.dumps(A)); print("C", json.dumps(C)); print("D", json.dumps(D))

if __name__ == "__main__": main()
