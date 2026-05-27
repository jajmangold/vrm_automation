import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import bpy


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def material_texture_paths(material: bpy.types.Material) -> list[str]:
    paths = []
    if not material.use_nodes or not material.node_tree:
        return paths
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        if image and image.filepath:
            paths.append(bpy.path.abspath(image.filepath))
    return sorted(set(paths))


def main() -> None:
    args = argv_after_separator()
    input_model = Path(args[0]) if args else None
    output_json = Path(
        os.environ.get("MATERIAL_AUDIT_JSON")
        or (args[2] if len(args) >= 3 else "/workspace/results/material_audit.json")
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)

    if input_model and not input_model.exists():
        report = {
            "status": "skipped-missing-input",
            "input_model": str(input_model),
            "material_count": 0,
            "materials": [],
            "likely_duplicate_groups": [],
            "atlas_recommendation": "not-evaluated",
        }
        output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    material_users = defaultdict(list)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            if slot.material:
                material_users[slot.material.name].append(obj.name)

    materials = []
    duplicate_groups = defaultdict(list)
    for mat_name, users in sorted(material_users.items()):
        mat = bpy.data.materials.get(mat_name)
        textures = material_texture_paths(mat) if mat else []
        key = tuple(textures) or (mat_name.removesuffix(".001").removesuffix(".002"),)
        duplicate_groups[key].append(mat_name)
        materials.append(
            {
                "name": mat_name,
                "users": sorted(set(users)),
                "texture_paths": textures,
                "uses_nodes": bool(mat and mat.use_nodes),
            }
        )

    likely_duplicates = [
        sorted(names) for names in duplicate_groups.values() if len(names) > 1
    ]
    report = {
        "material_count": len(materials),
        "materials": materials,
        "likely_duplicate_groups": likely_duplicates,
        "atlas_recommendation": "manual-review"
        if likely_duplicates or len(materials) > 12
        else "not-needed",
    }
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
