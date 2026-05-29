from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def import_vrm(path: Path) -> list[str]:
    errors = []
    try:
        if hasattr(bpy.ops.import_scene, "vrm"):
            bpy.ops.import_scene.vrm(filepath=str(path))
        else:
            errors.append("VRM addon not registered")
    except Exception as exc:
        errors.append(f"import failed: {exc}")
    return errors


def import_glb(path: Path) -> list[str]:
    errors = []
    try:
        bpy.ops.import_scene.gltf(filepath=str(path))
    except Exception as exc:
        errors.append(f"import failed: {exc}")
    return errors


def find_armature():
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj
    return None


def find_tie_object(object_name: str | None):
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj:
            return obj
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            name_lower = obj.name.lower()
            if "tie" in name_lower or "necktie" in name_lower:
                return obj
    return None


def scene_mesh_bounds():
    bounds = None
    from mathutils import Vector

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for co in obj.bound_box:
            world_co = obj.matrix_world @ Vector(co)
            if bounds is None:
                bounds = [world_co.x, world_co.y, world_co.z] * 2
            else:
                bounds[0] = min(bounds[0], world_co.x)
                bounds[1] = min(bounds[1], world_co.y)
                bounds[2] = min(bounds[2], world_co.z)
                bounds[3] = max(bounds[3], world_co.x)
                bounds[4] = max(bounds[4], world_co.y)
                bounds[5] = max(bounds[5], world_co.z)
    if bounds is None:
        return None
    return {
        "min": bounds[:3],
        "max": bounds[3:],
        "center": [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)],
        "size": [bounds[i + 3] - bounds[i] for i in range(3)],
    }


def position_side_camera():
    from mathutils import Vector

    camera = bpy.context.scene.camera
    if not camera:
        bpy.ops.object.camera_add(location=(0, 0, 0))
        camera = bpy.context.object
        bpy.context.scene.camera = camera

    bounds = scene_mesh_bounds()
    if not bounds:
        return

    center = Vector(bounds["center"])
    size = Vector(bounds["size"])
    distance = max(size.z * 3.45, 4.8)
    target = Vector((center.x, center.y, center.z + size.z * 0.03))
    camera_z = target.z + size.z * 0.26
    location = Vector((target.x - distance, target.y, camera_z))
    camera.data.lens = 45
    camera.location = location
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def hide_all_except(tie_obj):
    hidden = {}
    for obj in bpy.context.scene.objects:
        hidden[obj.name] = obj.hide_render
        obj.hide_render = obj.name != tie_obj.name
    return hidden


def hide_tie_only(tie_obj):
    hidden = {}
    for obj in bpy.context.scene.objects:
        hidden[obj.name] = obj.hide_render
        obj.hide_render = obj.name == tie_obj.name
    return hidden


def restore_hidden(hidden):
    for obj in bpy.context.scene.objects:
        if obj.name in hidden:
            obj.hide_render = hidden[obj.name]


def render_side_combined(width: int, height: int, output_path: Path) -> dict[str, Any]:
    """Render everything visible (body + tie) from the side camera for visual review. Returns stats."""
    scene = bpy.context.scene
    previous_resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent)
    
    visible_meshes = []
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and not obj.hide_render:
            visible_meshes.append(obj.name)

    try:
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.film_transparent = True
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        return {"visible_meshes": visible_meshes, "output": str(output_path)}
    finally:
        scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent = previous_resolution


def render_object_mask(tie_obj, width: int, height: int) -> list[list[bool]]:
    from mathutils import Vector

    scene = bpy.context.scene
    previous_resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent)
    hidden = hide_all_except(tie_obj)
    active = bpy.context.view_layer.objects.active
    selected = [obj for obj in bpy.context.selected_objects]

    try:
        bpy.ops.object.select_all(action="DESELECT")
        tie_obj.select_set(True)
        bpy.context.view_layer.objects.active = tie_obj
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.film_transparent = True
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            output_path = Path(handle.name)
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        rows = load_mask_png_with_blender(output_path, threshold=16)
        output_path.unlink(missing_ok=True)
        return rows
    finally:
        restore_hidden(hidden)
        scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent = previous_resolution
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active


def render_body_mask(width: int, height: int) -> list[list[bool]]:
    """Render all scene objects except the tie mask."""
    scene = bpy.context.scene
    previous_resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent)
    active = bpy.context.view_layer.objects.active
    selected = [obj for obj in bpy.context.selected_objects]

    tie_name = None
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            name_lower = obj.name.lower()
            if "tie" in name_lower or "necktie" in name_lower:
                tie_name = obj.name
                break

    hidden = hide_tie_only(None) if not tie_name else hide_tie_only(bpy.data.objects.get(tie_name))
    try:
        bpy.ops.object.select_all(action="DESELECT")
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.film_transparent = True
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            output_path = Path(handle.name)
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        rows = load_mask_png_with_blender(output_path, threshold=16)
        output_path.unlink(missing_ok=True)
        return rows
    finally:
        restore_hidden(hidden)
        scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent = previous_resolution
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active


def load_mask_png_with_blender(path: Path, *, threshold: int = 16) -> list[list[bool]]:
    image = bpy.data.images.load(str(path))
    try:
        width, height = image.size
        pixels = list(image.pixels)
        alpha_values = pixels[3::4]
        use_alpha = bool(alpha_values) and min(alpha_values) < 0.99
        rows: list[list[bool]] = []
        for y in range(height):
            row = []
            for x in range(width):
                index = ((height - 1 - y) * width + x) * 4
                alpha = pixels[index + 3]
                value = alpha if use_alpha else max(pixels[index], pixels[index + 1], pixels[index + 2])
                row.append(value * 255.0 > threshold)
            rows.append(row)
        return rows
    finally:
        bpy.data.images.remove(image)


def mask_metrics(mask: list[list[bool]]) -> dict[str, Any]:
    if not mask or not mask[0]:
        return {"foreground_pixels": 0, "center_x": None, "center_y": None, "bbox": None}
    height = len(mask)
    width = len(mask[0])
    xs = []
    ys = []
    for y in range(height):
        for x in range(width):
            if mask[y][x]:
                xs.append(x)
                ys.append(y)
    if not xs:
        return {"foreground_pixels": 0, "center_x": None, "center_y": None, "bbox": None}
    return {
        "foreground_pixels": len(xs),
        "center_x": sum(xs) / len(xs),
        "center_y": sum(ys) / len(ys),
        "center_x_ratio": (sum(xs) / len(xs)) / width,
        "center_y_ratio": (sum(ys) / len(ys)) / height,
        "bbox_x_min": min(xs),
        "bbox_x_max": max(xs),
        "bbox_y_min": min(ys),
        "bbox_y_max": max(ys),
    }


def body_surface_x_at_row(body_mask: list[list[bool]], row_y: int, side: str = "left") -> int | None:
    """Return the leftmost or rightmost foreground pixel X at a given Y row in the body mask."""
    if not body_mask or row_y < 0 or row_y >= len(body_mask):
        return None
    row = body_mask[row_y]
    width = len(row)
    if side == "left":
        for x in range(width):
            if row[x]:
                return x
    else:
        for x in range(width - 1, -1, -1):
            if row[x]:
                return x
    return None


def body_surface_x_avg(body_mask: list[list[bool]], y_min: int, y_max: int, side: str = "left") -> float | None:
    """Average body surface X across a vertical span at the tie's Y range."""
    xs = []
    for y in range(max(0, y_min), min(len(body_mask), y_max + 1)):
        vx = body_surface_x_at_row(body_mask, y, side)
        if vx is not None:
            xs.append(vx)
    if not xs:
        return None
    return sum(xs) / len(xs)


def get_tie_anchor_point(tie_obj, armature):
    from mathutils import Vector

    if not armature:
        return tie_obj.matrix_world.to_translation()
    head_bone = None
    chest_bone = None
    for bone in armature.data.bones:
        name = bone.name.lower()
        if "head" in name:
            head_bone = bone
        if "chest" in name:
            chest_bone = bone
    if head_bone and chest_bone:
        head_world = armature.matrix_world @ head_bone.head_local
        chest_world = armature.matrix_world @ chest_bone.head_local
        return head_world.lerp(chest_world, 0.5)
    return tie_obj.matrix_world.to_translation()


def offset_tie_along_body_front(tie_obj, anchor, front_offset_ratio: float, body_size: float) -> None:
    from mathutils import Vector

    armature = find_armature()
    if not armature:
        current_z = tie_obj.location.z
        tie_obj.location.z = current_z + (front_offset_ratio * body_size)
        return

    chest_bone = None
    for bone in armature.data.bones:
        if "chest" in bone.name.lower():
            chest_bone = bone
            break
    if not chest_bone:
        current_z = tie_obj.location.z
        tie_obj.location.z = current_z + (front_offset_ratio * body_size)
        return

    chest_world = armature.matrix_world @ chest_bone.head_local
    if chest_bone.parent:
        rel_matrix = chest_bone.parent.matrix_local.inverted() @ chest_bone.matrix_local
    else:
        rel_matrix = chest_bone.matrix_local
    chest_normal = rel_matrix.to_3x3().col[1].to_3d()
    chest_normal.normalized()

    displacement = chest_normal * (front_offset_ratio * body_size)
    chest_to_tie = anchor - chest_world
    tie_pos = chest_world + displacement + chest_to_tie
    tie_obj.location = tie_pos


def depth_sweep(
    *,
    tie_obj,
    armature,
    body_size: float,
    anchor,
    depth_values: list[float],
    width: int,
    height: int,
    initial_tie_location,
    output_dir: Path | None = None,
) -> list[dict[str, Any]]:
    from mathutils import Vector

    body_mask = render_body_mask(width, height)

    results = []
    for i, depth in enumerate(depth_values):
        offset_tie_along_body_front(tie_obj, anchor, depth, body_size)
        bpy.context.view_layer.update()

        if output_dir is not None:
            png = output_dir / ("side_%02d_depth_%.4f.png" % (i, depth))
            render_side_combined(width, height, png)

        mask = render_object_mask(tie_obj, width, height)
        metrics = mask_metrics(mask)
        result = {
            "index": i,
            "depth": round(depth, 4),
            "mask_pixels": metrics["foreground_pixels"],
            "mask_center_x": metrics.get("center_x"),
            "mask_center_y": metrics.get("center_y"),
            "mask_center_x_ratio": metrics.get("mask_center_x_ratio"),
            "mask_center_y_ratio": metrics.get("mask_center_y_ratio"),
            "bbox_x_min": metrics.get("bbox_x_min"),
            "bbox_x_max": metrics.get("bbox_x_max"),
            "bbox_y_min": metrics.get("bbox_y_min"),
            "bbox_y_max": metrics.get("bbox_y_max"),
        }

        surf_x = body_surface_x_avg(body_mask, metrics.get("bbox_y_min", 0), metrics.get("bbox_y_max", 0), side="left")
        if surf_x is not None and metrics.get("bbox_x_max") is not None:
            gap = int(metrics["bbox_x_max"]) - int(surf_x)
            result["body_surface_x_avg"] = round(surf_x, 2)
            result["tie_to_body_gap"] = gap
            result["tie_to_body_gap_abs"] = abs(gap)
        else:
            result["body_surface_x_avg"] = None
            result["tie_to_body_gap"] = None
            result["tie_to_body_gap_abs"] = None

        results.append(result)
    tie_obj.location = Vector(initial_tie_location)
    return results


def pick_best_depth(results: list[dict[str, Any]], target_center_y_ratio: float | None) -> dict[str, Any] | None:
    valid = [r for r in results if r["mask_pixels"] > 0]
    if not valid:
        return None

    with_gap = [r for r in valid if r.get("tie_to_body_gap_abs") is not None]
    if with_gap:
        best = min(with_gap, key=lambda r: r["tie_to_body_gap_abs"])
    elif target_center_y_ratio is not None:
        best = min(valid, key=lambda r: abs(r.get("mask_center_y_ratio", 0) - target_center_y_ratio))
    else:
        best = max(valid, key=lambda r: r["mask_pixels"])

    return best


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep tie depth from side camera to find optimal front_offset_ratio via Blender alpha mask rendering."
    )
    parser.add_argument("vrm_path", help="Path to the VRM model file")
    parser.add_argument("tie_path", help="Path to the necktie GLB file")
    parser.add_argument("--addon-path", help="VRM addon zip path (auto-finds if omitted)")
    parser.add_argument("--object-name", help="Name of the tie mesh object in Blender")
    parser.add_argument("--depth-min", type=float, default=0.05)
    parser.add_argument("--depth-max", type=float, default=0.45)
    parser.add_argument("--depth-steps", type=int, default=10)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--target-center-y-ratio", type=float, help="Expected vertical center ratio from front solve")
    parser.add_argument("--report-json", default="/workspace/results/necktie_depth_sweep.json")
    parser.add_argument("--review-images-dir", default=None, help="Dir to save side-view combined PNGs for visual review")
    argv = argv_after_separator() if argv is None else argv
    return parser.parse_args(argv)


def find_vrm_addon_path() -> str | None:
    addon_dirs = [
        "/tmp/blender-config/blender/4.2/scripts/addons",
        "/root/.config/blender/4.2/scripts/addons",
        str(Path.home() / ".config/blender/4.2/scripts/addons"),
    ]
    for d in addon_dirs:
        addon_dir = Path(d)
        if not addon_dir.exists():
            continue
        for item in addon_dir.iterdir():
            if item.is_dir() and "vrm" in item.name.lower():
                return str(item)
        for item in addon_dir.iterdir():
            if item.suffix == ".zip" and "vrm" in item.name.lower():
                return str(item)
    return None


def main():
    args = parse_args()

    addon_path = getattr(args, "addon_path", None)
    if not addon_path:
        addon_path = find_vrm_addon_path()

    vrm_path = Path(args.vrm_path)
    tie_path = Path(args.tie_path)

    errors = []

    if addon_path:
        print(f"Loading VRM addon from: {addon_path}")
        try:
            if addon_path.endswith(".zip"):
                bpy.ops.preferences.addon_install(overlay=False, target="default", filepath=addon_path)
            else:
                bpy.ops.preferences.addon_install(overlay=False, target="default", filepath=addon_path)
        except Exception as exc:
            print(f"Warning: addon install failed ({exc}), hoping it is already registered")

    print(f"Importing VRM: {vrm_path}")
    import_errors = import_vrm(vrm_path)
    errors.extend([f"VRM: {e}" for e in import_errors])

    print(f"Importing tie GLB: {tie_path}")
    import_errors = import_glb(tie_path)
    errors.extend([f"Tie: {e}" for e in import_errors])

    if errors:
        print(f"Errors: {errors}")
        sys.exit(1)

    tie_obj = find_tie_object(args.object_name)
    if not tie_obj:
        print("ERROR: could not find tie object after import")
        for obj in bpy.data.objects:
            print(f"  -> {obj.name} ({obj.type})")
        sys.exit(1)

    armature = find_armature()
    bounds = scene_mesh_bounds()
    if not bounds:
        print("ERROR: no mesh objects found")
        sys.exit(1)

    from mathutils import Vector

    body_size = max(bounds["size"][2], 1.0)
    anchor = get_tie_anchor_point(tie_obj, armature)
    initial_location = [
        float(tie_obj.location.x),
        float(tie_obj.location.y),
        float(tie_obj.location.z),
    ]

    print(f"Positioning side camera...")
    position_side_camera()

    depth_values = [
        args.depth_min + (args.depth_max - args.depth_min) * (i / max(args.depth_steps - 1, 1))
        for i in range(args.depth_steps)
    ]

    print(f"Starting depth sweep: {len(depth_values)} candidates from {args.depth_min} to {args.depth_max}")
    print(f"Tie object: {tie_obj.name}")
    print(f"Body Z size: {body_size:.4f}")
    print(f"Anchor: {' '.join(f'{v:.4f}' for v in anchor)}")
    print(f"Tie initial location: {initial_location}")

    output_dir = Path(args.review_images_dir) if args.review_images_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    results = depth_sweep(
        tie_obj=tie_obj,
        armature=armature,
        body_size=body_size,
        anchor=anchor,
        depth_values=depth_values,
        width=args.width,
        height=args.height,
        initial_tie_location=initial_location,
        output_dir=output_dir,
    )
    elapsed = round(time.perf_counter() - t0, 1)
    print(f"Sweep completed in {elapsed}s")

    best = pick_best_depth(results, args.target_center_y_ratio)

    report = {
        "status": "ok",
        "vrm_path": str(vrm_path),
        "tie_path": str(tie_path),
        "tie_object": tie_obj.name,
        "body_size_z": round(body_size, 4),
        "anchor": [round(float(v), 4) for v in anchor],
        "initial_tie_location": initial_location,
        "render_resolution": [args.width, args.height],
        "depth_range": [args.depth_min, args.depth_max],
        "depth_steps": args.depth_steps,
        "target_center_y_ratio": args.target_center_y_ratio,
        "elapsed_seconds": elapsed,
        "sweep_results": [
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
            for r in results
        ],
        "best_candidate": (
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in best.items()}
            if best is not None
            else None
        ),
        "recommended_front_offset_ratio": best["depth"] if best is not None else None,
    }

    report_path = Path(args.report_json)
    save_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
