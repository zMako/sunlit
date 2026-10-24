"""Local server for the room platform: static files, listing photos, room status, and a one-worker render queue.
GET /api/status            -> all rooms of kept listings with status (queued | rendering | shell | done)
POST/GET /api/render?room= -> queue a room (build + panorama + completion)
GET /listings/<id>/<f>.jpg -> listing photo (read-only)"""
import http.server, urllib.parse, urllib.request, pathlib, sys, json, threading, subprocess, time, os, hashlib
ROOT = pathlib.Path(__file__).parent.resolve(); LIST = ROOT.parent / "feasibility" / "listings"; PY = str(ROOT.parent / "feasibility" / ".venv" / "bin" / "python")
QUEUE, LOCK, STATE = [], threading.Lock(), {"current": None, "log": []}

def short(lid): return lid if lid.startswith(("gs-", "rsn-")) else lid[:6]   # Craigslist ids are 22 chars; landlord ids are short and must stay unique
def listing_of(short_id): return next((p.name for p in LIST.iterdir() if p.name == short_id), None) or next((p.name for p in LIST.iterdir() if p.name.startswith(short_id)), None)
def room_key(lid, k): return f"p2_{short(lid)}_{{type}}_{k}"

def rooms_of(lid):
    d = LIST / lid; g = d / "roomgraph.json"; meta = json.load(open(d / "meta.json")) if (d / "meta.json").exists() else {}
    if not g.exists(): return []
    out = []
    for k, r in enumerate(json.load(open(g))["rooms"]):
        if len(r["photos"]) < 2 or not r.get("has_exterior_window"): continue
        name = f"p2_{short(lid)}_{r['type']}_{k}"; done = (ROOT / "rooms" / f"{name}_polished.glb").exists() and (ROOT / "rooms" / f"{name}_pano" / "px_done.png").exists()
        shell = (ROOT / "rooms" / f"{name}.glb").exists(); meta_r = json.load(open(ROOT / "rooms" / f"{name}.json")) if (ROOT / "rooms" / f"{name}.json").exists() else {}
        status = "rendering" if STATE["current"] == name else ("queued" if name in QUEUE else ("done" if done else ("shell" if shell else "not built")))
        out.append({"name": name, "listing": lid, "title": meta.get("title", lid)[:60], "label": r["name"], "type": r["type"], "photos": [f"/listings/{lid}/{i:02d}.jpg" for i in r["photos"]],
                    "status": status, "plan": f"rooms/{name}_plan.png" if (ROOT / "rooms" / f"{name}_plan.png").exists() else None,
                    "variants": [v for v in ("A", "B") if (ROOT / "rooms" / f"{name}_{v}_polished.glb").exists()],
                    "area_m2": meta_r.get("area_m2"), "n_windows": len(meta_r.get("windows", [])), "n_walls": len(meta_r.get("edges", [])), "vlm_ratio": meta_r.get("vlm_area_ratio")})
    return out

def status():
    kept = sorted(p for p in LIST.iterdir() if p.is_dir() and (p / "KEEP").exists()); rooms = []
    for p in kept: rooms += rooms_of(p.name)
    return {"rooms": rooms, "queue": list(QUEUE), "current": STATE["current"], "log": STATE["log"][-20:]}

def worker():
    while True:
        with LOCK: name = QUEUE.pop(0) if QUEUE else None
        if not name: time.sleep(1); continue
        STATE["current"] = name; lid6, k = name.split("_")[1], name.split("_")[-1]
        try:
            lid = listing_of(lid6); g = json.load(open(LIST / lid / "roomgraph.json"))["rooms"][int(k)]
        except Exception as e:
            STATE["log"].append(f"{name}: cannot resolve listing ({type(e).__name__})"); STATE["current"] = None; continue
        photos = ",".join(f"{i:02d}.jpg" for i in g["photos"]); t = time.time()
        env = dict(os.environ, FIT="1", VLM="1", PANO="1", ROOM_LABEL=f"{g.get('type', 'other')}: {g.get('name', '')}")
        b = subprocess.run([PY, str(ROOT / "pipeline2" / "build_room2.py"), str(LIST / lid), name, photos, "2.6"], capture_output=True, text=True, env=env)
        ok = any(l.startswith("[p2]") for l in b.stdout.splitlines())
        if ok: c = subprocess.run([PY, str(ROOT / "pipeline2" / "complete.py"), name], capture_output=True, text=True); ok = "[complete] wrote" in c.stdout
        STATE["log"].append(f"{time.strftime('%H:%M:%S')} {name}: {'done' if ok else 'FAILED'} in {time.time()-t:.0f}s" + ("" if ok else " | " + (b.stderr or c.stderr if ok is False else "")[-300:]))
        STATE["current"] = None
        # the viewer index
        try:
            import glob; names = sorted(os.path.basename(p)[:-5] for p in glob.glob(str(ROOT / "rooms" / "*.json")) if not p.endswith("index.json") and os.path.exists(p[:-5] + ".glb")); json.dump(names, open(ROOT / "rooms" / "index.json", "w"))
        except Exception: pass

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(ROOT), **k)
    def log_message(self, fmt, *args):
        msg = fmt % args
        if "code 4" in msg or "code 5" in msg: sys.stderr.write(msg + "\n")
    def reply(self, body, ct="application/json"):
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); rel = urllib.parse.unquote(u.path)
        if "/." in rel or ".." in rel: return self.send_error(403)
        if rel == "/api/status": return self.reply(json.dumps(status()).encode())
        if rel == "/api/render":
            name = dict(urllib.parse.parse_qsl(u.query)).get("room")
            with LOCK:
                if name and name not in QUEUE and STATE["current"] != name: QUEUE.append(name)
            return self.reply(json.dumps({"queued": list(QUEUE)}).encode())
        if rel == "/api/furnish":
            name = dict(urllib.parse.parse_qsl(u.query)).get("room", "")
            if not name or "/" in name or ".." in name: return self.send_error(400)
            f = ROOT / "furnish" / "plans" / f"{name}.json"
            if self.command == "POST":
                n = int(self.headers.get("Content-Length", "0") or 0); body = self.rfile.read(n) if n else b""
                try: plan = json.loads(body or b"{}")
                except Exception: return self.send_error(400)
                f.parent.mkdir(parents=True, exist_ok=True); plan["room"] = name; json.dump(plan, open(f, "w"), indent=1); return self.reply(json.dumps({"saved": name, "n": len(plan.get("items", []))}).encode())
            if f.exists(): return self.reply(f.read_bytes())
            return self.send_error(404)
        if rel == "/api/img":   # same-origin copy of a product image so WebGL can use it as a texture (CORS); ikea.com only
            url = dict(urllib.parse.parse_qsl(u.query)).get("u", ""); host = urllib.parse.urlsplit(url).hostname or ""
            if not (host == "www.ikea.com" or host.endswith(".ikea.com")): return self.send_error(403)
            cache = ROOT / "furnish" / "imgcache"; cache.mkdir(parents=True, exist_ok=True); f = cache / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
            if not f.exists():
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"})
                    with urllib.request.urlopen(req, timeout=20) as r: f.write_bytes(r.read())
                except Exception: return self.send_error(502)
            return self.reply(f.read_bytes(), "image/jpeg")
        if rel == "/api/model":   # same-origin copy of a product 3D model (GLB) for the viewer; web-api.ikea.com only; opt-in switch in the panel
            url = dict(urllib.parse.parse_qsl(u.query)).get("u", ""); host = urllib.parse.urlsplit(url).hostname or ""
            if not host.endswith("ikea.com"): return self.send_error(403)
            cache = ROOT / "furnish" / "modelcache"; cache.mkdir(parents=True, exist_ok=True); f = cache / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".glb")
            if not f.exists():
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"})
                    with urllib.request.urlopen(req, timeout=40) as r: f.write_bytes(r.read())
                except Exception: return self.send_error(502)
            return self.reply(f.read_bytes(), "model/gltf-binary")
        if rel == "/api/furnish/auto":   # plan.py <room> [--budget N] [--style "..."] writes furnish/plans/<room>.json and prints a one-line JSON summary
            q = dict(urllib.parse.parse_qsl(u.query)); name = q.get("room", ""); planner = ROOT / "furnish" / "plan.py"
            if not name or "/" in name or ".." in name or not planner.exists() or not (ROOT / "rooms" / f"{name}.json").exists(): return self.send_error(404)
            cmd = [PY, str(planner), name]
            if q.get("budget"): cmd += ["--budget", q["budget"]]
            if q.get("style"): cmd += ["--style", q["style"]]
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT.parent), env=dict(os.environ), timeout=600)
            if r.returncode != 0: self.send_response(500); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write((r.stderr or r.stdout)[-1200:].encode()); return
            return self.reply((r.stdout.strip().splitlines() or ["{}"])[-1].encode())
        if rel == "/api/agent/furnish":   # server-sent events from agent.py furnish: one event per item placed/rejected
            q = dict(urllib.parse.parse_qsl(u.query)); name = q.get("room", "")
            if not name or "/" in name or ".." in name or not (ROOT / "rooms" / f"{name}.json").exists(): return self.send_error(404)
            cmd = [PY, str(ROOT / "furnish" / "agent.py"), "furnish", name]
            if q.get("budget"): cmd += ["--budget", q["budget"]]
            if q.get("style"): cmd += ["--style", q["style"]]
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close"); self.end_headers()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=str(ROOT.parent), env=dict(os.environ), bufsize=1)
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if not line.startswith("{"): continue
                    self.wfile.write(f"data: {line}\n\n".encode()); self.wfile.flush()
                self.wfile.write(b"data: {\"event\": \"end\"}\n\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): proc.kill()
            return
        if rel == "/api/agent/chat":   # POST {room, message, plan, budget, style} -> agent.py chat -> {reply, ops, plan}
            n = int(self.headers.get("Content-Length", "0") or 0); body = self.rfile.read(n) if n else b"{}"
            try: req = json.loads(body or b"{}")
            except Exception: return self.send_error(400)
            name = req.get("room", "")
            if not name or "/" in name or ".." in name or not (ROOT / "rooms" / f"{name}.json").exists(): return self.send_error(404)
            r = subprocess.run([PY, str(ROOT / "furnish" / "agent.py"), "chat", name], input=json.dumps(req), capture_output=True, text=True, cwd=str(ROOT.parent), env=dict(os.environ), timeout=300)
            out = (r.stdout.strip().splitlines() or ["{}"])[-1]
            return self.reply(out.encode() if out.startswith("{") else json.dumps({"error": (r.stderr or r.stdout)[-800:]}).encode())
        if rel.startswith("/listings/") and rel.endswith(".jpg"):
            p = (LIST / rel[len("/listings/"):]).resolve()
            if LIST.resolve() in p.parents and p.exists(): return self.reply(p.read_bytes(), "image/jpeg")
            return self.send_error(404)
        return super().do_GET()
    do_POST = do_GET

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    threading.Thread(target=worker, daemon=True).start()
    print(f"rooms platform on http://127.0.0.1:{port}/"); http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
