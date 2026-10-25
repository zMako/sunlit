"""Out-of-the-window spike server: serves app/ as static files and proxies Google Photorealistic 3D Tiles with the API key kept
server-side. Every root tileset request (one per viewing session, ~3 h of tile requests on its session token) is checked and
charged through spend.py before it is made; child tiles are free and only counted. Runs on :8771 so the shared :8765
platform keeps running untouched; the same route can move into proxy.py once the view is approved.
    ../../feasibility/.venv/bin/python plan3d/outside/tiles_server.py [port]      (from app/)"""
import http.server, socketserver, urllib.request, urllib.parse, urllib.error, pathlib, re, sys

APP = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP)); import spend   # noqa: E402

def _key():
    for line in (APP.parent / ".env").read_text().splitlines():
        if line.startswith("GOOGLE_MAPS_API_KEY="): return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("GOOGLE_MAPS_API_KEY missing from .env")
KEY = _key()
SESSION = [None]
ALLOWED_ORIGINS = {"http://127.0.0.1:8765", "http://localhost:8765", "http://127.0.0.1:8771", "http://localhost:8771"}

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(APP), **k)
    def log_message(self, fmt, *a): pass
    def end_headers(self):
        if not self.path.startswith("/v1/3dtiles/"): self.send_header("Cache-Control", "no-cache")   # pages and code under edit: always fresh
        super().end_headers()
    def do_GET(self):
        p = urllib.parse.urlsplit(self.path)
        if p.path.startswith("/v1/3dtiles/"): return self.tiles(p)
        return super().do_GET()
    def tiles(self, p):
        root = p.path == "/v1/3dtiles/root.json"
        try: spend.google_call("google_root_tile" if root else "google_tile", note="outside: root tileset (session)" if root else "")
        except spend.SpendCapExceeded as e: return self.send_error(402, str(e))
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k != "key"]
        if not root and not any(k == "session" for k, _ in q) and SESSION[0]: q.append(("session", SESSION[0]))   # nested tilesets list children without it
        q.append(("key", KEY))
        req = urllib.request.Request("https://tile.googleapis.com" + p.path + "?" + urllib.parse.urlencode(q),
                                     headers={"Accept-Encoding": "identity", "User-Agent": "MoveIn-CalHacks-demo/1.0"})
        try:
            r = urllib.request.urlopen(req, timeout=40); body, code, hdr = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e: body, code, hdr = e.read(), e.code, e.headers
        except Exception as e: return self.send_error(502, f"tiles upstream: {type(e).__name__}")
        if root and code == 200:
            m = re.search(rb'session=([A-Za-z0-9_\-]+)', body)
            if m: SESSION[0] = m.group(1).decode()   # the session token every later tile request must carry (~3 h)
        self.send_response(code)
        self.send_header("Content-Type", hdr.get("Content-Type", "application/octet-stream")); self.send_header("Content-Length", str(len(body)))
        if hdr.get("Cache-Control"): self.send_header("Cache-Control", hdr["Cache-Control"])   # Google's own caching rules, nothing longer
        o = self.headers.get("Origin", "")
        if o in ALLOWED_ORIGINS: self.send_header("Access-Control-Allow-Origin", o); self.send_header("Vary", "Origin")   # the platform on :8765 loads tiles from here
        self.end_headers(); self.wfile.write(body)

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True; request_queue_size = 256   # tile bursts: the default backlog of 5 resets connections

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8771
    print(f"outside spike on http://127.0.0.1:{port}/  (Google tiles proxied, key server-side, spend-capped)", flush=True)
    Server(("127.0.0.1", port), H).serve_forever()
