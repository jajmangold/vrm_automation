import json
import sys
from pathlib import Path

import bpy


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def try_import(path: Path) -> list[str]:
    errors = []
    suffix = path.suffix.lower()
    try:
        if suffix == ".vrm" and hasattr(bpy.ops.import_scene, "vrm"):
            bpy.ops.import_scene.vrm(filepath=str(path))
        elif suffix in {".glb", ".gltf"}:
            bpy.ops.import_scene.gltf(filepath=str(path))
        elif suffix == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(path))
        elif suffix in {".pmx", ".pmd"} and hasattr(bpy.ops, "mmd_tools"):
            bpy.ops.mmd_tools.import_model(filepath=str(path))
        else:
            errors.append(f"no importer registered for {suffix}")
    except Exception as exc:
        errors.append(f"import failed: {exc}")
    return errors


def inspect_scene(import_errors: list[str]) -> dict:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    shape_key_count = 0
    for obj in meshes:
        keys = getattr(getattr(obj.data, "shape_keys", None), "key_blocks", None)
        if keys:
            shape_key_count += len(keys)

    materials = sorted({slot.material.name for obj in meshes for slot in obj.material_slots if slot.material})
    return {
        "blender_version": bpy.app.version_string,
        "objects": len(bpy.context.scene.objects),
        "armatures": [{"name": obj.name, "bones": len(obj.data.bones)} for obj in armatures],
        "mesh_count": len(meshes),
        "mesh_names": [obj.name for obj in meshes[:200]],
        "material_count": len(materials),
        "materials": materials[:300],
        "shape_key_count": shape_key_count,
        "import_errors": import_errors,
        "warnings": qa_warnings(armatures, meshes, materials, shape_key_count),
    }


def qa_warnings(armatures, meshes, materials, shape_key_count: int) -> list[str]:
    warnings = []
    if not armatures:
        warnings.append("no armature found")
    if len(armatures) > 1:
        warnings.append("multiple armatures found")
    if not meshes:
        warnings.append("no meshes found")
    if not materials:
        warnings.append("no materials found")
    if shape_key_count == 0:
        warnings.append("no shape keys found; facial expression automation may be missing")
    return warnings


def main() -> None:
    args = argv_after_separator()
    input_model = Path(args[0] if len(args) >= 1 else "/workspace/input/model.vrm")
    output_json = Path(args[1] if len(args) >= 2 else "/workspace/results/model_inspection.json")
    output_json.parent.mkdir(parents=True, exist_ok=True)

    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    if not input_model.exists():
        result = {
            "input_model": str(input_model),
            "status": "missing-input",
            "message": "Place a .vrm, .pmx, .pmd, .fbx, .glb, or .gltf file under input/ or set INPUT_MODEL.",
        }
    else:
        import_errors = try_import(input_model)
        result = inspect_scene(import_errors)
        result["input_model"] = str(input_model)
        result["status"] = "error" if import_errors else "ok"

    output_json.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
