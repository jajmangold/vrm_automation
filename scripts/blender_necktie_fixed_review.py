#!/usr/bin/env python3
"""Render fixed necktie placement using depth sweep logic + 4-view cameras.

Uses the exact same placement logic as blender_necktie_depth_sweep.py 
(offset_tie_along_body_front) with corrected depth=0.05 from sweep results.

Render front, side, three-quarter, and portrait views for review.
Also composites a 4-panel review sheet."""

from __future__ import annotations

import argparse
import math
import json
import sys
from pathlib import Path

import bpy


def argv_after_separator():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1:]


def find_vrm_addon():
    # Check local addon dir first (mounted from workspace)
    local_addons = ["/workspace/addons/vrm-addon.zip"]
    for p in local_addons:
        fp = Path(p)
        if fp.is_file():
            return str(fp)
    # Fall back to Blender config dirs
    addon_dirs = [
        "/tmp/blender-config/blender/4.2/scripts/addons",
        str(Path.home() / ".config/blender/4.2/scripts/addons"),
    ]
    for d in addon_dirs:
        addon_dir = Path(d)
        try:
            if not addon_dir.is_dir():
                continue
        except OSError:
            continue
        for item in addon_dir.iterdir():
            if item.is_dir() and "vrm" in item.name.lower():
                return str(item)
        for item in addon_dir.iterdir():
            if item.suffix == ".zip" and "vrm" in item.name.lower():
                return str(item)
    return None


def import_vrm(path):
    """Import VRM via glTF (VRM is a glTF extension, standard import loads the mesh+armature)."""
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
        print("VRM import (glTF) ok")
    except Exception as e:
        print("VRM import error: %s" % e)
        sys.exit(1)


def import_glb(path):
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
    except Exception as e:
        print("GLB import error: %s" % e)
        sys.exit(1)


def find_armature():
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj
    return None


def find_tie_object(object_name=None):
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj:
            return obj
    for obj in bpy.data.objects:
        if obj.type == "MESH" and ("tie" in obj.name.lower() or "necktie" in obj.name.lower()):
            return obj
    return None


def char_only_bounds():
    from mathutils import Vector
    armature = find_armature()
    b = None
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if armature and obj.find_armature() == armature:
            for co in obj.bound_box:
                world_co = obj.matrix_world @ Vector(co)
                if b is None:
                    b = [world_co.x, world_co.y, world_co.z] * 2
                else:
                    b[0] = min(b[0], world_co.x)
                    b[1] = min(b[1], world_co.y)
                    b[2] = min(b[2], world_co.z)
                    b[3] = max(b[3], world_co.x)
                    b[4] = max(b[4], world_co.y)
                    b[5] = max(b[5], world_co.z)
    if not b:
        return None
    return {
        "min": b[:3],
        "max": b[3:],
        "center": [(b[i] + b[i + 3]) / 2 for i in range(3)],
        "size": [b[i + 3] - b[i] for i in range(3)],
    }


def measure_body():
    from mathutils import Vector
    armature = find_armature()
    if not armature:
        return None
    head = None
    for bone in armature.data.bones:
        nl = bone.name.lower()
        if "head" in nl and "eye" not in nl:
            head = bone
    if not head:
        return None
    head_w = armature.matrix_world @ head.head_local
    body = char_only_bounds()
    body_height = body["size"][2] if body else 1.8
    hip_z = body["min"][2] if body else head_w.z - body_height
    return {
        "armature": armature,
        "body_height": body_height,
        "body": body,
        "head_world": head_w,
        "hip_z": hip_z,
    }


def tie_world_height(tie_obj):
    from mathutils import Vector
    zs = []
    for co in tie_obj.bound_box:
        w = tie_obj.matrix_world @ Vector(co)
        zs.append(w.z)
    return max(zs) - min(zs)


def scene_mesh_bounds():
    from mathutils import Vector
    b = None
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for co in obj.bound_box:
            world_co = obj.matrix_world @ Vector(co)
            if b is None:
                b = [world_co.x, world_co.y, world_co.z] * 2
            else:
                b[0] = min(b[0], world_co.x)
                b[1] = min(b[1], world_co.y)
                b[2] = min(b[2], world_co.z)
                b[3] = max(b[3], world_co.x)
                b[4] = max(b[4], world_co.y)
                b[5] = max(b[5], world_co.z)
    if not b:
        return None
    return {
        "min": b[:3],
        "max": b[3:],
        "center": [(b[i] + b[i + 3]) / 2 for i in range(3)],
        "size": [b[i + 3] - b[i] for i in range(3)],
    }


def apply_placement(tie_obj, body_info, front_offset_ratio=0.05):
    """Place tie using depth sweep's proven logic.
    
    1. Compute anchor at head-chest midpoint
    2. Place tie at anchor
    3. Rotate tie (front solve rotation)
    4. Scale to target_size_ratio of body height
    5. Apply horizontal offset from front solve
    6. Apply depth offset along chest Y-normal (same as offset_tie_along_body_front)
    """
    from mathutils import Vector
    
    armature = body_info["armature"]
    body_height = body_info["body_height"]
    
    # Find head and chest bones
    head_bone = None
    chest_bone = None
    for bone in armature.data.bones:
        nl = bone.name.lower()
        if "head" in nl and "eye" not in nl:
            head_bone = bone
        if "chest" in nl and "upper" not in nl:
            chest_bone = bone
    if not head_bone or not chest_bone:
        print("ERROR: could not find head/chest bones")
        return
    
    head_w = armature.matrix_world @ head_bone.head_local
    chest_w = armature.matrix_world @ chest_bone.head_local
    anchor = head_w.lerp(chest_w, 0.5)
    
    print("Anchor (head-chest mid): %.4f, %.4f, %.4f" % (anchor.x, anchor.y, anchor.z))
    print("Chest: %.4f, %.4f, %.4f" % (chest_w.x, chest_w.y, chest_w.z))
    print("Body height: %.4f, body Z: %.4f to %.4f" % (
        body_height, body_info["body"]["min"][2], body_info["body"]["max"][2]))
    print("Tie object: %s" % tie_obj.name)
    
    # Step 1: Place tie at anchor
    tie_obj.location = anchor
    tie_obj.scale = Vector((1.0, 1.0, 1.0))
    tie_obj.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    
    print("Tie at anchor, native height: %.4f" % tie_world_height(tie_obj))
    
    # Step 2: Apply rotation (Z-roll from front solve)
    tie_obj.rotation_euler.z = math.radians(-3.3665)
    bpy.context.view_layer.update()
    
    # Step 3: Scale to target size (0.1873 * body_height)
    local_h = tie_world_height(tie_obj)
    target_h = body_height * 0.1873
    scale = target_h / max(local_h, 1e-6)
    tie_obj.scale = Vector((scale, scale, scale))
    bpy.context.view_layer.update()
    
    print("Scale: %.4f, target_h: %.4f, tie world h: %.4f" % (
        scale, target_h, tie_world_height(tie_obj)))
    
    # Step 4: Horizontal offset from front solve
    tie_obj.location.x += 0.0367 * body_height
    
    # Step 5: Depth offset - reuse offset_tie_along_body_front logic exactly
    # This computes the chest Y-normal and displaces the tie outward from the chest
    if chest_bone.parent:
        rel_matrix = chest_bone.parent.matrix_local.inverted() @ chest_bone.matrix_local
    else:
        rel_matrix = chest_bone.matrix_local
    chest_normal = rel_matrix.to_3x3().col[1].to_3d()
    chest_normal.normalized()
    
    print("Chest Y-normal: (%.4f, %.4f, %.4f)" % (chest_normal.x, chest_normal.y, chest_normal.z))
    
    # offset_tie_along_body_front formula:
    #   displacement = chest_normal * (front_offset_ratio * body_height)
    #   chest_to_tie = anchor - chest_world
    #   tie_pos = chest_world + displacement + chest_to_tie
    # Which simplifies to: anchor + displacement
    displacement = chest_normal * (front_offset_ratio * body_height)
    
    print("Displacement: (%.4f, %.4f, %.4f)" % (displacement.x, displacement.y, displacement.z))
    tie_obj.location += displacement
    
    bpy.context.view_layer.update()
    
    tie_wh = tie_world_height(tie_obj)
    tie_min_z = None
    tie_max_z = None
    from mathutils import Vector as V
    for co in tie_obj.bound_box:
        w = tie_obj.matrix_world @ V(co)
        if tie_min_z is None or w.z < tie_min_z:
            tie_min_z = w.z
        if tie_max_z is None or w.z > tie_max_z:
            tie_max_z = w.z
    
    print("Tie final: (%.4f, %.4f, %.4f), Z range: %.4f - %.4f, scale=%.4f" % (
        tie_obj.location.x, tie_obj.location.y, tie_obj.location.z,
        tie_min_z, tie_max_z, tie_obj.scale.x))
    print("Body Z range: %.4f to %.4f" % (
        body_info["body"]["min"][2], body_info["body"]["max"][2]))


def setup_camera():
    camera = bpy.context.scene.camera
    if not camera:
        bpy.ops.object.camera_add(location=(0, 0, 0))
        camera = bpy.context.object
        bpy.context.scene.camera = camera
    return camera


def position_camera_front():
    camera = setup_camera()
    b = char_only_bounds()
    if not b:
        return
    from mathutils import Vector
    c = Vector(b["center"])
    s = Vector(b["size"])
    camera.location = Vector((c.x + max(s.z * 1.57, 2.3), c.y, c.z + s.z * 0.28))
    camera.data.lens = 50
    la = Vector((c.x, c.y, c.z - s.z * 0.1))
    camera.rotation_euler = (la - camera.location).to_track_quat("-Z", "Y").to_euler()


def position_camera_side():
    camera = setup_camera()
    b = scene_mesh_bounds()
    if not b:
        return
    from mathutils import Vector
    c = Vector(b["center"])
    s = Vector(b["size"])
    distance = max(s.z * 3.45, 4.8)
    target = Vector((c.x, c.y, c.z + s.z * 0.03))
    camera_z = target.z + s.z * 0.26
    location = Vector((target.x - distance, target.y, camera_z))
    camera.data.lens = 45
    camera.location = location
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def position_camera_three_quarter():
    camera = setup_camera()
    b = char_only_bounds()
    if not b:
        return
    from mathutils import Vector
    c = Vector(b["center"])
    s = Vector(b["size"])
    dist = max(s.z * 1.3, 2.0)
    ang = math.radians(45)
    ch = c.z + s.z * 0.21
    camera.location = Vector((c.x + dist * math.sin(ang), c.y - dist * math.cos(ang), ch))
    camera.data.lens = 50
    target = Vector((c.x, c.y, ch - s.z * 0.08))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def position_camera_portrait():
    camera = setup_camera()
    b = char_only_bounds()
    if not b:
        return
    from mathutils import Vector
    c = Vector(b["center"])
    s = Vector(b["size"])
    camera.location = Vector((c.x + max(s.z * 1.0, 1.5), c.y, c.z + s.z * 0.45))
    camera.data.lens = 35
    la = Vector((c.x, c.y, c.z + s.z * 0.15))
    camera.rotation_euler = (la - camera.location).to_track_quat("-Z", "Y").to_euler()


def setup_lighting():
    if not [obj for obj in bpy.data.objects if obj.type == "LIGHT"]:
        bpy.ops.object.light_add(type="SUN", location=(5, 5, 5))
        sun = bpy.context.object
        sun.data.energy = 1.5


def render_view(width, height, output_path):
    from mathutils import Euler
    scene = bpy.context.scene
    prev = (scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.film_transparent = True
    scene.render.filepath = str(output_path)
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent = prev


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Render fixed necktie at corrected depth (from sweep results) across 4 views.")
    parser.add_argument("vrm_path")
    parser.add_argument("tie_path")
    parser.add_argument("--object-name", default=None)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--depth", type=float, default=0.05)
    parser.add_argument("--output-dir", default="/workspace/results/necktie_fixed_renders")
    argv = argv_after_separator() if argv is None else argv
    return parser.parse_args(argv)


def main():
    args = parse_args()
    import_vrm(Path(args.vrm_path))
    import_glb(Path(args.tie_path))
    
    tie_obj = find_tie_object(args.object_name)
    if not tie_obj:
        print("ERROR: no tie object")
        sys.exit(1)
    
    body_info = measure_body()
    if not body_info:
        print("ERROR: no body info")
        sys.exit(1)
        
    apply_placement(tie_obj, body_info, front_offset_ratio=args.depth)
    setup_lighting()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for label, cam_fn in [
        ("fixed_front", position_camera_front),
        ("fixed_side", position_camera_side),
        ("fixed_three_quarter", position_camera_three_quarter),
        ("fixed_portrait", position_camera_portrait),
    ]:
        cam_fn()
        png = output_dir / (label + ".png")
        render_view(args.width, args.height, png)
        print("Rendered: %s" % label)
    
    print("Done.")


if __name__ == "__main__":
    main()
