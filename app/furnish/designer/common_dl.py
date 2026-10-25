"""Streaming download helper for group D (uses common's rate limiter). Skips > maxmb. Returns path or None."""
import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import *
import common
def download(url, dest, maxmb=300, session=None):
    dest = pathlib.Path(dest)
    if dest.exists() and dest.stat().st_size > 0: return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    S = session or common._S
    try:
        common._wait(url.split("/")[2])
        r = S.get(url, stream=True, timeout=60, allow_redirects=True)
        if r.status_code in (403, 429): common.log_wall(url.split("/")[2], url, r.status_code); return None
        if r.status_code != 200: return None
        n = int(r.headers.get("content-length") or 0)
        if n > maxmb * 1e6: print("skip big", url, n, flush=True); r.close(); return "BIG"
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for ch in r.iter_content(1 << 20): f.write(ch)
        tmp.replace(dest); return dest
    except Exception as e:
        print("dl fail", url, e, flush=True); return None

def _bc(src, dst):
    p = subprocess.run([BLENDER, "-b", "-noaudio", "-P", str(H / "blender_convert.py"), "--", str(src), str(dst)], capture_output=True, timeout=900)
    if p.returncode != 0: print("blender rc", p.returncode, p.stdout[-400:].decode("utf8", "replace"), flush=True)
    return p.returncode == 0 and pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 1000
common.blender_convert = _bc   # common.blender_convert decodes stdout as utf8 and crashes on Blender's non-utf8 bytes

import struct
def convert_3ds_to_obj(src, dst, zup_to_yup=True):
    """Minimal 3DS parser (Blender 5.x has no 3DS importer). Writes OBJ+MTL (diffuse colours per material). Returns dst or None."""
    data = pathlib.Path(src).read_bytes(); mats = {}; objs = []
    def walk(off, end, ctx):
        while off + 6 <= end:
            cid, ln = struct.unpack_from("<HI", data, off)
            if ln < 6: break
            body = off + 6; stop = min(off + ln, end)
            if cid in (0x4D4D, 0x3D3D): walk(body, stop, ctx)
            elif cid == 0xAFFF: m = {"name": None, "rgb": (0.7, 0.7, 0.7)}; walk(body, stop, m); mats[m["name"]] = m["rgb"]
            elif cid == 0xA000: ctx["name"] = data[body:stop].split(b"\0")[0].decode("latin1")
            elif cid == 0xA020 and "name" in ctx: walk(body, stop, {"_c": ctx, "k": "d"})   # diffuse
            elif cid in (0x0011, 0x0010) and "_c" in ctx:
                if cid == 0x0011: ctx["_c"]["rgb"] = tuple(b / 255 for b in data[body:body + 3])
                else: ctx["_c"]["rgb"] = struct.unpack_from("<3f", data, body)
            elif cid == 0x4000:
                nm = data[body:stop].split(b"\0")[0]; o = {"v": [], "f": [], "fm": {}, "mat": None}; objs.append(o); walk(body + len(nm) + 1, stop, o)
            elif cid == 0x4100: walk(body, stop, ctx)
            elif cid == 0x4110:
                n = struct.unpack_from("<H", data, body)[0]; ctx["v"] = [struct.unpack_from("<3f", data, body + 2 + 12 * i) for i in range(n)]
            elif cid == 0x4120:
                n = struct.unpack_from("<H", data, body)[0]; ctx["f"] = [struct.unpack_from("<3H", data, body + 2 + 8 * i) for i in range(n)]
                walk(body + 2 + 8 * n, stop, ctx)
            elif cid == 0x4130:
                nm = data[body:stop].split(b"\0")[0]; p = body + len(nm) + 1; n = struct.unpack_from("<H", data, p)[0]
                for i in range(n): ctx["fm"][struct.unpack_from("<H", data, p + 2 + 2 * i)[0]] = nm.decode("latin1")
            off += ln
    walk(0, len(data), {})
    # materials parsing needs ctx for colour chunks: re-parse materials simply
    lines = []; base = 1; used = set()
    for oi, o in enumerate(objs):
        if not o["v"] or not o["f"]: continue
        for x, y, z in o["v"]:
            lines.append("v %f %f %f" % ((x, z, -y) if zup_to_yup else (x, y, z)))
        cur = None
        faces = sorted(range(len(o["f"])), key=lambda i: o["fm"].get(i, ""))
        for i in faces:
            m = o["fm"].get(i, "default")
            if m != cur: lines.append("usemtl " + (re.sub(r"\W", "_", m))); cur = m; used.add(m)
            a, b, c = o["f"][i]; lines.append("f %d %d %d" % (a + base, b + base, c + base))
        base += len(o["v"])
    if not lines: return None
    dst = pathlib.Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    mt = []
    for m in used | {"default"}:
        r, g, b = mats.get(m, (0.7, 0.7, 0.7)); mt += ["newmtl " + re.sub(r"\W", "_", m), "Kd %f %f %f" % (r, g, b), "Ka 0 0 0", "Ks 0.1 0.1 0.1", "Ns 20", ""]
    dst.with_suffix(".mtl").write_text("\n".join(mt)); dst.write_text("mtllib " + dst.with_suffix(".mtl").name + "\n" + "\n".join(lines) + "\n"); return dst
