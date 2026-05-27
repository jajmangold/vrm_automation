from __future__ import annotations

from typing import Any

from scripts.accessory_visual_calibration import box_center, box_size, parse_box, rounded
from scripts.asset_classifier import placement_profile


BODY_SCALE_RULES = {
    "neck_chest": {"metric": "shoulder_width", "fraction": 0.16, "axis": "width"},
    "head_face": {"metric": "eye_distance", "fraction": 1.15, "axis": "width"},
    "torso_back": {"metric": "torso_height", "fraction": 0.38, "axis": "height"},
    "torso_front": {"metric": "torso_height", "fraction": 0.28, "axis": "height"},
    "unknown": {"metric": "character_height", "fraction": 0.12, "axis": "height"},
}

DEFAULT_PLACEMENT_RULE = {
    "category": "unknown",
    "scale_axis": "height",
    "target_size_ratio": 0.12,
    "vertical_center_ratio": 0.57,
    "surface_offset_ratio": 0.28,
    "target_bone_role": "spine",
    "fit_scope": "visual-review",
}

RIGHT_SIDE_VIEWS = {"right", "right45", "side", "side_right", "right_side"}
LEFT_SIDE_VIEWS = {"left", "left45", "side_left", "left_side"}
DEPTH_DELTA_SIGNS = {
    "side": -1.0,
    "right": 1.0,
    "right45": 1.0,
    "side_right": 1.0,
    "right_side": 1.0,
    "left": -1.0,
    "left45": -1.0,
    "side_left": -1.0,
    "left_side": -1.0,
}
FRONT_OFFSET_LIMITS = {
    "head_face": (-0.05, 0.36),
    "neck_chest": (-0.05, 0.5),
    "torso_front": (-0.05, 0.5),
    "torso_back": (-0.05, 0.8),
    "unknown": (-0.05, 0.5),
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_box(value: Any) -> list[float]:
    if isinstance(value, str):
        return parse_box(value)
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return parse_box(",".join(str(item) for item in value))
    raise ValueError("box must be a list of four numbers or x1,y1,x2,y2 string")


def require_keys(value: dict[str, Any], keys: tuple[str, ...], context: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValueError(f"{context} missing required field(s): {', '.join(missing)}")


def normalize_category(category: str | None) -> str:
    return (category or "unknown").strip().lower().replace("-", "_").replace(" ", "_") or "unknown"


def rule_for_category(category: str) -> dict[str, Any]:
    try:
        return placement_profile(category)
    except KeyError:
        return {**DEFAULT_PLACEMENT_RULE, "category": category}


def view_kind(view: str | None) -> str:
    cleaned = (view or "default").strip().lower().replace(" ", "_")
    if cleaned in RIGHT_SIDE_VIEWS:
        return "right-side"
    if cleaned in LEFT_SIDE_VIEWS:
        return "left-side"
    return "front"


def depth_delta_sign_for_view(view: str | None, kind: str) -> float:
    cleaned = (view or "default").strip().lower().replace(" ", "_")
    if cleaned in DEPTH_DELTA_SIGNS:
        return DEPTH_DELTA_SIGNS[cleaned]
    return -1.0 if kind == "left-side" else 1.0


def normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    require_keys(raw, ("current_box", "target_box", "character_box"), "observation")
    current_box = normalize_box(raw["current_box"])
    target_box = normalize_box(raw["target_box"])
    character_box = normalize_box(raw["character_box"])
    registration = body_frame_registration(raw)
    if registration["status"] == "registered":
        target_box = registration["registered_target_box"]
    current_center = box_center(current_box)
    target_center = box_center(target_box)
    current_size = box_size(current_box)
    target_size = box_size(target_box)
    character_size = box_size(character_box)
    view = str(raw.get("view") or "default")
    kind = view_kind(view)
    return {
        "view": view,
        "kind": kind,
        "zoom": str(raw.get("zoom") or raw.get("zoom_level") or "default"),
        "qwen_edit_id": raw.get("qwen_edit_id"),
        "current_box": current_box,
        "target_box": target_box,
        "raw_target_box": normalize_box(raw["target_box"]),
        "character_box": character_box,
        "body_registration": registration,
        "center_delta_ratio": {
            "x": (target_center[0] - current_center[0]) / max(character_size[0], 1e-6),
            "y": (target_center[1] - current_center[1]) / max(character_size[1], 1e-6),
        },
        "size_scale": {
            "width": target_size[0] / max(current_size[0], 1e-6),
            "height": target_size[1] / max(current_size[1], 1e-6),
        },
        "target_size_ratio": {
            "width": target_size[0] / max(character_size[0], 1e-6),
            "height": target_size[1] / max(character_size[1], 1e-6),
        },
        "rotation_x_delta_degrees": float(
            raw.get("rotation_x_delta_degrees", raw.get("pitch_delta_degrees", 0.0)) or 0.0
        ),
        "rotation_y_delta_degrees": float(
            raw.get("rotation_y_delta_degrees", raw.get("yaw_delta_degrees", 0.0)) or 0.0
        ),
        "rotation_delta_degrees": float(raw.get("rotation_delta_degrees", 0.0) or 0.0),
        "depth_delta_sign": (
            depth_delta_sign_for_view(view, kind)
            if raw.get("depth_delta_sign") is None
            else float(raw["depth_delta_sign"])
        ),
        "weight": float(raw.get("weight", 1.0) or 1.0),
    }


def refresh_observation_geometry(observation: dict[str, Any]) -> dict[str, Any]:
    current_center = box_center(observation["current_box"])
    target_center = box_center(observation["target_box"])
    current_size = box_size(observation["current_box"])
    target_size = box_size(observation["target_box"])
    character_size = box_size(observation["character_box"])
    observation["center_delta_ratio"] = {
        "x": (target_center[0] - current_center[0]) / max(character_size[0], 1e-6),
        "y": (target_center[1] - current_center[1]) / max(character_size[1], 1e-6),
    }
    observation["size_scale"] = {
        "width": target_size[0] / max(current_size[0], 1e-6),
        "height": target_size[1] / max(current_size[1], 1e-6),
    }
    observation["target_size_ratio"] = {
        "width": target_size[0] / max(character_size[0], 1e-6),
        "height": target_size[1] / max(character_size[1], 1e-6),
    }
    return observation


def maybe_clamp_side_target_to_body(observation: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if observation["kind"] not in {"right-side", "left-side"}:
        return observation
    if not payload.get("clamp_side_target_to_body"):
        return observation

    character_box = observation["character_box"]
    character_size = box_size(character_box)
    target_center = box_center(observation["target_box"])
    target_size = box_size(observation["target_box"])
    limits = payload.get("side_target_center_ratio_limits") or [-0.05, 0.9]
    if len(limits) != 2:
        raise ValueError("side_target_center_ratio_limits must contain [min, max]")
    min_ratio = float(limits[0])
    max_ratio = float(limits[1])
    current_ratio_x = (target_center[0] - character_box[0]) / max(character_size[0], 1e-6)
    clamped_ratio_x = clamp(current_ratio_x, min_ratio, max_ratio)
    if abs(clamped_ratio_x - current_ratio_x) < 1e-6:
        return observation

    clamped_center_x = character_box[0] + (character_size[0] * clamped_ratio_x)
    half_width = target_size[0] / 2.0
    observation = dict(observation)
    observation["target_box"] = [
        clamped_center_x - half_width,
        observation["target_box"][1],
        clamped_center_x + half_width,
        observation["target_box"][3],
    ]
    observation["body_clamp"] = {
        "status": "clamped",
        "axis": "x",
        "source_center_ratio": rounded(current_ratio_x),
        "clamped_center_ratio": rounded(clamped_ratio_x),
        "limits": [rounded(min_ratio), rounded(max_ratio)],
    }
    return refresh_observation_geometry(observation)


def body_frame_registration(raw: dict[str, Any]) -> dict[str, Any]:
    current_body_raw = raw.get("current_body_box") or raw.get("source_body_box") or raw.get("current_reference_box")
    target_body_raw = raw.get("target_body_box") or raw.get("qwen_body_box") or raw.get("target_reference_box")
    if not current_body_raw or not target_body_raw:
        return {"status": "not-provided"}

    current_body = normalize_box(current_body_raw)
    target_body = normalize_box(target_body_raw)
    target_box = normalize_box(raw["target_box"])
    current_body_size = box_size(current_body)
    target_body_size = box_size(target_body)
    scale_x = current_body_size[0] / max(target_body_size[0], 1e-6)
    scale_y = current_body_size[1] / max(target_body_size[1], 1e-6)

    def map_x(value: float) -> float:
        return current_body[0] + ((value - target_body[0]) * scale_x)

    def map_y(value: float) -> float:
        return current_body[1] + ((value - target_body[1]) * scale_y)

    registered = [map_x(target_box[0]), map_y(target_box[1]), map_x(target_box[2]), map_y(target_box[3])]
    aspect_change = abs(scale_x - scale_y) / max((scale_x + scale_y) / 2, 1e-6)
    return {
        "status": "registered",
        "current_body_box": current_body,
        "target_body_box": target_body,
        "registered_target_box": [rounded(value) for value in registered],
        "scale": {"x": rounded(scale_x), "y": rounded(scale_y)},
        "aspect_change_ratio": rounded(aspect_change),
    }


def observation_rejection_reason(observation: dict[str, Any], payload: dict[str, Any]) -> str | None:
    registration = observation.get("body_registration") or {}
    if payload.get("require_body_registration") and registration.get("status") != "registered":
        return "missing-body-registration"
    if registration.get("status") == "registered":
        max_aspect_change = float(payload.get("max_body_registration_aspect_change", 0.28))
        if float(registration.get("aspect_change_ratio", 0.0)) > max_aspect_change:
            return "body-registration-aspect-change"

    size_scale = observation["size_scale"]
    max_scale = float(payload.get("max_observation_size_scale", 5.0))
    min_scale = float(payload.get("min_observation_size_scale", 0.2))
    if not (min_scale <= size_scale["width"] <= max_scale and min_scale <= size_scale["height"] <= max_scale):
        return "object-scale-outlier"

    max_center_delta = float(payload.get("max_observation_center_delta_ratio", 0.65))
    center_delta = observation["center_delta_ratio"]
    if abs(center_delta["x"]) > max_center_delta or abs(center_delta["y"]) > max_center_delta:
        return "object-center-outlier"
    target_center = box_center(observation["target_box"])
    character_box = observation["character_box"]
    character_size = box_size(character_box)
    target_center_ratio = {
        "x": (target_center[0] - character_box[0]) / max(character_size[0], 1e-6),
        "y": (target_center[1] - character_box[1]) / max(character_size[1], 1e-6),
    }
    if observation["kind"] in {"right-side", "left-side"}:
        margin = float(payload.get("max_side_target_center_outside_ratio", 0.25))
        if not (-margin <= target_center_ratio["x"] <= 1.0 + margin):
            return "side-target-off-body"
        if not (-margin <= target_center_ratio["y"] <= 1.0 + margin):
            return "side-target-off-body"
    return None


def accepted_observations(raw_observations: list[dict[str, Any]], payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations = [maybe_clamp_side_target_to_body(normalize_observation(item), payload) for item in raw_observations]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for observation in observations:
        reason = observation_rejection_reason(observation, payload)
        if reason:
            rejected.append(
                {
                    "view": observation["view"],
                    "zoom": observation["zoom"],
                    "qwen_edit_id": observation.get("qwen_edit_id"),
                    "reason": reason,
                    "body_registration": observation.get("body_registration"),
                    "body_clamp": observation.get("body_clamp"),
                    "raw_target_box": observation.get("raw_target_box"),
                    "registered_target_box": observation.get("target_box"),
                }
            )
        else:
            accepted.append(observation)
    return accepted, rejected


def weighted_average(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _value, weight in values)
    if total_weight <= 0:
        raise ValueError("at least one observation weight must be positive")
    return sum(value * weight for value, weight in values) / total_weight


def scale_rule_for_payload(category: str, payload: dict[str, Any]) -> dict[str, Any]:
    custom_rule = payload.get("scale_rule")
    if custom_rule:
        rule = dict(custom_rule)
        require_keys(rule, ("metric",), "scale_rule")
        rule.setdefault("axis", rule.get("scale_axis", "height"))
        rule.setdefault("fraction", 1.0)
        if rule["axis"] not in {"width", "height"}:
            raise ValueError("scale_rule axis must be width or height")
        if float(rule["fraction"]) <= 0:
            raise ValueError("scale_rule fraction must be positive")
        return rule
    return dict(BODY_SCALE_RULES.get(category, BODY_SCALE_RULES["unknown"]))


def front_offset_limits(category: str, payload: dict[str, Any], profile: dict[str, Any]) -> tuple[float, float]:
    if payload.get("front_offset_limits"):
        limits = list(payload["front_offset_limits"])
        if len(limits) != 2:
            raise ValueError("front_offset_limits must contain [min, max]")
        return float(limits[0]), float(limits[1])
    default_min, default_max = FRONT_OFFSET_LIMITS.get(category, FRONT_OFFSET_LIMITS["unknown"])
    return (
        float(profile.get("min_front_offset_ratio", default_min)),
        float(profile.get("max_front_offset_ratio", default_max)),
    )


def body_relative_size_ratio(
    category: str,
    payload: dict[str, Any],
    body_metrics: dict[str, Any],
    character_box: list[float],
) -> tuple[float | None, dict[str, Any]]:
    rule = scale_rule_for_payload(category, payload)
    metric = rule["metric"]
    if metric not in body_metrics:
        return None, {"rule": rule, "status": "missing-body-metric"}
    character_size = box_size(character_box)
    denominator = character_size[0] if rule["axis"] == "width" else character_size[1]
    ratio = (float(body_metrics[metric]) * float(rule["fraction"])) / max(denominator, 1e-6)
    return ratio, {"rule": rule, "status": "ok"}


def placement_requirements(category: str, payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, bool]:
    requirements = {
        "front": True,
        "side": category in {"torso_back"} or bool(profile.get("require_depth")),
        "body_scale": bool(profile.get("require_body_scale")),
        "rotation": bool(profile.get("require_rotation")),
    }
    requirements.update({key: bool(value) for key, value in dict(payload.get("requirements") or {}).items()})
    return requirements


def placement_quality(requirements: dict[str, bool], evidence: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    blocking = []
    if requirements.get("front") and int(evidence["front_view_count"]) <= 0:
        blocking.append("missing-front-view")
    if requirements.get("side") and int(evidence["side_view_count"]) <= 0:
        blocking.append("missing-side-view")
    if requirements.get("body_scale") and not evidence["body_scale"]:
        blocking.append("missing-body-scale")
    if requirements.get("rotation") and not evidence["rotation"]:
        blocking.append("missing-rotation")
    return {
        "status": "solved" if not blocking else "review",
        "blocking": blocking,
        "warnings": warnings,
    }


def solve_placement(payload: dict[str, Any]) -> dict[str, Any]:
    observations, rejected_observations = accepted_observations(list(payload.get("observations", [])), payload)
    if not observations:
        raise ValueError("observations must contain at least one accepted current/target/character box set")

    category = normalize_category(payload.get("category"))
    profile = {**rule_for_category(category), **dict(payload.get("placement_rule") or {})}
    current_overrides = dict(payload.get("current_overrides") or {})
    center_gain = float(payload.get("center_correction_gain", 1.0))
    size_gain = float(payload.get("size_correction_gain", 1.0))
    depth_gain = float(payload.get("depth_correction_gain", center_gain))
    rotation_gain = float(payload.get("rotation_correction_gain", 1.0))
    rotation_x_gain = float(payload.get("rotation_x_correction_gain", rotation_gain))
    rotation_y_gain = float(payload.get("rotation_y_correction_gain", rotation_gain))
    rotation_z_gain = float(payload.get("rotation_z_correction_gain", rotation_gain))
    warnings = []

    primary = observations[0]
    front_observations = [item for item in observations if item["kind"] == "front"] or [primary]
    side_observations = [item for item in observations if item["kind"] in {"right-side", "left-side"}]
    scale_axis = str(current_overrides.get("scale_axis") or profile.get("scale_axis") or "height")
    if scale_axis not in {"width", "height"}:
        raise ValueError("scale_axis must be width or height")

    current_size_ratio = float(current_overrides.get("target_size_ratio", profile["target_size_ratio"]))
    scale_observations = front_observations
    image_scale = weighted_average([(item["size_scale"][scale_axis], item["weight"]) for item in scale_observations])
    image_size_ratio = current_size_ratio * (1.0 + ((image_scale - 1.0) * size_gain))

    body_size_ratio, body_scale = body_relative_size_ratio(
        category,
        payload,
        dict(payload.get("body_metrics") or {}),
        primary["character_box"],
    )
    if body_size_ratio is None:
        solved_size_ratio = image_size_ratio
        scale_source = "image-observations"
    else:
        blend = float(payload.get("body_scale_weight", 0.55))
        solved_size_ratio = (body_size_ratio * blend) + (image_size_ratio * (1.0 - blend))
        scale_source = "body-metrics+image-observations"

    front_dx = weighted_average([(item["center_delta_ratio"]["x"], item["weight"]) for item in front_observations])
    front_dy = weighted_average([(item["center_delta_ratio"]["y"], item["weight"]) for item in front_observations])

    solved_overrides = {
        **current_overrides,
        "scale_axis": scale_axis,
        "target_size_ratio": rounded(clamp(solved_size_ratio, 0.01, 0.6)),
        "vertical_center_ratio": rounded(
            clamp(
                float(current_overrides.get("vertical_center_ratio", profile["vertical_center_ratio"]))
                - (front_dy * center_gain),
                0.0,
                1.1,
            )
        ),
    }

    horizontal = float(current_overrides.get("horizontal_center_offset_ratio", 0.0)) + (front_dx * center_gain)
    if abs(horizontal) >= 0.005 or "horizontal_center_offset_ratio" in current_overrides:
        solved_overrides["horizontal_center_offset_ratio"] = rounded(clamp(horizontal, -0.5, 0.5))

    depth_delta = 0.0
    depth_unclamped = None
    if side_observations:
        signed_depth = []
        for item in side_observations:
            sign = item.get("depth_delta_sign")
            if sign is None:
                sign = -1.0 if item["kind"] == "left-side" else 1.0
            signed_depth.append((item["center_delta_ratio"]["x"] * sign, item["weight"]))
        depth_delta = weighted_average(signed_depth) * depth_gain
        base_front_offset = float(
            current_overrides.get("front_offset_ratio", profile.get("surface_offset_ratio", 0.0))
        )
        depth_unclamped = base_front_offset + depth_delta
        min_front_offset, max_front_offset = front_offset_limits(category, payload, profile)
        solved_front_offset = clamp(depth_unclamped, min_front_offset, max_front_offset)
        solved_overrides["front_offset_ratio"] = rounded(solved_front_offset)
        if abs(solved_front_offset - depth_unclamped) > 1e-6:
            warnings.append(f"depth:front-offset-clamped:{rounded(solved_front_offset)}")

    rotation_x_delta = weighted_average([(item["rotation_x_delta_degrees"], item["weight"]) for item in observations])
    rotation_y_delta = weighted_average([(item["rotation_y_delta_degrees"], item["weight"]) for item in observations])
    rotation_delta = weighted_average([(item["rotation_delta_degrees"], item["weight"]) for item in observations])
    rotation_x = float(current_overrides.get("rotation_x_degrees", 0.0)) + (rotation_x_delta * rotation_x_gain)
    rotation_y = float(current_overrides.get("rotation_y_degrees", 0.0)) + (rotation_y_delta * rotation_y_gain)
    rotation_z = float(current_overrides.get("rotation_z_degrees", 0.0)) + (rotation_delta * rotation_z_gain)
    if abs(rotation_x) >= 0.001 or "rotation_x_degrees" in current_overrides:
        solved_overrides["rotation_x_degrees"] = rounded(rotation_x)
    if abs(rotation_y) >= 0.001 or "rotation_y_degrees" in current_overrides:
        solved_overrides["rotation_y_degrees"] = rounded(rotation_y)
    if abs(rotation_z) >= 0.001 or "rotation_z_degrees" in current_overrides:
        solved_overrides["rotation_z_degrees"] = rounded(rotation_z)

    anchor_offset = list(current_overrides.get("anchor_offset") or [0.0, 0.0, 0.0])
    while len(anchor_offset) < 3:
        anchor_offset.append(0.0)
    anchor_offset[0] = rounded(float(anchor_offset[0]) + (front_dx * center_gain))
    anchor_offset[1] = rounded(float(anchor_offset[1]) + depth_delta)
    anchor_offset[2] = rounded(float(anchor_offset[2]) - (front_dy * center_gain))

    evidence = {
        "observation_count": len(observations),
        "front_view_count": len(front_observations),
        "side_view_count": len(side_observations),
        "scale_view_count": len(scale_observations),
        "body_scale": body_scale["status"] == "ok",
        "rotation": (
            abs(rotation_x_delta) > 1e-6
            or abs(rotation_y_delta) > 1e-6
            or abs(rotation_delta) > 1e-6
            or "rotation_x_degrees" in current_overrides
            or "rotation_y_degrees" in current_overrides
            or "rotation_z_degrees" in current_overrides
        ),
    }
    requirements = placement_requirements(category, payload, profile)
    if body_scale["status"] != "ok":
        warnings.append(f"scale:{body_scale['status']}:{body_scale['rule'].get('metric')}")
    if category not in BODY_SCALE_RULES and not payload.get("scale_rule"):
        warnings.append(f"category-defaulted:{category}")
    if not side_observations:
        warnings.append("depth:not-observed")
    if not evidence["rotation"]:
        warnings.append("rotation:not-observed")

    return {
        "status": "ok",
        "solver": "body-relative-multiview-v1",
        "asset_key": payload.get("asset_key"),
        "category": category,
        "anchor": payload.get("anchor_name") or profile.get("anchor") or f"{category}:{profile.get('fit_scope', 'visual-review')}",
        "fit_overrides": solved_overrides,
        "placement_transform": {
            "translation_ratio": {
                "x": anchor_offset[0],
                "y_depth": anchor_offset[1],
                "z": anchor_offset[2],
            },
            "rotation_degrees": {
                "pitch": solved_overrides.get("rotation_x_degrees", 0.0),
                "yaw": solved_overrides.get("rotation_y_degrees", 0.0),
                "roll": solved_overrides.get("rotation_z_degrees", 0.0),
            },
            "scale": {
                "axis": scale_axis,
                "target_size_ratio": solved_overrides["target_size_ratio"],
                "source": scale_source,
                "body_metric_ratio": None if body_size_ratio is None else rounded(body_size_ratio),
                "image_scale": rounded(image_scale),
            },
            "bone": profile.get("target_bone_role", "spine"),
        },
        "observations": observations,
        "diagnostics": {
            "body_scale": body_scale,
            "placement_rule": profile,
            "requirements": requirements,
            "evidence": evidence,
            "quality": placement_quality(requirements, evidence, warnings),
            "front_delta_ratio": {"x": rounded(front_dx), "y": rounded(front_dy)},
            "depth_delta_ratio": rounded(depth_delta),
            "depth_unclamped_front_offset_ratio": None if depth_unclamped is None else rounded(depth_unclamped),
            "rotation_x_delta_degrees": rounded(rotation_x_delta),
            "rotation_y_delta_degrees": rounded(rotation_y_delta),
            "rotation_delta_degrees": rounded(rotation_delta),
            "warnings": warnings,
            "rejected_observations": rejected_observations,
            "accepted_observation_count": len(observations),
            "limitations": [
                "rotation requires explicit rotation_delta_degrees observations; "
                "axis-aligned boxes do not infer it",
                "depth is estimated from side-view horizontal target drift and should be validated by rerendering",
            ],
        },
    }
