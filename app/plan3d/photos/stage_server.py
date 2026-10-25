"""Photo staging worker for the apartment page: the browser sends a listing photo, the same photo with our furniture drawn in
from the photo's camera, and the furniture mask; Stable Diffusion 1.5 inpainting restyles ONLY the masked furniture and its
shadows to the photo's light and texture (strength 0.3: shapes and positions stay ours), and everything outside the mask is
copied back from the photo pixel for pixel, so a slider between photo and result stays exact.
One job at a time (MPS), newest request per photo wins, results cached as photos/staged/<key>.jpg (scraped-photo content:
gitignored). Local, no API cost. Runs on :8772 beside the shared :8765 platform.
    ../../../feasibility/.venv/bin/python plan3d/photos/stage_server.py [port]        (from app/)
POST /stage  {key, photo, composite, mask (data URLs), prompt}  -> {status}
GET  /status/<key> -> {status: queued|running|done|error, seconds?}     GET /staged/<key>.jpg"""
import http.server, socketserver, json, base64, io, re, threading, time, pathlib, sys, collections

HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "staged"; OUT.mkdir(exist_ok=True)
STRENGTH, STEPS, GUIDANCE, SEED, SD_W = 0.3, 30, 6.5, 7, 768
NEG = "cartoon, 3d render, cgi, plastic, flat shading, blurry, distorted, deformed, extra furniture, people, text, watermark, low quality"
ORIGINS = {"http://127.0.0.1:8765", "http://localhost:8765"}
KEY = re.compile(r"^[A-Za-z0-9_\-]{6,120}$")

jobs = {}                       # key -> {"status", "t", "seconds", "error"}
queue = collections.OrderedDict()   # key -> payload (newest per photo group only)
lock = threading.Condition()
pipe = None

def load():
    global pipe
    import torch
    from diffusers import StableDiffusionInpaintPipeline
    t0 = time.time()
    pipe = StableDiffusionInpaintPipeline.from_pretrained("stable-diffusion-v1-5/stable-diffusion-inpainting", torch_dtype=torch.float16, safety_checker=None).to("mps")
    pipe.set_progress_bar_config(disable=True)
    print(f"[stage] model ready in {time.time() - t0:.0f}s", flush=True)

def img(data_url, mode):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert(mode)

def run(key, p):
    import torch
    from PIL import Image, ImageFilter
    photo, comp, mask = img(p["photo"], "RGB"), img(p["composite"], "RGB"), img(p["mask"], "L")
    if comp.size != photo.size: comp = comp.resize(photo.size, Image.LANCZOS)
    mask = mask.resize(photo.size, Image.NEAREST).point(lambda v: 255 if v > 8 else 0).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MaxFilter(9))
    aspect = photo.width / photo.height; W = SD_W; H = max(384, min(1024, round(W / aspect / 8) * 8))
    g = torch.Generator("mps").manual_seed(SEED)
    out = pipe(prompt=p.get("prompt") or "professional real estate photograph of a furnished room, natural light, photorealistic", negative_prompt=NEG,
               image=comp.resize((W, H), Image.LANCZOS), mask_image=mask.resize((W, H), Image.NEAREST), strength=STRENGTH,
               num_inference_steps=STEPS, guidance_scale=GUIDANCE, width=W, height=H, generator=g).images[0]
    final = Image.composite(out.resize(photo.size, Image.LANCZOS), photo, mask.filter(ImageFilter.GaussianBlur(6)))   # outside the mask: the photo itself
    tmp = OUT / f"{key}.tmp.jpg"; final.save(tmp, quality=90); tmp.replace(OUT / f"{key}.jpg")

def worker():
    load()
    while True:
        with lock:
            while not queue: lock.wait()
            key, p = queue.popitem(last=False); jobs[key]["status"] = "running"; t0 = time.time()
        try: run(key, p); st = {"status": "done", "seconds": round(time.time() - t0, 1)}
        except Exception as e: st = {"status": "error", "error": f"{type(e).__name__}: {str(e)[:160]}"}; print("[stage] error", key, st["error"], flush=True)
        with lock: jobs[key].update(st)
        print(f"[stage] {key}: {st}", flush=True)

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def cors(self):
        o = self.headers.get("Origin", "")
        if o in ORIGINS: self.send_header("Access-Control-Allow-Origin", o); self.send_header("Vary", "Origin")
    def reply(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.cors(); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.send_header("Access-Control-Allow-Methods", "GET, POST"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.end_headers()
    def do_GET(self):
        m = re.match(r"^/staged/([A-Za-z0-9_\-]+)\.jpg$", self.path.split("?")[0])
        if m:
            f = OUT / f"{m.group(1)}.jpg"
            return self.reply(200, f.read_bytes(), "image/jpeg") if f.exists() else self.reply(404, {"status": "missing"})
        m = re.match(r"^/status/([A-Za-z0-9_\-]+)$", self.path.split("?")[0])
        if m:
            k = m.group(1)
            if (OUT / f"{k}.jpg").exists(): return self.reply(200, {"status": "done"})
            with lock: return self.reply(200, jobs.get(k, {"status": "missing"}))
        if self.path.startswith("/health"): return self.reply(200, {"ok": True, "model": pipe is not None, "queued": len(queue)})
        self.reply(404, {"error": "not found"})
    def do_POST(self):
        if self.path != "/stage": return self.reply(404, {"error": "not found"})
        try: p = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except Exception: return self.reply(400, {"error": "bad json"})
        k = str(p.get("key", ""))
        if not KEY.match(k) or not all(isinstance(p.get(f), str) and p[f].startswith("data:image/") for f in ("photo", "composite", "mask")): return self.reply(400, {"error": "bad request"})
        if (OUT / f"{k}.jpg").exists(): return self.reply(200, {"status": "done"})
        group = k.rsplit("_", 1)[0]   # unit_photo: a newer furniture state replaces the queued older one
        with lock:
            for old in [q for q in queue if q.rsplit("_", 1)[0] == group and q != k]: queue.pop(old); jobs[old] = {"status": "replaced"}
            if jobs.get(k, {}).get("status") not in ("queued", "running"): queue[k] = p; jobs[k] = {"status": "queued", "t": time.time()}; lock.notify()
            return self.reply(200, jobs[k])

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True; request_queue_size = 64

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8772
    threading.Thread(target=worker, daemon=True).start()
    print(f"[stage] photo staging worker on http://127.0.0.1:{port}/ (SD 1.5 inpainting, strength {STRENGTH})", flush=True)
    Server(("127.0.0.1", port), H).serve_forever()
