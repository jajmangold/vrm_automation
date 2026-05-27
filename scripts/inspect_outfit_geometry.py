#!/usr/bin/env python3
"""Inspect imported outfit geometry in Blender."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def rounded(value: float) -> float:
    return round(float(value), 4)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    if not args:
        raise SystemExit("usage: blender --background --python scripts/inspect_outfit_geometry.py -- <glb> [out.json]")

    source = Path(args[0])
    output = Path(args[1]) if len(args) > 1 else None
    bpy.ops.import_scene.gltf(filepath=str(source))

    report: dict[str, object] = {"source": str(source), "objects": []}
    objects: list[dict[str, object]] = []
    for obj in sorted((o for o in bpy.context.scene.objects if o.type == "MESH"), key=lambda item: item.name):
        world_vertices = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        if not world_vertices:
            continue
        z_values = [vertex.z for vertex in world_vertices]
        z_min = min(z_values)
        z_max = max(z_values)
        bands: list[dict[str, object]] = []
        for band_index in range(12):
            low = z_min + (z_max - z_min) * band_index / 12
            high = z_min + (z_max - z_min) * (band_index + 1) / 12
            band_vertices = [vertex for vertex in world_vertices if low <= vertex.z <= high]
            if not band_vertices:
                continue
            bands.append(
                {
                    "band": band_index,
                    "z_range": [rounded(low), rounded(high)],
                    "vertex_count": len(band_vertices),
                    "x_range": [rounded(min(vertex.x for vertex in band_vertices)), rounded(max(vertex.x for vertex in band_vertices))],
                    "x_size": rounded(max(vertex.x for vertex in band_vertices) - min(vertex.x for vertex in band_vertices)),
                    "y_size": rounded(max(vertex.y for vertex in band_vertices) - min(vertex.y for vertex in band_vertices)),
                }
            )
        material_faces: dict[str, int] = {}
        for polygon in obj.data.polygons:
            material = obj.material_slots[polygon.material_index].material if polygon.material_index < len(obj.material_slots) else None
            name = material.name if material else "none"
            material_faces[name] = material_faces.get(name, 0) + 1
        objects.append(
            {
                "name": obj.name,
                "vertices": len(obj.data.vertices),
                "faces": len(obj.data.polygons),
                "materials": material_faces,
                "bounds": {
                    "x_size": rounded(max(vertex.x for vertex in world_vertices) - min(vertex.x for vertex in world_vertices)),
                    "y_size": rounded(max(vertex.y for vertex in world_vertices) - min(vertex.y for vertex in world_vertices)),
                    "z_size": rounded(z_max - z_min),
                },
                "z_bands": bands,
            }
        )
    report["objects"] = objects
    text = json.dumps(report, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
