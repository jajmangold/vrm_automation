from __future__ import annotations


def _axis(bounds: dict, field: str, index: int) -> float:
    return float(bounds[field][index])


def ratio(value: float, denominator: float) -> float:
    return round(value / denominator, 4) if denominator else 0.0


def thresholds_for_scope(scope: str) -> dict:
    if scope == "headwear":
        return {
            "width_min": 0.08,
            "width_max": 0.65,
            "height_min": 0.035,
            "height_max": 0.28,
            "depth_max": 1.05,
            "lateral_max": 0.24,
            "vertical_min": 0.78,
            "vertical_max": 1.08,
            "floating_max": 0.28,
            "buried_max": 0.55,
        }
    if scope == "head-face":
        return {
            "width_min": 0.08,
            "width_max": 0.55,
            "height_min": 0.015,
            "height_max": 0.22,
            "depth_max": 0.75,
            "lateral_max": 0.24,
            "vertical_min": 0.68,
            "vertical_max": 0.95,
            "floating_max": 0.25,
            "buried_max": 0.18,
        }
    if scope == "neck-chest":
        return {
            "width_min": 0.025,
            "width_max": 0.45,
            "height_min": 0.02,
            "height_max": 0.32,
            "depth_max": 0.50,
            "lateral_max": 0.18,
            "vertical_min": 0.58,
            "vertical_max": 0.86,
            "floating_max": 0.18,
            "buried_max": 0.12,
        }
    return {
        "width_min": 0.025,
        "width_max": 0.65,
        "height_min": 0.035,
        "height_max": 0.55,
        "depth_max": 0.45,
        "lateral_max": 0.18,
        "vertical_min": 0.28,
        "vertical_max": 0.78,
        "floating_max": 0.18,
        "buried_max": 0.08,
    }


def outfit_fit_check(character_bounds: dict, outfit_bounds: dict, scope: str = "torso", surface: str = "front") -> dict:
    char_min_y = _axis(character_bounds, "min", 1)
    char_max_y = _axis(character_bounds, "max", 1)
    char_min_z = _axis(character_bounds, "min", 2)
    char_max_z = _axis(character_bounds, "max", 2)
    char_center_x = _axis(character_bounds, "center", 0)
    char_center_y = _axis(character_bounds, "center", 1)
    char_size_x = _axis(character_bounds, "size", 0)
    char_size_y = _axis(character_bounds, "size", 1)
    char_size_z = _axis(character_bounds, "size", 2)

    outfit_min_y = _axis(outfit_bounds, "min", 1)
    outfit_min_z = _axis(outfit_bounds, "min", 2)
    outfit_max_y = _axis(outfit_bounds, "max", 1)
    outfit_max_z = _axis(outfit_bounds, "max", 2)
    outfit_center_x = _axis(outfit_bounds, "center", 0)
    outfit_center_y = _axis(outfit_bounds, "center", 1)
    outfit_center_z = _axis(outfit_bounds, "center", 2)
    outfit_size_x = _axis(outfit_bounds, "size", 0)
    outfit_size_y = _axis(outfit_bounds, "size", 1)
    outfit_size_z = _axis(outfit_bounds, "size", 2)

    width_ratio = ratio(outfit_size_x, char_size_x)
    height_ratio = ratio(outfit_size_z, char_size_z)
    depth_ratio = ratio(outfit_size_y, char_size_y)
    lateral_offset_ratio = ratio(abs(outfit_center_x - char_center_x), char_size_x)
    vertical_center_ratio = ratio(outfit_center_z - char_min_z, char_size_z)
    front_surface_gap_ratio = ratio(char_min_y - outfit_min_y, char_size_y)
    back_surface_gap_ratio = ratio(outfit_max_y - char_max_y, char_size_y)
    surface_name = "back" if surface == "back" else "front"
    if surface_name == "back":
        surface_gap_ratio = back_surface_gap_ratio
        buried_depth_ratio = ratio(max(char_center_y - outfit_min_y, 0.0), char_size_y)
    else:
        surface_gap_ratio = front_surface_gap_ratio
        buried_depth_ratio = ratio(max(outfit_max_y - char_center_y, 0.0), char_size_y)
    surface_penetration_ratio = max(-surface_gap_ratio, 0.0)

    thresholds = thresholds_for_scope(scope)
    warnings = []
    if width_ratio < thresholds["width_min"]:
        warnings.append("outfit-width-very-small")
    elif width_ratio > thresholds["width_max"]:
        warnings.append("outfit-width-large")
    if height_ratio < thresholds["height_min"]:
        warnings.append("outfit-height-very-small")
    elif height_ratio > thresholds["height_max"]:
        warnings.append("outfit-height-large")
    if depth_ratio > thresholds["depth_max"]:
        warnings.append("outfit-depth-large")
    if lateral_offset_ratio > thresholds["lateral_max"]:
        warnings.append("outfit-lateral-offset")
    if vertical_center_ratio < thresholds["vertical_min"]:
        warnings.append("outfit-too-low")
    elif vertical_center_ratio > thresholds["vertical_max"]:
        warnings.append("outfit-too-high")
    if surface_gap_ratio > thresholds["floating_max"]:
        warnings.append("outfit-floating-backward" if surface_name == "back" else "outfit-floating-forward")
    if surface_penetration_ratio > thresholds["buried_max"] and depth_ratio > 0.08:
        warnings.append("outfit-surface-penetration")
    if buried_depth_ratio > thresholds["buried_max"]:
        warnings.append("outfit-buried-deep")
    if outfit_max_z < char_min_z or outfit_min_z > char_max_z:
        warnings.append("outfit-outside-character-height")

    depth_zone = "back-surface" if surface_name == "back" else "front-surface"
    if surface_gap_ratio > thresholds["floating_max"]:
        depth_zone = "floating-backward" if surface_name == "back" else "floating-forward"
    elif buried_depth_ratio > thresholds["buried_max"]:
        depth_zone = "buried-deep"
    elif surface_penetration_ratio > thresholds["buried_max"] and depth_ratio > 0.08:
        depth_zone = "surface-penetration"
    elif surface_name == "front" and outfit_center_y > char_center_y:
        depth_zone = "inside-back-half"

    return {
        "status": "review" if warnings else "ok",
        "scope": scope,
        "warnings": warnings,
        "metrics": {
            "width_ratio": width_ratio,
            "height_ratio": height_ratio,
            "depth_ratio": depth_ratio,
            "lateral_offset_ratio": lateral_offset_ratio,
            "vertical_center_ratio": vertical_center_ratio,
            "surface": surface_name,
            "surface_gap_ratio": surface_gap_ratio,
            "surface_penetration_ratio": surface_penetration_ratio,
            "front_surface_gap_ratio": front_surface_gap_ratio,
            "back_surface_gap_ratio": back_surface_gap_ratio,
            "buried_depth_ratio": buried_depth_ratio,
            "depth_zone": depth_zone,
        },
        "threshold_note": "coarse-bounds-check; visual PNG QA remains required",
    }
