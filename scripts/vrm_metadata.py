from __future__ import annotations

import json
import struct
from pathlib import Path


GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A


def load_glb_json(path: Path | str) -> dict:
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError(f"{path} is too small to be a GLB/VRM file")
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise ValueError(f"{path} does not start with GLB magic")
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != JSON_CHUNK:
        raise ValueError(f"{path} first GLB chunk is not JSON")
    return json.loads(data[20 : 20 + chunk_length].decode("utf-8"))


def summarize_vrm_document(document: dict) -> dict:
    extensions = document.get("extensions", {})
    extensions_used = document.get("extensionsUsed", [])
    vrm0 = extensions.get("VRM") or {}
    vrm1 = extensions.get("VRMC_vrm") or {}
    spring1 = extensions.get("VRMC_springBone") or {}
    vrm_extension = "VRMC_vrm" if vrm1 else ("VRM" if vrm0 else None)
    vrm = vrm1 or vrm0

    humanoid = vrm.get("humanoid", {})
    human_bones = humanoid.get("humanBones", {})
    humanoid_bone_count = len(human_bones) if isinstance(human_bones, dict) else len(human_bones or [])

    blend_shape_master = vrm.get("blendShapeMaster", {})
    blend_shape_groups = blend_shape_master.get("blendShapeGroups", [])
    expressions = vrm.get("expressions", {})
    preset_expressions = expressions.get("preset", {})
    custom_expressions = expressions.get("custom", {})
    expression_count = len(blend_shape_groups or []) + len(preset_expressions or {}) + len(custom_expressions or {})

    secondary = vrm.get("secondaryAnimation", {})
    spring_groups = spring1.get("springs", secondary.get("boneGroups", []))
    collider_groups = spring1.get("colliderGroups", secondary.get("colliderGroups", []))
    colliders = spring1.get("colliders", [])
    material_properties = vrm.get("materialProperties", [])

    return {
        "vrm_extension": vrm_extension,
        "spring_extension": "VRMC_springBone" if spring1 else ("VRM.secondaryAnimation" if secondary else None),
        "spec_version": vrm.get("specVersion"),
        "extensions_used": sorted(extensions_used),
        "root_extensions": sorted(extensions),
        "humanoid_bone_count": humanoid_bone_count,
        "expression_count": expression_count,
        "material_property_count": len(material_properties or []),
        "spring_bone_group_count": len(spring_groups or []),
        "collider_count": len(colliders or []),
        "collider_group_count": len(collider_groups or []),
        "has_meta": bool(vrm.get("meta")),
    }


def summarize_vrm_file(path: Path | str) -> dict:
    return summarize_vrm_document(load_glb_json(path))


def compare_vrm_summaries(before: dict, after: dict) -> dict:
    warnings = []
    checks = {
        "humanoid_bone_count": "humanoid-bones-decreased",
        "expression_count": "expressions-decreased",
        "material_property_count": "material-properties-decreased",
        "spring_bone_group_count": "spring-groups-decreased",
        "collider_group_count": "collider-groups-decreased",
        "collider_count": "colliders-decreased",
    }
    for key, warning in checks.items():
        before_count = before.get(key) or 0
        after_count = after.get(key) or 0
        if after_count < before_count:
            warnings.append(warning)
    if before.get("vrm_extension") and before.get("vrm_extension") != after.get("vrm_extension"):
        warnings.append("vrm-extension-changed")
    if before.get("spring_extension") and before.get("spring_extension") != after.get("spring_extension"):
        warnings.append("spring-extension-changed")
    if before.get("has_meta") and not after.get("has_meta"):
        warnings.append("meta-missing")

    return {
        "status": "review" if warnings else "ok",
        "warnings": warnings,
        "before": before,
        "after": after,
    }
