"""Minimal pure-python 3DS reader (Blender 5 has no built-in 3DS importer). 3ds_to_glb(src, dst, zup_to_yup=True) -> bool. Keeps per-material diffuse colours."""
import struct, pathlib, numpy as np, trimesh

def _chunks(b, i, end):
    while i + 6 <= end:
        cid, ln = struct.unpack_from("<HI", b, i)
        if ln < 6: return
        yield cid, i + 6, min(i + ln, end); i += ln

def parse(path):
    b = pathlib.Path(path).read_bytes(); mats = {}; objs = []
    def color(i, end):
        for cid, s, e in _chunks(b, i, end):
            if cid == 0x0011: return [x / 255 for x in b[s:s + 3]]
            if cid == 0x0010: return list(struct.unpack_from("<3f", b, s))
    def material(i, end):
        name = None; col = [0.7, 0.7, 0.7]
        for cid, s, e in _chunks(b, i, end):
            if cid == 0xA000: name = b[s:e].split(b"\0")[0].decode("latin1")
            elif cid == 0xA020: col = color(s, e) or col
        mats[name] = col
    def trimesh_chunk(i, end):
        v = f = m = None; faces_mat = []
        for cid, s, e in _chunks(b, i, end):
            if cid == 0x4110:
                n = struct.unpack_from("<H", b, s)[0]; v = np.frombuffer(b, "<f4", n * 3, s + 2).reshape(n, 3)
            elif cid == 0x4160:
                m = np.frombuffer(b, "<f4", 12, s).reshape(4, 3)
            elif cid == 0x4120:
                n = struct.unpack_from("<H", b, s)[0]; f = np.frombuffer(b, "<u2", n * 4, s + 2).reshape(n, 4)[:, :3]
                for c2, s2, e2 in _chunks(b, s + 2 + n * 8, e):
                    if c2 == 0x4130:
                        nm = b[s2:e2].split(b"\0")[0]; k = len(nm) + 1; cnt = struct.unpack_from("<H", b, s2 + k)[0]
                        faces_mat.append((nm.decode("latin1"), np.frombuffer(b, "<u2", cnt, s2 + k + 2)))
        if v is not None and f is not None: objs.append((v, f, m, faces_mat))
    def editor(i, end):
        for cid, s, e in _chunks(b, i, end):
            if cid == 0xAFFF: material(s, e)
            elif cid == 0x4000:
                k = b.index(b"\0", s) + 1
                for c2, s2, e2 in _chunks(b, k, e):
                    if c2 == 0x4100: trimesh_chunk(s2, e2)
    for cid, s, e in _chunks(b, 0, len(b)):
        if cid == 0x4D4D:
            for c2, s2, e2 in _chunks(b, s, e):
                if c2 == 0x3D3D: editor(s2, e2)
    return mats, objs

def to_scene(path, zup_to_yup=True):
    mats, objs = parse(path); sc = trimesh.Scene(); R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
    for oi, (v, f, m, fm) in enumerate(objs):
        v = v.astype(float)
        if len(f) == 0 or len(v) == 0: continue
        if zup_to_yup: v = v @ R.T
        assigned = np.zeros(len(f), bool); groups = []
        for nm, idx in fm:
            idx = idx[idx < len(f)]; groups.append((nm, idx)); assigned[idx] = True
        rest = np.where(~assigned)[0]
        if len(rest): groups.append((None, rest))
        for gi, (nm, idx) in enumerate(groups):
            if not len(idx): continue
            mesh = trimesh.Trimesh(v, f[idx], process=False)
            c = mats.get(nm, [0.7, 0.7, 0.7])
            mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=[c[0], c[1], c[2], 1.0], metallicFactor=0.0, roughnessFactor=0.7, doubleSided=True))
            sc.add_geometry(mesh, node_name=f"o{oi}_{gi}")
    return sc

def threeds_to_glb(src, dst, zup_to_yup=True):
    sc = to_scene(src, zup_to_yup)
    if len(sc.geometry) == 0: return False
    sc.export(str(dst)); return pathlib.Path(dst).exists()
