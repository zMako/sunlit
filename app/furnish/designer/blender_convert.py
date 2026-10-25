"""blender -b -P blender_convert.py -- <src> <dst.glb> : import FBX/3DS/DAE/OBJ/BLEND/STL and export GLB (Y-up, materials kept)."""
import bpy, sys, os
src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
e = os.path.splitext(src)[1].lower()
if e == ".fbx": bpy.ops.import_scene.fbx(filepath=src)
elif e == ".3ds":
    try: bpy.ops.import_scene.autodesk_3ds(filepath=src)
    except Exception: bpy.ops.wm.obj_import(filepath=src)
elif e == ".dae": bpy.ops.wm.collada_import(filepath=src)
elif e == ".obj": bpy.ops.wm.obj_import(filepath=src)
elif e == ".stl": bpy.ops.wm.stl_import(filepath=src)
elif e == ".ply": bpy.ops.wm.ply_import(filepath=src)
elif e == ".blend": bpy.ops.wm.open_mainfile(filepath=src)
else: raise SystemExit("unsupported " + e)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_yup=True, export_apply=True)
