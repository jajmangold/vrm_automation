import sys
from pathlib import Path

import bpy


def argv_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def clear_scene() -> None:
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Alpha"].default_value = color[3]
    return mat


def flat_panel(name: str, center, size, mat: bpy.types.Material) -> bpy.types.Object:
    cx, cy, cz = center
    sx, sz = (value / 2 for value in size)
    verts = [
        (cx - sx, cy, cz - sz),
        (cx + sx, cy, cz - sz),
        (cx + sx, cy, cz + sz),
        (cx - sx, cy, cz + sz),
    ]
    faces = [(0, 1, 2, 3)]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj


def main() -> None:
    args = argv_after_separator()
    output = Path(args[0] if args else "/workspace/input/outfits/sample_torso_sash.glb")
    output.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    teal = material("sample_outfit_teal", (0.0, 0.72, 0.78, 1.0))
    coral = material("sample_outfit_coral", (0.95, 0.18, 0.28, 1.0))

    flat_panel("sample_sash_panel", (0, 0, 0.08), (0.16, 0.42), teal)
    flat_panel("sample_sash_belt", (0, -0.001, -0.18), (0.26, 0.045), coral)

    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
