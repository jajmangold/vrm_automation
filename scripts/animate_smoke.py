import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy
from mathutils import Matrix, Vector

from scripts.animation_presets import animation_preset, preset_value
from scripts.asset_classifier import classify_asset, placement_profile
from scripts.face_profile import VISEME_ALIASES, build_face_profile
from scripts.facial_presets import facial_preset_for_animation, plan_facial_animation
from scripts.fit_checks import outfit_fit_check
from scripts.render_profiles import clear_pose_render_files
from scripts.vrm_metadata import compare_vrm_summaries, summarize_vrm_file
from scripts.weighting import torso_weight_plan


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def elapsed_since(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def clear_scene() -> None:
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def try_import(path: Path) -> list[str]:
    errors = []
    suffix = path.suffix.lower()
    try:
        if suffix == ".blend":
            bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
        elif suffix == ".vrm" and hasattr(bpy.ops.import_scene, "vrm"):
            bpy.ops.import_scene.vrm(filepath=str(path))
        elif suffix in {".glb", ".gltf"}:
            bpy.ops.import_scene.gltf(filepath=str(path))
        elif suffix == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(path))
        elif suffix == ".obj" and hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        elif suffix == ".obj" and hasattr(bpy.ops.import_scene, "obj"):
            bpy.ops.import_scene.obj(filepath=str(path))
        elif suffix in {".pmx", ".pmd"} and hasattr(bpy.ops, "mmd_tools"):
            bpy.ops.mmd_tools.import_model(filepath=str(path))
        else:
            errors.append(f"no importer registered for {suffix}")
    except Exception as exc:
        errors.append(f"import failed: {exc}")
    return errors


def clear_existing_animation() -> int:
    cleared = 0
    for obj in bpy.context.scene.objects:
        if obj.animation_data:
            obj.animation_data_clear()
            cleared += 1
    for datablock_collection in (bpy.data.armatures, bpy.data.meshes, bpy.data.materials):
        for datablock in datablock_collection:
            if getattr(datablock, "animation_data", None):
                datablock.animation_data_clear()
                cleared += 1
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
        cleared += 1
    return cleared


def remove_default_scene_cubes() -> list[str]:
    removed = []
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH" or not obj.name.startswith("Cube"):
            continue
        if obj.parent or obj.vertex_groups or obj.modifiers:
            continue
        dims = tuple(round(value, 3) for value in obj.dimensions)
        if all(1.8 <= value <= 2.2 for value in dims):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return removed


def audit_secondary_bones(armature: bpy.types.Object | None) -> dict:
    if not armature:
        return {
            "hair_joint_count": 0,
            "secondary_bone_count": 0,
            "chains": {},
            "collider_like_count": 0,
        }
    bone_names = [bone.name for bone in armature.data.bones]
    hair = [name for name in bone_names if "HairJoint" in name]
    secondary = [name for name in bone_names if name.startswith("J_Sec")]
    collider_like = [name for name in bone_names if "collider" in name.lower()]

    chains = {
        "hair": hair,
        "skirt": [name for name in secondary if "skirt" in name.lower()],
        "sleeve": [name for name in secondary if "sleeve" in name.lower()],
        "bust": [name for name in secondary if "bust" in name.lower()],
        "other_secondary": [
            name
            for name in secondary
            if not any(token in name.lower() for token in ("skirt", "sleeve", "bust"))
        ],
    }
    return {
        "hair_joint_count": len(hair),
        "secondary_bone_count": len(secondary),
        "collider_like_count": len(collider_like),
        "chains": chains,
        "recommendation": "spring-bone-review"
        if hair or secondary
        else "no-secondary-bones-detected",
    }


def primary_image_node(material: bpy.types.Material):
    if not material.use_nodes or not material.node_tree:
        return None
    candidates = []
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage" or not getattr(node, "image", None):
            continue
        name = f"{node.name} {node.label} {node.image.name}".lower()
        score = 0
        for token in ("base", "main", "color", "albedo", "lit", "texture"):
            if token in name:
                score += 1
        candidates.append((score, node.name, node))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def simplify_materials_for_glb() -> dict:
    changed = []
    skipped = []
    for material in bpy.data.materials:
        image_node = primary_image_node(material)
        base_color = material.diffuse_color[:]
        if not image_node:
            skipped.append(material.name)
            continue

        image = image_node.image
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.image = image
        tex.location = (-400, 100)
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.location = (-100, 100)
        output = nodes.new(type="ShaderNodeOutputMaterial")
        output.location = (160, 100)
        material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in tex.outputs and "Alpha" in bsdf.inputs:
            material.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            material.blend_method = "BLEND"
            material.use_screen_refraction = False
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = base_color[3]
        material.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        changed.append({"material": material.name, "image": image.name})
    return {"changed": changed, "skipped": skipped}


def create_box_mesh(name: str, center: tuple[float, float, float], size: tuple[float, float, float]):
    cx, cy, cz = center
    sx, sy, sz = (v / 2 for v in size)
    verts = [
        (cx - sx, cy - sy, cz - sz),
        (cx + sx, cy - sy, cz - sz),
        (cx + sx, cy + sy, cz - sz),
        (cx - sx, cy + sy, cz - sz),
        (cx - sx, cy - sy, cz + sz),
        (cx + sx, cy - sy, cz + sz),
        (cx + sx, cy + sy, cz + sz),
        (cx - sx, cy + sy, cz + sz),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def create_principled_material(name: str, color: tuple[float, float, float, float]):
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Alpha"].default_value = color[3]
    return material


def add_weighted_part(name: str, bone_name: str, center, size, armature):
    obj = create_box_mesh(name, center, size)
    obj.parent = armature
    group = obj.vertex_groups.new(name=bone_name)
    group.add(range(len(obj.data.vertices)), 1.0, "ADD")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = armature
    return obj


def mesh_bounds(objects: list[bpy.types.Object]) -> dict | None:
    points = []
    for obj in objects:
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    if not points:
        return None
    mins = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maxs = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    size = maxs - mins
    center = (mins + maxs) * 0.5
    return {
        "min": tuple(round(value, 4) for value in mins),
        "max": tuple(round(value, 4) for value in maxs),
        "center": tuple(round(value, 4) for value in center),
        "size": tuple(round(value, 4) for value in size),
    }


def scene_mesh_bounds(exclude_prefixes: tuple[str, ...] = ()) -> dict | None:
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.name.startswith(exclude_prefixes)
    ]
    return mesh_bounds(meshes)


def local_scene_mesh_bounds(
    *,
    center: Vector,
    character_bounds: dict,
    exclude_prefixes: tuple[str, ...] = (),
    x_band_ratio: float = 0.22,
    z_band_ratio: float = 0.07,
) -> dict | None:
    char_size = Vector(character_bounds["size"])
    x_limit = max(char_size.x * x_band_ratio, 0.08)
    z_limit = max(char_size.z * z_band_ratio, 0.08)
    points = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.name.startswith(exclude_prefixes):
            continue
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            if abs(world.x - center.x) <= x_limit and abs(world.z - center.z) <= z_limit:
                points.append(world)
    if not points:
        return None
    mins = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maxs = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    size = maxs - mins
    bounds_center = (mins + maxs) * 0.5
    return {
        "min": tuple(round(value, 4) for value in mins),
        "max": tuple(round(value, 4) for value in maxs),
        "center": tuple(round(value, 4) for value in bounds_center),
        "size": tuple(round(value, 4) for value in size),
    }


def add_bound_box(name: str, bone_name: str, center, size, armature, material):
    obj = add_weighted_part(name, bone_name, center, size, armature)
    obj.data.materials.append(material)
    return obj


def add_outfit_probe(armature: bpy.types.Object | None) -> dict:
    if not armature:
        return {"enabled": False, "reason": "missing-armature", "objects": []}

    bounds = scene_mesh_bounds(exclude_prefixes=("outfit_probe_",))
    if not bounds:
        return {"enabled": False, "reason": "missing-mesh-bounds", "objects": []}

    bones = choose_pose_bones(armature)
    spine = bones["spine"]
    left_arm = bones["left_arm"]
    right_arm = bones["right_arm"]
    if not spine:
        return {"enabled": False, "reason": "missing-spine-bone", "objects": []}

    min_x, min_y, min_z = bounds["min"]
    max_x, max_y, max_z = bounds["max"]
    center_x, _center_y, _center_z = bounds["center"]
    width_x, depth_y, height_z = bounds["size"]
    front_y = min_y - max(depth_y * 0.018, 0.018)

    accent = create_principled_material("outfit_probe_teal", (0.02, 0.72, 0.78, 1.0))
    trim = create_principled_material("outfit_probe_coral", (0.95, 0.18, 0.28, 1.0))

    torso_width = max(width_x * 0.075, 0.09)
    chest_z = min_z + height_z * 0.66
    waist_z = min_z + height_z * 0.47
    panel = add_bound_box(
        "outfit_probe_front_panel",
        spine.name,
        (center_x, front_y, min_z + height_z * 0.585),
        (torso_width, 0.035, max(height_z * 0.16, 0.2)),
        armature,
        accent,
    )
    belt = add_bound_box(
        "outfit_probe_waist_belt",
        spine.name,
        (center_x, front_y - 0.006, waist_z),
        (torso_width * 1.15, 0.045, max(height_z * 0.025, 0.035)),
        armature,
        trim,
    )

    objects = [panel, belt]
    for label, bone in (("left", left_arm), ("right", right_arm)):
        if not bone:
            continue
        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        center = (head + tail) * 0.5
        cuff = add_bound_box(
            f"outfit_probe_{label}_arm_band",
            bone.name,
            (center.x, center.y - 0.015, center.z),
            (max(width_x * 0.035, 0.06), 0.06, max(height_z * 0.035, 0.055)),
            armature,
            trim,
        )
        objects.append(cuff)

    for obj in objects:
        obj.show_in_front = True

    return {
        "enabled": True,
        "object_count": len(objects),
        "objects": [
            {
                "name": obj.name,
                "bone": obj.vertex_groups[0].name if obj.vertex_groups else None,
                "vertices": len(obj.data.vertices),
                "faces": len(obj.data.polygons),
            }
            for obj in objects
        ],
        "source_bounds": bounds,
        "recommendation": "visual-fit-review",
    }


def role_bone_names(bones: dict[str, bpy.types.PoseBone | None], roles: list[str]) -> dict[str, str | None]:
    return {role: bones[role].name if bones.get(role) else None for role in roles}


def scale_factor_for_profile(profile: dict, char_size: Vector, outfit_size: Vector) -> float:
    axis_index = {"width": 0, "depth": 1, "height": 2}.get(profile["scale_axis"], 2)
    target_size = max(char_size[axis_index] * float(profile["target_size_ratio"]), 0.02)
    return target_size / max(outfit_size[axis_index], 0.001)


def outfit_target_center(profile: dict, character_bounds: dict, front_offset_ratio: float) -> tuple[Vector, float]:
    char_min = Vector(character_bounds["min"])
    char_center = Vector(character_bounds["center"])
    char_size = Vector(character_bounds["size"])
    offset_ratio = float(front_offset_ratio)
    front_offset = max(char_size.y * offset_ratio, 0.025)
    target_y = char_center.y + front_offset if profile.get("surface") == "back" else char_center.y - front_offset
    target_x = char_center.x + char_size.x * float(profile.get("horizontal_center_offset_ratio", 0.0))
    return (
        Vector(
            (
                target_x,
                target_y,
                char_min.z + char_size.z * float(profile["vertical_center_ratio"]),
            )
        ),
        front_offset,
    )


def mesh_world_z_percentile(objects: list[bpy.types.Object], percentile: float) -> float | None:
    values = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        values.extend((obj.matrix_world @ vertex.co).z for vertex in obj.data.vertices)
    if not values:
        return None
    values.sort()
    clamped = max(0.0, min(percentile, 1.0))
    index = min(int(round((len(values) - 1) * clamped)), len(values) - 1)
    return values[index]


def material_names(obj: bpy.types.Object) -> set[str]:
    return {slot.material.name for slot in obj.material_slots if slot.material}


def prune_imported_outfit_meshes(objects: list[bpy.types.Object], excluded_materials: set[str]) -> tuple[list[bpy.types.Object], list[dict]]:
    if not excluded_materials:
        return objects, []
    kept = []
    removed = []
    for obj in objects:
        names = material_names(obj)
        if names and names.issubset(excluded_materials):
            removed.append({"name": obj.name, "materials": sorted(names)})
            bpy.data.objects.remove(obj, do_unlink=True)
        else:
            kept.append(obj)
    return kept, removed


def rotate_outfit_meshes(objects: list[bpy.types.Object], rotation_degrees: tuple[float, float, float]) -> None:
    if not objects or all(abs(degrees) < 0.0001 for degrees in rotation_degrees):
        return
    bounds = mesh_bounds(objects)
    if not bounds:
        return
    center = Vector(bounds["center"])
    rotation = Matrix.Translation(center)
    for degrees, axis in zip(rotation_degrees, ("X", "Y", "Z")):
        if abs(degrees) >= 0.0001:
            rotation = rotation @ Matrix.Rotation(math.radians(degrees), 4, axis)
    rotation = rotation @ Matrix.Translation(-center)
    for obj in objects:
        obj.matrix_world = rotation @ obj.matrix_world
    bpy.context.view_layer.update()


def rotate_outfit_meshes_z(objects: list[bpy.types.Object], degrees: float) -> None:
    rotate_outfit_meshes(objects, (0.0, 0.0, degrees))


def condition_top_outlier_geometry(objects: list[bpy.types.Object]) -> dict:
    report = {"mode": "top-outlier-slim", "changed": []}
    for obj in objects:
        vertices = list(obj.data.vertices)
        if len(vertices) < 16:
            continue
        z_values = [vertex.co.z for vertex in vertices]
        z_min = min(z_values)
        z_max = max(z_values)
        z_size = max(z_max - z_min, 0.001)

        widths = []
        for band_index in range(12):
            low = z_min + z_size * band_index / 12
            high = z_min + z_size * (band_index + 1) / 12
            band = [vertex.co for vertex in vertices if low <= vertex.co.z <= high]
            if len(band) >= 4:
                widths.append(max(point.x for point in band) - min(point.x for point in band))
        body_widths = sorted(width for width in widths if width > 0.001)
        if not body_widths:
            continue
        median_width = body_widths[len(body_widths) // 2]

        top_vertices = [vertex for vertex in vertices if (vertex.co.z - z_min) / z_size >= 0.9]
        if len(top_vertices) < 4:
            continue
        top_width = max(vertex.co.x for vertex in top_vertices) - min(vertex.co.x for vertex in top_vertices)
        if top_width < median_width * 1.7:
            continue

        center_x = sum(vertex.co.x for vertex in top_vertices) / len(top_vertices)
        center_y = sum(vertex.co.y for vertex in top_vertices) / len(top_vertices)
        for vertex in top_vertices:
            z_ratio = (vertex.co.z - z_min) / z_size
            factor = 0.34 if z_ratio < 0.97 else 0.22
            vertex.co.x = center_x + (vertex.co.x - center_x) * factor
            vertex.co.y = center_y + (vertex.co.y - center_y) * max(factor, 0.4)
        obj.data.update()
        report["changed"].append(
            {
                "object": obj.name,
                "top_width": round(top_width, 4),
                "median_width": round(median_width, 4),
                "top_vertex_count": len(top_vertices),
            }
        )
    bpy.context.view_layer.update()
    return report


def conform_outfit_meshes_to_surface(
    objects: list[bpy.types.Object],
    character_bounds: dict,
    *,
    surface: str = "front",
    amount_ratio: float = 0.0,
    exponent: float = 1.6,
    pin_top_ratio: float = 0.0,
) -> dict:
    amount_ratio = float(amount_ratio)
    pin_top_ratio = max(0.0, min(float(pin_top_ratio), 0.95))
    report = {
        "mode": "surface-curve",
        "surface": surface,
        "amount_ratio": round(amount_ratio, 6),
        "pin_top_ratio": round(pin_top_ratio, 6),
        "changed": [],
    }
    if not objects or abs(amount_ratio) <= 0.000001:
        report["mode"] = "none"
        return report

    bounds = mesh_bounds(objects)
    if not bounds:
        report["mode"] = "none"
        return report

    z_min = float(bounds["min"][2])
    z_size = max(float(bounds["size"][2]), 0.001)
    char_depth = max(float(character_bounds["size"][1]), 0.001)
    direction = 1.0 if surface == "back" else -1.0
    max_offset = char_depth * amount_ratio
    exponent = max(float(exponent), 0.2)

    for obj in objects:
        if obj.type != "MESH":
            continue
        matrix = obj.matrix_world.copy()
        inverse = matrix.inverted()
        moved = 0
        max_applied = 0.0
        for vertex in obj.data.vertices:
            world = matrix @ vertex.co
            z_ratio = max(0.0, min((world.z - z_min) / z_size, 1.0))
            if pin_top_ratio > 0.0:
                bend_ratio = max(
                    0.0,
                    min((1.0 - pin_top_ratio - z_ratio) / max(1.0 - pin_top_ratio, 0.001), 1.0),
                )
            else:
                bend_ratio = 1.0 - z_ratio
            offset = direction * max_offset * (bend_ratio**exponent)
            if abs(offset) < 0.000001:
                continue
            world.y += offset
            vertex.co = inverse @ world
            moved += 1
            max_applied = max(max_applied, abs(offset))
        if moved:
            obj.data.update()
            report["changed"].append(
                {
                    "object": obj.name,
                    "vertices": moved,
                    "max_offset": round(max_applied, 6),
                }
            )

    bpy.context.view_layer.update()
    return report


def snap_outfit_meshes_to_surface(
    objects: list[bpy.types.Object],
    character_bounds: dict,
    *,
    surface: str = "front",
    target_gap_ratio: float = 0.02,
    reference_bounds: dict | None = None,
) -> dict:
    snap_bounds = reference_bounds or character_bounds
    report = {
        "mode": "surface-snap",
        "surface": surface,
        "target_gap_ratio": round(float(target_gap_ratio), 6),
        "reference": "local" if reference_bounds else "global",
        "changed": [],
    }
    bounds = mesh_bounds(objects)
    if not objects or not bounds:
        report["mode"] = "none"
        return report

    char_size_y = max(float(character_bounds["size"][1]), 0.001)
    char_min_y = float(snap_bounds["min"][1])
    char_max_y = float(snap_bounds["max"][1])
    if surface == "back":
        current_gap_ratio = (float(bounds["max"][1]) - char_max_y) / char_size_y
        delta_y = (float(target_gap_ratio) - current_gap_ratio) * char_size_y
    else:
        current_gap_ratio = (char_min_y - float(bounds["min"][1])) / char_size_y
        delta_y = (current_gap_ratio - float(target_gap_ratio)) * char_size_y
    if abs(delta_y) <= 0.000001:
        report["changed"].append({"delta_y": 0.0, "source_gap_ratio": round(current_gap_ratio, 6)})
        return report

    for obj in objects:
        obj.location.y += delta_y
    bpy.context.view_layer.update()
    report["changed"].append(
        {
            "delta_y": round(delta_y, 6),
            "source_gap_ratio": round(current_gap_ratio, 6),
        }
    )
    return report


def anchored_target_center(
    profile: dict,
    target_center: Vector,
    character_bounds: dict,
    scaled_bounds: dict,
    objects: list[bpy.types.Object],
) -> Vector:
    if profile.get("anchor") != "hat_top":
        return target_center

    char_min = Vector(character_bounds["min"])
    char_size = Vector(character_bounds["size"])
    rim_z = char_min.z + char_size.z * float(profile["vertical_center_ratio"])
    scaled_center = Vector(scaled_bounds["center"])
    anchor_z = mesh_world_z_percentile(objects, float(profile.get("anchor_z_percentile", 0.0)))
    if anchor_z is None:
        anchor_z = float(scaled_bounds["min"][2])
    anchored = Vector((target_center.x, target_center.y, scaled_center.z + (rim_z - anchor_z)))
    anchor_offset = profile.get("anchor_offset") or (0, 0, 0)
    return anchored + Vector(anchor_offset)


def bone_weights_for_category(
    world_z: float,
    character_bounds: dict,
    profile: dict,
    bind_bones: dict[str, str | None],
) -> dict[str, float]:
    if profile["weighting_mode"] == "height-band-torso":
        return torso_weight_plan(world_z, character_bounds, bind_bones)

    available = {role: name for role, name in bind_bones.items() if name}
    if not available:
        return {}
    if profile["weighting_mode"] == "upper-torso-neck":
        z_ratio = (world_z - float(character_bounds["min"][2])) / max(float(character_bounds["size"][2]), 0.001)
        if z_ratio > 0.74 and available.get("neck"):
            return {available["neck"]: 1.0}
        if z_ratio > 0.64 and available.get("chest"):
            return {available["chest"]: 1.0}
        return {available.get("spine") or available.get("chest") or available.get("neck"): 1.0}

    target_role = profile.get("target_bone_role")
    return {available.get(target_role) or next(iter(available.values())): 1.0}


def import_external_outfit(
    outfit_model: Path,
    armature: bpy.types.Object | None,
    explicit_category: str | None = None,
) -> dict:
    if not outfit_model:
        return {"enabled": False, "reason": "not-configured", "objects": []}
    if not outfit_model.exists():
        return {"enabled": False, "reason": "missing-file", "path": str(outfit_model), "objects": []}
    if not armature:
        return {"enabled": False, "reason": "missing-armature", "path": str(outfit_model), "objects": []}

    character_bounds = scene_mesh_bounds(exclude_prefixes=("outfit_probe_", "outfit_external_"))
    if not character_bounds:
        return {"enabled": False, "reason": "missing-character-bounds", "path": str(outfit_model), "objects": []}

    existing_objects = set(bpy.data.objects)
    errors = try_import(outfit_model)
    imported = [obj for obj in bpy.data.objects if obj not in existing_objects]
    imported_meshes = [obj for obj in imported if obj.type == "MESH"]
    if not imported_meshes:
        return {
            "enabled": False,
            "reason": "no-imported-meshes",
            "path": str(outfit_model),
            "errors": errors,
            "objects": [],
        }

    for index, obj in enumerate(imported_meshes, start=1):
        obj.name = f"outfit_external_{outfit_model.stem}_{index:02d}"
        obj.data.name = f"{obj.name}_mesh"

    excluded_materials = {
        value.strip()
        for value in os.environ.get("OUTFIT_EXCLUDE_MATERIALS", "").split(",")
        if value.strip()
    }
    imported_meshes, pruned_objects = prune_imported_outfit_meshes(imported_meshes, excluded_materials)
    if not imported_meshes:
        return {
            "enabled": False,
            "reason": "all-imported-meshes-pruned",
            "path": str(outfit_model),
            "errors": errors,
            "pruned_objects": pruned_objects,
            "objects": [],
        }

    bones = choose_pose_bones(armature)
    classification = classify_asset(outfit_model.stem, str(outfit_model), explicit_category)
    profile = placement_profile(classification["category"])
    if os.environ.get("OUTFIT_SCALE_AXIS"):
        profile["scale_axis"] = os.environ["OUTFIT_SCALE_AXIS"]
    if os.environ.get("OUTFIT_TARGET_SIZE_RATIO"):
        profile["target_size_ratio"] = float(os.environ["OUTFIT_TARGET_SIZE_RATIO"])
    if os.environ.get("OUTFIT_VERTICAL_CENTER_RATIO"):
        profile["vertical_center_ratio"] = float(os.environ["OUTFIT_VERTICAL_CENTER_RATIO"])
    if os.environ.get("OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO"):
        profile["horizontal_center_offset_ratio"] = float(os.environ["OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO"])
    if os.environ.get("OUTFIT_SURFACE_OFFSET_RATIO"):
        profile["surface_offset_ratio"] = float(os.environ["OUTFIT_SURFACE_OFFSET_RATIO"])
    if os.environ.get("OUTFIT_ANCHOR_Z_PERCENTILE"):
        profile["anchor_z_percentile"] = float(os.environ["OUTFIT_ANCHOR_Z_PERCENTILE"])
    if os.environ.get("OUTFIT_ROTATION_X_DEGREES"):
        profile["rotation_x_degrees"] = float(os.environ["OUTFIT_ROTATION_X_DEGREES"])
    if os.environ.get("OUTFIT_ROTATION_Y_DEGREES"):
        profile["rotation_y_degrees"] = float(os.environ["OUTFIT_ROTATION_Y_DEGREES"])
    if os.environ.get("OUTFIT_ROTATION_Z_DEGREES"):
        profile["rotation_z_degrees"] = float(os.environ["OUTFIT_ROTATION_Z_DEGREES"])
    if os.environ.get("OUTFIT_SURFACE_CONFORMER"):
        profile["surface_conformer"] = os.environ["OUTFIT_SURFACE_CONFORMER"]
    if os.environ.get("OUTFIT_SURFACE_CONFORM_RATIO"):
        profile["surface_conform_ratio"] = float(os.environ["OUTFIT_SURFACE_CONFORM_RATIO"])
    if os.environ.get("OUTFIT_SURFACE_CONFORM_EXPONENT"):
        profile["surface_conform_exponent"] = float(os.environ["OUTFIT_SURFACE_CONFORM_EXPONENT"])
    if os.environ.get("OUTFIT_SURFACE_CONFORM_PIN_TOP_RATIO"):
        profile["surface_conform_pin_top_ratio"] = float(os.environ["OUTFIT_SURFACE_CONFORM_PIN_TOP_RATIO"])
    if os.environ.get("OUTFIT_SURFACE_SNAP"):
        profile["surface_snap"] = os.environ["OUTFIT_SURFACE_SNAP"]
    if os.environ.get("OUTFIT_SURFACE_SNAP_GAP_RATIO"):
        profile["surface_snap_gap_ratio"] = float(os.environ["OUTFIT_SURFACE_SNAP_GAP_RATIO"])
    if os.environ.get("OUTFIT_ANCHOR"):
        profile["anchor"] = os.environ["OUTFIT_ANCHOR"]
    if os.environ.get("OUTFIT_FIT_SCOPE"):
        profile["fit_scope"] = os.environ["OUTFIT_FIT_SCOPE"]
    if any(os.environ.get(key) for key in ("OUTFIT_ANCHOR_OFFSET_X", "OUTFIT_ANCHOR_OFFSET_Y", "OUTFIT_ANCHOR_OFFSET_Z")):
        profile["anchor_offset"] = [
            float(os.environ.get("OUTFIT_ANCHOR_OFFSET_X", "0")),
            float(os.environ.get("OUTFIT_ANCHOR_OFFSET_Y", "0")),
            float(os.environ.get("OUTFIT_ANCHOR_OFFSET_Z", "0")),
        ]
    geometry_conditioning = {"mode": "none", "changed": []}
    if os.environ.get("OUTFIT_GEOMETRY_CONDITIONER") == "top-outlier-slim":
        geometry_conditioning = condition_top_outlier_geometry(imported_meshes)
    rotate_outfit_meshes(
        imported_meshes,
        (
            float(profile.get("rotation_x_degrees", 0.0)),
            float(profile.get("rotation_y_degrees", 0.0)),
            float(profile.get("rotation_z_degrees", 0.0)),
        ),
    )
    outfit_bounds = mesh_bounds(imported_meshes)
    target_bone = bones.get(profile["target_bone_role"]) or bones.get("spine")
    bind_bones = role_bone_names(bones, profile["bind_roles"])
    bind_bone = target_bone
    if not bind_bone:
        return {
            "enabled": False,
            "reason": f"missing-{profile['target_bone_role']}-bone",
            "path": str(outfit_model),
            "classification": classification,
            "placement": profile,
            "errors": errors,
            "objects": [obj.name for obj in imported_meshes],
        }

    char_size = Vector(character_bounds["size"])
    outfit_size = Vector(outfit_bounds["size"])
    scale_factor = scale_factor_for_profile(profile, char_size, outfit_size)
    front_offset_ratio = float(os.environ.get("OUTFIT_FRONT_OFFSET_RATIO", str(profile["surface_offset_ratio"])))
    target_center, front_offset = outfit_target_center(profile, character_bounds, front_offset_ratio)

    for obj in imported_meshes:
        obj.scale = tuple(component * scale_factor for component in obj.scale)
    bpy.context.view_layer.update()

    scaled_bounds = mesh_bounds(imported_meshes)
    target_center = anchored_target_center(profile, target_center, character_bounds, scaled_bounds, imported_meshes)
    scaled_center = Vector(scaled_bounds["center"])
    offset = target_center - scaled_center
    weight_summary = {}
    for obj in imported_meshes:
        obj.location = obj.location + offset
    bpy.context.view_layer.update()

    local_surface_bounds = None
    if profile.get("fit_scope") == "neck-chest":
        updated_bounds = mesh_bounds(imported_meshes) or scaled_bounds
        local_surface_bounds = local_scene_mesh_bounds(
            center=Vector(updated_bounds["center"]),
            character_bounds=character_bounds,
            exclude_prefixes=("outfit_probe_", "outfit_external_"),
        )

    surface_snapping = {"mode": "none", "changed": []}
    if profile.get("surface_snap") == "surface-gap":
        surface_snapping = snap_outfit_meshes_to_surface(
            imported_meshes,
            character_bounds,
            surface=profile.get("surface", "front"),
            target_gap_ratio=float(profile.get("surface_snap_gap_ratio", 0.02)),
            reference_bounds=local_surface_bounds,
        )

    surface_conforming = {"mode": "none", "changed": []}
    if profile.get("surface_conformer") == "surface-curve":
        surface_conforming = conform_outfit_meshes_to_surface(
            imported_meshes,
            character_bounds,
            surface=profile.get("surface", "front"),
            amount_ratio=float(profile.get("surface_conform_ratio", 0.0)),
            exponent=float(profile.get("surface_conform_exponent", 1.6)),
            pin_top_ratio=float(profile.get("surface_conform_pin_top_ratio", 0.0)),
        )

    for obj in imported_meshes:
        for group in list(obj.vertex_groups):
            obj.vertex_groups.remove(group)
        group_cache = {}
        object_counts = {}
        for vertex in obj.data.vertices:
            world_z = (obj.matrix_world @ vertex.co).z
            weights = bone_weights_for_category(world_z, character_bounds, profile, bind_bones)
            for bone_name, weight in weights.items():
                group = group_cache.get(bone_name)
                if not group:
                    group = obj.vertex_groups.new(name=bone_name)
                    group_cache[bone_name] = group
                group.add([vertex.index], weight, "REPLACE")
                object_counts[bone_name] = object_counts.get(bone_name, 0) + 1
        obj.parent = armature
        if not any(mod.type == "ARMATURE" and mod.object == armature for mod in obj.modifiers):
            mod = obj.modifiers.new("Armature", "ARMATURE")
            mod.object = armature
        weight_summary[obj.name] = {
            "groups": sorted(object_counts),
            "vertex_assignments": object_counts,
        }

    bpy.context.view_layer.update()
    fitted_bounds = mesh_bounds(imported_meshes)
    fit_check = outfit_fit_check(
        character_bounds,
        fitted_bounds,
        scope=profile["fit_scope"],
        surface=profile.get("surface", "front"),
    )
    return {
        "enabled": True,
        "path": str(outfit_model),
        "classification": classification,
        "placement": profile,
        "source_bounds": outfit_bounds,
        "fitted_bounds": fitted_bounds,
        "character_bounds": character_bounds,
        "bind_bone": bind_bone.name,
        "bind_bones": bind_bones,
        "scale_factor": round(scale_factor, 6),
        "front_offset_ratio": round(front_offset_ratio, 6),
        "front_offset": round(front_offset, 6),
        "fit_check": fit_check,
        "weighting": {
            "mode": "height-band-torso",
            "objects": weight_summary,
        },
        "object_count": len(imported_meshes),
        "pruned_objects": pruned_objects,
        "geometry_conditioning": geometry_conditioning,
        "surface_snapping": surface_snapping,
        "surface_conforming": surface_conforming,
        "objects": [
            {
                "name": obj.name,
                "vertices": len(obj.data.vertices),
                "faces": len(obj.data.polygons),
                "materials": [slot.material.name for slot in obj.material_slots if slot.material],
            }
            for obj in imported_meshes
        ],
        "errors": errors,
        "recommendation": "visual-fit-review",
    }


def create_test_rig() -> bpy.types.Object:
    arm_data = bpy.data.armatures.new("SmokeRig")
    armature = bpy.data.objects.new("SmokeRig", arm_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    bones = {}
    specs = {
        "hips": ((0, 0, 0.8), (0, 0, 1.1), None),
        "spine": ((0, 0, 1.1), (0, 0, 2.0), "hips"),
        "head": ((0, 0, 2.0), (0, 0, 2.45), "spine"),
        "upper_arm.L": ((-0.35, 0, 1.85), (-1.0, 0, 1.55), "spine"),
        "upper_arm.R": ((0.35, 0, 1.85), (1.0, 0, 1.55), "spine"),
        "forearm.L": ((-1.0, 0, 1.55), (-1.45, 0, 1.25), "upper_arm.L"),
        "forearm.R": ((1.0, 0, 1.55), (1.45, 0, 1.25), "upper_arm.R"),
        "thigh.L": ((-0.18, 0, 0.8), (-0.25, 0, 0.25), "hips"),
        "thigh.R": ((0.18, 0, 0.8), (0.25, 0, 0.25), "hips"),
        "shin.L": ((-0.25, 0, 0.25), (-0.25, 0, -0.45), "thigh.L"),
        "shin.R": ((0.25, 0, 0.25), (0.25, 0, -0.45), "thigh.R"),
    }
    for name, (head, tail, parent) in specs.items():
        bone = arm_data.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        bones[name] = bone
        if parent:
            bone.parent = bones[parent]
            bone.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")

    material = bpy.data.materials.new("smoke_character_blue")
    material.diffuse_color = (0.2, 0.45, 0.95, 1.0)

    parts = [
        ("torso", "spine", (0, 0, 1.45), (0.58, 0.32, 0.9)),
        ("head", "head", (0, 0, 2.25), (0.42, 0.36, 0.42)),
        ("upper_arm.L", "upper_arm.L", (-0.7, 0, 1.7), (0.62, 0.18, 0.22)),
        ("upper_arm.R", "upper_arm.R", (0.7, 0, 1.7), (0.62, 0.18, 0.22)),
        ("forearm.L", "forearm.L", (-1.22, 0, 1.4), (0.5, 0.16, 0.2)),
        ("forearm.R", "forearm.R", (1.22, 0, 1.4), (0.5, 0.16, 0.2)),
        ("thigh.L", "thigh.L", (-0.22, 0, 0.5), (0.22, 0.2, 0.65)),
        ("thigh.R", "thigh.R", (0.22, 0, 0.5), (0.22, 0.2, 0.65)),
        ("shin.L", "shin.L", (-0.25, 0, -0.1), (0.2, 0.18, 0.65)),
        ("shin.R", "shin.R", (0.25, 0, -0.1), (0.2, 0.18, 0.65)),
    ]
    for part in parts:
        obj = add_weighted_part(*part, armature)
        obj.data.materials.append(material)

    return armature


def find_armature() -> bpy.types.Object | None:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        return None
    armatures.sort(key=lambda obj: len(obj.data.bones), reverse=True)
    return armatures[0]


def choose_pose_bones(armature: bpy.types.Object) -> dict[str, bpy.types.PoseBone]:
    pose_bones = {bone.name.lower(): bone for bone in armature.pose.bones}

    def find(*needles: str):
        for needle in needles:
            for name, bone in pose_bones.items():
                if needle in name:
                    return bone
        return None

    def find_side(side: str, *needles: str):
        side_tokens = {
            "left": ("_l_", "_l", ".l", "left", "左"),
            "right": ("_r_", "_r", ".r", "right", "右"),
        }[side]
        for needle in needles:
            for name, bone in pose_bones.items():
                if needle in name and any(token in name for token in side_tokens):
                    return bone
        return None

    return {
        "hips": find("hips", "pelvis", "腰"),
        "spine": find("spine", "chest", "upperchest", "body"),
        "chest": find("upperchest", "chest", "spine"),
        "neck": find("neck"),
        "head": find("head", "neck"),
        "left_arm": find_side("left", "upperarm", "upper_arm", "arm", "腕"),
        "right_arm": find_side("right", "upperarm", "upper_arm", "arm", "腕"),
        "left_lower_arm": find_side("left", "lowerarm", "forearm", "lower_arm"),
        "right_lower_arm": find_side("right", "lowerarm", "forearm", "lower_arm"),
        "left_hand": find_side("left", "hand", "wrist", "手"),
        "right_hand": find_side("right", "hand", "wrist", "手"),
        "left_leg": find_side("left", "upperleg", "thigh", "leg", "足"),
        "right_leg": find_side("right", "upperleg", "thigh", "leg", "足"),
    }


def keyframe_pose_bone(bone, frame: int, rotation_xyz: tuple[float, float, float]) -> None:
    if not bone:
        return
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(v) for v in rotation_xyz)
    bone.keyframe_insert(data_path="rotation_euler", frame=frame)


def secondary_pose_targets(armature: bpy.types.Object) -> list[bpy.types.PoseBone]:
    targets = []
    for bone in armature.pose.bones:
        name = bone.name.lower()
        if "hairjoint" in name or "skirt" in name or "sleeve" in name:
            targets.append(bone)
    return targets[:32]


def animate_armature(armature: bpy.types.Object, preset_name: str = "wave") -> dict:
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    for pose_bone in armature.pose.bones:
        pose_bone.rotation_mode = "XYZ"
    bones = choose_pose_bones(armature)

    preset = animation_preset(preset_name)
    frames = preset["frames"]
    secondary_bones = secondary_pose_targets(armature)
    for index, frame in enumerate(frames):
        bpy.context.scene.frame_set(frame)
        wave = preset_value(preset, "right_arm", index)
        right_arm_z = preset_value(preset, "right_arm_z", index)
        left_arm = preset_value(preset, "left_arm", index)
        left_arm_z = preset_value(preset, "left_arm_z", index, -18)
        lean = preset_value(preset, "spine_lean", index)
        twist = preset_value(preset, "spine_twist", index)
        head_pitch = preset_value(preset, "head_pitch", index, -lean * 2)
        head_yaw = preset_value(preset, "head_yaw", index)
        keyframe_pose_bone(bones["spine"], frame, (lean, 0, twist))
        keyframe_pose_bone(bones["head"], frame, (head_pitch, head_yaw, 0))
        keyframe_pose_bone(bones["left_arm"], frame, (left_arm, 0, left_arm_z))
        keyframe_pose_bone(bones["right_arm"], frame, (wave, 0, right_arm_z))
        left_leg = preset_value(preset, "left_leg", index, 5 if preset.get("leg_lift") and index == 1 else 0)
        right_leg = preset_value(preset, "right_leg", index, -5 if preset.get("leg_lift") and index == 2 else 0)
        keyframe_pose_bone(bones["left_leg"], frame, (left_leg, 0, 0))
        keyframe_pose_bone(bones["right_leg"], frame, (right_leg, 0, 0))
        sway = preset_value(preset, "secondary_sway", index)
        for index, bone in enumerate(secondary_bones):
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = (
                math.radians(sway * (0.35 if "skirt" in bone.name.lower() else 0.18)),
                0,
                math.radians(sway * (0.22 if index % 2 == 0 else -0.22)),
            )
            bone.keyframe_insert(data_path="rotation_euler", frame=frame)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max(frames)
    bpy.context.scene.render.fps = 24
    if armature.animation_data and armature.animation_data.action:
        armature.animation_data.action.name = f"{preset['name']}_Armature"

    keyed = [name for name, bone in bones.items() if bone is not None]
    return {
        "animation": preset["name"],
        "frames": frames,
        "tags": preset.get("tags", []),
        "review_frames": preset.get("review_frames", []),
        "matched_bones": {name: bone.name if bone else None for name, bone in bones.items()},
        "keyed_roles": keyed,
        "secondary_pose_bone_count": len(secondary_bones),
    }


def find_shape_key(*needles: str):
    lowered_needles = tuple(needle.lower() for needle in needles)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        for key in obj.data.shape_keys.key_blocks:
            name = key.name.lower()
            if all(needle in name for needle in lowered_needles):
                return obj, key
    return None, None


def key_shape(key, frame: int, value: float) -> None:
    if not key:
        return
    key.value = value
    key.keyframe_insert(data_path="value", frame=frame)


def animate_expressions(preset_name: str | None, frame_end: int) -> dict:
    profile = build_face_profile("scene", collect_shape_keys())
    plan = plan_facial_animation(profile, preset_name, frame_end=frame_end)
    keyed_shapes = set()

    for item in plan["keyframes"]:
        key = shape_key_from_profile_entry(item)
        if not key:
            continue
        key_shape(key, int(item["frame"]), float(item["value"]))
        keyed_shapes.add(item["shape"])

    return {
        "expression_animation": {
            "preset": plan["preset"],
            "object": next((item["mesh"] for item in plan["keyframes"]), None),
            "keyed": plan["keyed"],
            "keyed_expressions": plan["keyed_expressions"],
            "keyed_visemes": plan["keyed_visemes"],
            "missing": plan["missing"],
            "missing_expressions": plan["missing_expressions"],
            "missing_visemes": plan["missing_visemes"],
            "keyframe_count": plan["keyframe_count"],
            "shape_keys": sorted(keyed_shapes),
        }
    }


def collect_shape_keys() -> dict[str, list[str]]:
    shape_keys = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        shape_keys[obj.name] = [key.name for key in obj.data.shape_keys.key_blocks]
    return shape_keys


def shape_key_from_profile_entry(entry: dict):
    obj = bpy.data.objects.get(entry.get("mesh", ""))
    if not obj or obj.type != "MESH" or not obj.data.shape_keys:
        return None
    return obj.data.shape_keys.key_blocks.get(entry.get("shape", ""))


def key_profile_shapes(entries: list[dict], frame: int, active_values: dict[str, float]) -> int:
    keyed = 0
    for entry in entries:
        key = shape_key_from_profile_entry(entry)
        if key:
            key_shape(key, frame, float(active_values.get(entry["shape"], 0.0)))
            keyed += 1
    return keyed


def apply_lipsync_timeline(timeline_path: Path | None) -> dict:
    if not timeline_path:
        return {"lipsync_animation": {"enabled": False, "reason": "not-configured"}}
    if not timeline_path.exists():
        return {
            "lipsync_animation": {
                "enabled": False,
                "reason": "timeline-missing",
                "timeline": str(timeline_path),
            }
        }

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    profile = build_face_profile(timeline_path.stem, collect_shape_keys())
    viseme_entries = list(profile.get("visemes", {}).values())
    expression_entries = profile.get("expressions", {})
    fps = int(bpy.context.scene.render.fps or 24)
    keyed_visemes = set()
    missing_visemes = set()
    keyed_cues = 0

    for cue in timeline.get("cues", []):
        viseme = str(cue.get("viseme", "rest")).lower()
        canonical = VISEME_ALIASES.get(viseme, viseme)
        start = max(1, int(round(float(cue.get("time", 0.0)) * fps)) + 1)
        end = max(start + 1, int(round((float(cue.get("time", 0.0)) + float(cue.get("duration", 0.0))) * fps)) + 1)
        if canonical == "rest":
            keyed_cues += key_profile_shapes(viseme_entries, start, {})
            continue
        entry = profile.get("visemes", {}).get(canonical)
        if not entry:
            missing_visemes.add(canonical)
            continue
        keyed_cues += key_profile_shapes(
            viseme_entries,
            start,
            {entry["shape"]: float(cue.get("value", 1.0))},
        )
        keyed_cues += key_profile_shapes(viseme_entries, end, {})
        keyed_visemes.add(canonical)

    keyed_expressions = []
    for expression in timeline.get("expressions", []):
        name = str(expression.get("name", "")).lower()
        entry = expression_entries.get(name)
        if not entry:
            continue
        start = max(1, int(round(float(expression.get("time", 0.0)) * fps)) + 1)
        end = max(start + 1, int(round((float(expression.get("time", 0.0)) + float(expression.get("duration", 0.0))) * fps)) + 1)
        key = shape_key_from_profile_entry(entry)
        if not key:
            continue
        key_shape(key, start, float(expression.get("value", 1.0)))
        key_shape(key, end, 0.0)
        keyed_expressions.append(name)

    duration = float(timeline.get("duration", 0.0))
    if duration > 0:
        bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, int(math.ceil(duration * fps)) + 1)

    return {
        "lipsync_animation": {
            "enabled": True,
            "timeline": str(timeline_path),
            "duration": duration,
            "fps": fps,
            "cue_count": len(timeline.get("cues", [])),
            "keyed_cues": keyed_cues,
            "keyed_visemes": sorted(keyed_visemes),
            "missing_visemes": sorted(missing_visemes),
            "keyed_expressions": sorted(set(keyed_expressions)),
        }
    }


def add_camera_and_light() -> None:
    bpy.ops.object.light_add(type="AREA", location=(0, -3.5, 4.5))
    light = bpy.context.object
    light.name = "SmokeKeyLight"
    light.data.energy = 700
    light.data.size = 5

    bpy.ops.object.camera_add(location=(0, -5.4, 1.35), rotation=(math.radians(78), 0, 0))
    camera = bpy.context.object
    camera.data.lens = 45
    bpy.context.scene.camera = camera


def render_angles() -> list[str]:
    raw = os.environ.get("RENDER_ANGLES", "front,side,three_quarter")
    allowed = {"front", "back", "side", "three_quarter", "portrait"}
    angles = [angle.strip() for angle in raw.split(",") if angle.strip()]
    return [angle for angle in angles if angle in allowed] or ["front"]


def head_focus_point() -> Vector | None:
    armature = find_armature()
    if not armature:
        return None
    head = choose_pose_bones(armature).get("head")
    if not head:
        return None
    head_world = armature.matrix_world @ head.head
    tail_world = armature.matrix_world @ head.tail
    return head_world.lerp(tail_world, 0.55)


def position_camera(angle: str) -> None:
    camera = bpy.context.scene.camera
    if not camera:
        return
    bounds = scene_mesh_bounds()
    if not bounds:
        return

    center = Vector(bounds["center"])
    size = Vector(bounds["size"])
    if angle == "portrait":
        distance = max(size.z * 1.25, 2.05)
        target = head_focus_point() or Vector((center.x, center.y, center.z + size.z * 0.47))
        camera_z = target.z + size.z * 0.015
        location = Vector((target.x, target.y - distance, camera_z))
        camera.data.lens = float(os.environ.get("RENDER_PORTRAIT_LENS", "72"))
        camera.location = location
        direction = target - camera.location
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return

    distance = max(size.z * 3.45, 4.8)
    target = Vector((center.x, center.y, center.z + size.z * 0.03))
    camera_z = target.z + size.z * 0.26
    camera.data.lens = 45
    if angle == "side":
        location = Vector((target.x - distance, target.y, camera_z))
    elif angle == "back":
        location = Vector((target.x, target.y + distance, camera_z))
    elif angle == "three_quarter":
        location = Vector((target.x - distance * 0.68, target.y - distance * 0.68, camera_z))
    else:
        location = Vector((target.x, target.y - distance, camera_z))

    camera.location = location
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def apply_compact_review_pose() -> None:
    armature = find_armature()
    if not armature:
        return
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    bones = choose_pose_bones(armature)
    compact_rotations = {
        "left_arm": (-60, 0, -80),
        "right_arm": (-60, 0, 80),
        "left_lower_arm": (18, 0, -12),
        "right_lower_arm": (18, 0, 12),
    }
    for role, rotation in compact_rotations.items():
        bone = bones.get(role)
        if not bone:
            continue
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = tuple(math.radians(value) for value in rotation)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def render_pose_stills(output_dir: Path, frames: list[int]) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("CLEAR_RENDER_DIR", "1") == "1":
        clear_pose_render_files(output_dir)
    scene = bpy.context.scene
    render_engine = os.environ.get("RENDER_ENGINE", "BLENDER_WORKBENCH")
    scene.render.engine = render_engine
    if render_engine == "BLENDER_EEVEE_NEXT":
        scene.eevee.taa_render_samples = 32
    elif render_engine == "BLENDER_WORKBENCH":
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "TEXTURE"
        for attr, value in (
            ("show_cavity", True),
            ("show_shadows", True),
            ("cavity_valley_factor", 1.1),
            ("cavity_ridge_factor", 0.45),
            ("shadow_intensity", 0.35),
        ):
            if hasattr(shading, attr):
                setattr(shading, attr, value)
    scene.render.resolution_x = int(os.environ.get("RENDER_WIDTH", "768"))
    scene.render.resolution_y = int(os.environ.get("RENDER_HEIGHT", "1152"))
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.render.image_settings.file_format = "PNG"

    paths = []
    for angle in render_angles():
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            if os.environ.get("RENDER_COMPACT_ARMS", "0") == "1":
                apply_compact_review_pose()
            position_camera(angle)
            filename = f"pose_{frame:04d}.png" if angle == "front" else f"pose_{angle}_{frame:04d}.png"
            path = output_dir / filename
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            paths.append(str(path))
    return paths


def parse_frame_list(raw: str, fallback: list[int]) -> list[int]:
    frames = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            frames.append(int(item))
        except ValueError:
            continue
    return frames or fallback


def export_outputs(
    output_blend: Path,
    output_glb: Path,
    output_vrm: Path | None = None,
    export_blend: bool = True,
    export_glb: bool = True,
) -> tuple[list[str], dict]:
    errors = []
    exported = {"blend": False, "glb": False, "vrm": False}
    if export_blend:
        output_blend.parent.mkdir(parents=True, exist_ok=True)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
            exported["blend"] = True
        except Exception as exc:
            errors.append(f"blend save failed: {exc}")
    if export_glb:
        output_glb.parent.mkdir(parents=True, exist_ok=True)
        try:
            bpy.ops.export_scene.gltf(
                filepath=str(output_glb),
                export_format="GLB",
                export_animations=True,
                export_frame_range=True,
                export_force_sampling=True,
            )
            exported["glb"] = True
        except Exception as exc:
            errors.append(f"glb export failed: {exc}")
    if output_vrm:
        output_vrm.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(bpy.ops.export_scene, "vrm"):
            try:
                bpy.ops.export_scene.vrm(filepath=str(output_vrm))
                exported["vrm"] = True
            except Exception as exc:
                errors.append(f"vrm export failed: {exc}")
        else:
            errors.append("vrm export failed: bpy.ops.export_scene.vrm unavailable")
    return errors, exported


def scene_summary(armature: bpy.types.Object | None, mode: str, errors: list[str], animation_report: dict) -> dict:
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    return {
        "status": "error" if errors or not armature else "ok",
        "mode": mode,
        "armature": armature.name if armature else None,
        "bone_count": len(armature.data.bones) if armature else 0,
        "mesh_count": len(meshes),
        "mesh_names": [obj.name for obj in meshes[:100]],
        "frame_start": bpy.context.scene.frame_start,
        "frame_end": bpy.context.scene.frame_end,
        "fps": bpy.context.scene.render.fps,
        "errors": errors,
        **animation_report,
    }


def safe_vrm_summary(path: Path | None) -> dict | None:
    if not path or path.suffix.lower() != ".vrm" or not path.exists():
        return None
    try:
        return summarize_vrm_file(path)
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    total_start = time.perf_counter()
    timings = {}
    args = argv_after_separator()
    input_model = Path(args[0] if len(args) >= 1 else "/workspace/input/model.vrm")
    report_json = Path(args[1] if len(args) >= 2 else "/workspace/results/animation_smoke.json")
    output_blend = Path(args[2] if len(args) >= 3 else "/workspace/outputs/animation_smoke.blend")
    output_glb = Path(args[3] if len(args) >= 4 else "/workspace/outputs/animation_smoke.glb")
    output_vrm_env = os.environ.get("OUTPUT_VRM", "").strip()
    output_vrm = Path(output_vrm_env) if output_vrm_env else None
    animation_preset_name = os.environ.get("ANIMATION_PRESET", "wave")
    export_blend_enabled = os.environ.get("EXPORT_BLEND", "1") == "1"
    export_glb_enabled = os.environ.get("EXPORT_GLB", "1") == "1"
    generate_test_rig = os.environ.get("GENERATE_TEST_RIG", "1") == "1"
    clear_imported_animation = os.environ.get("CLEAR_IMPORTED_ANIMATION", "1") == "1"
    normalize_materials = os.environ.get("NORMALIZE_MATERIALS_FOR_GLB", "1") == "1"
    animate_expression_keys = os.environ.get("ANIMATE_EXPRESSIONS", "1") == "1"
    facial_preset_name = os.environ.get("FACIAL_PRESET", "").strip() or facial_preset_for_animation(animation_preset_name)
    add_outfit_probe_enabled = os.environ.get("ADD_OUTFIT_PROBE", "1") == "1"
    outfit_model_env = os.environ.get("OUTFIT_MODEL", "").strip()
    outfit_model = Path(outfit_model_env) if outfit_model_env else None
    outfit_category = os.environ.get("OUTFIT_CATEGORY", "").strip() or None
    render_stills = os.environ.get("RENDER_POSE_STILLS", "1") == "1"
    render_dir = Path(os.environ.get("RENDER_DIR", "/workspace/outputs/pose_renders"))
    render_frames = parse_frame_list(os.environ.get("RENDER_POSE_FRAMES", ""), [1, 24, 36, 48, 72])
    lipsync_timeline_env = os.environ.get("LIPSYNC_TIMELINE_JSON", "").strip()
    lipsync_timeline = Path(lipsync_timeline_env) if lipsync_timeline_env else None

    stage_start = time.perf_counter()
    clear_scene()
    timings["clear_scene_seconds"] = elapsed_since(stage_start)
    errors = []
    input_vrm_summary = safe_vrm_summary(input_model)
    cleanup_report = {
        "cleared_animation_items": 0,
        "material_simplification": {"changed": [], "skipped": []},
        "removed_default_cubes": [],
    }
    mode = "imported-model"
    if input_model.exists():
        stage_start = time.perf_counter()
        errors.extend(try_import(input_model))
        timings["import_seconds"] = elapsed_since(stage_start)
        stage_start = time.perf_counter()
        cleanup_report["removed_default_cubes"] = remove_default_scene_cubes()
        if clear_imported_animation:
            cleanup_report["cleared_animation_items"] = clear_existing_animation()
        timings["cleanup_seconds"] = elapsed_since(stage_start)
    elif generate_test_rig:
        mode = "generated-test-rig"
        stage_start = time.perf_counter()
        create_test_rig()
        timings["test_rig_seconds"] = elapsed_since(stage_start)
    else:
        errors.append(f"missing input model: {input_model}")

    armature = find_armature()
    stage_start = time.perf_counter()
    animation_report = animate_armature(armature, animation_preset_name) if armature else {}
    if animate_expression_keys:
        frame_end = max(animation_report.get("frames", [72]))
        animation_report.update(animate_expressions(facial_preset_name, frame_end))
    animation_report.update(apply_lipsync_timeline(lipsync_timeline))
    timings["animation_seconds"] = elapsed_since(stage_start)
    stage_start = time.perf_counter()
    external_outfit_report = (
        import_external_outfit(outfit_model, armature, outfit_category)
        if outfit_model
        else {"enabled": False, "reason": "not-configured", "objects": []}
    )
    outfit_probe_report = add_outfit_probe(armature) if add_outfit_probe_enabled else {"enabled": False, "reason": "disabled", "objects": []}
    timings["outfit_seconds"] = elapsed_since(stage_start)
    stage_start = time.perf_counter()
    add_camera_and_light()
    if normalize_materials:
        cleanup_report["material_simplification"] = simplify_materials_for_glb()
    secondary_bone_report = audit_secondary_bones(armature)
    timings["scene_prep_seconds"] = elapsed_since(stage_start)
    stage_start = time.perf_counter()
    render_paths = render_pose_stills(render_dir, render_frames) if render_stills else []
    timings["pose_render_seconds"] = elapsed_since(stage_start)
    stage_start = time.perf_counter()
    export_errors, export_report = export_outputs(
        output_blend,
        output_glb,
        output_vrm,
        export_blend=export_blend_enabled,
        export_glb=export_glb_enabled,
    )
    timings["export_seconds"] = elapsed_since(stage_start)
    errors.extend(export_errors)

    stage_start = time.perf_counter()
    output_vrm_summary = safe_vrm_summary(output_vrm)
    vrm_preservation = (
        compare_vrm_summaries(input_vrm_summary, output_vrm_summary)
        if input_vrm_summary and output_vrm_summary and "error" not in input_vrm_summary and "error" not in output_vrm_summary
        else None
    )
    timings["vrm_summary_seconds"] = elapsed_since(stage_start)
    timings["total_seconds"] = elapsed_since(total_start)

    report = scene_summary(armature, mode, errors, animation_report)
    report.update(
        {
            **cleanup_report,
            "input_model": str(input_model),
            "input_vrm_summary": input_vrm_summary,
            "output_blend": str(output_blend),
            "output_glb": str(output_glb),
            "output_vrm": str(output_vrm) if output_vrm else None,
            "output_vrm_summary": output_vrm_summary,
            "vrm_preservation": vrm_preservation,
            "exports": export_report,
            "pose_renders": render_paths,
            "secondary_bone_audit": secondary_bone_report,
            "external_outfit": external_outfit_report,
            "outfit_probe": outfit_probe_report,
            "face_profile": build_face_profile(report_json.stem, collect_shape_keys()),
            "timings": timings,
        }
    )
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
