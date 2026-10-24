"""Fetch a small sample of CubiCasa5K (Kalervo et al. 2019, Zenodo record 2613548, CC BY-NC 4.0) without downloading the
5.4 GB archive: the zip is read over HTTP range requests (central directory + the members we need). Per sample we keep
F1_scaled.png (the image the SVG coordinates refer to) and model.svg (ground truth). Usage: cubicasa_fetch.py [n=100] [seed=0]
Samples are drawn from the official test split (test.txt), seeded, so the sample is reproducible."""
import sys, io, zipfile, pathlib, random, urllib.request, time
URL = "https://zenodo.org/api/records/2613548/files/cubicasa5k.zip/content"
OUT = pathlib.Path(__file__).resolve().parent / "data" / "cubicasa5k"

class HttpRange(io.RawIOBase):
    def __init__(self, url, size=None):
        self.url, self.pos = url, 0
        if size is None:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=60)
            size = int(r.headers["Content-Range"].split("/")[-1])
        self.size = size; self.cache = {}
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off); return self.pos
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        if n == 0 or self.pos >= self.size: return b""
        end = min(self.size, self.pos + n) - 1
        for attempt in range(5):
            try:
                r = urllib.request.urlopen(urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"}), timeout=120); data = r.read(); break
            except Exception:
                if attempt == 4: raise
                time.sleep(2 + 3 * attempt)
        self.pos += len(data); return data
    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100; seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    OUT.mkdir(parents=True, exist_ok=True)
    f = io.BufferedReader(HttpRange(URL), buffer_size=1 << 20); z = zipfile.ZipFile(f)
    names = z.namelist(); print(f"[cubicasa] {len(names)} members", flush=True)
    test_name = next(x for x in names if x.endswith("test.txt"))
    root = test_name[: -len("test.txt")]
    folders = [l.strip() for l in z.read(test_name).decode().splitlines() if l.strip()]
    (OUT / "test.txt").write_text("\n".join(folders))
    pick = sorted(random.Random(seed).sample(folders, min(n, len(folders))))
    (OUT / "sample.txt").write_text("\n".join(pick))
    have = set(names); t0 = time.time()
    for i, fo in enumerate(pick):
        sid = fo.strip("/").replace("/", "_"); d = OUT / sid; d.mkdir(exist_ok=True)
        for fn in ("F1_scaled.png", "model.svg"):
            member = root + fo.strip("/") + "/" + fn
            if member not in have: member = (root + fo.lstrip("/")).rstrip("/") + "/" + fn
            if (d / fn).exists() or member not in have: continue
            (d / fn).write_bytes(z.read(member))
        print(f"[cubicasa] {i + 1}/{len(pick)} {sid} {time.time() - t0:.0f}s", flush=True)

if __name__ == "__main__": main()
