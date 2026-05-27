from __future__ import annotations


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    cleaned = {name: max(0.0, float(value)) for name, value in weights.items() if name}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {name: round(value / total, 4) for name, value in cleaned.items() if value > 0}


def _height_ratio(world_z: float, character_bounds: dict) -> float:
    min_z = float(character_bounds["min"][2])
    size_z = float(character_bounds["size"][2])
    if size_z <= 0:
        return 0.5
    return max(0.0, min(1.0, (float(world_z) - min_z) / size_z))


def torso_weight_plan(world_z: float, character_bounds: dict, bones: dict[str, str | None]) -> dict[str, float]:
    hips = bones.get("hips")
    spine = bones.get("spine")
    chest = bones.get("chest")
    if not spine:
        return {}
    if not hips and not chest:
        return {spine: 1.0}

    z_ratio = _height_ratio(world_z, character_bounds)
    if z_ratio < 0.52:
        low_blend = max(0.0, min(1.0, (z_ratio - 0.38) / 0.14))
        return _normalize({hips or spine: 1.0 - low_blend, spine: 0.55 + low_blend * 0.45})
    if z_ratio > 0.62:
        high_blend = max(0.0, min(1.0, (z_ratio - 0.62) / 0.14))
        return _normalize({spine: 0.75 - high_blend * 0.35, chest or spine: 0.25 + high_blend * 0.75})
    return _normalize({hips or spine: 0.18, spine: 0.64, chest or spine: 0.18})
