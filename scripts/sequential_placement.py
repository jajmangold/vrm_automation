from __future__ import annotations

from typing import Any

from scripts.placement_solver import solve_placement, view_kind


DEFAULT_VIEW_SEQUENCE = ("front", "side", "three_quarter", "portrait")
FRONT_MERGE_FIELDS = {
    "scale_axis",
    "target_size_ratio",
    "vertical_center_ratio",
    "horizontal_center_offset_ratio",
    "rotation_z_degrees",
}
SIDE_MERGE_FIELDS = {
    "front_offset_ratio",
    "rotation_x_degrees",
    "rotation_y_degrees",
}


def parse_view_sequence(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return list(DEFAULT_VIEW_SEQUENCE)
    if isinstance(value, str):
        views = [item.strip() for item in value.split(",") if item.strip()]
    else:
        views = [str(item).strip() for item in value if str(item).strip()]
    if not views:
        raise ValueError("view sequence must contain at least one view")
    return views


def initial_sequential_state(payload: dict[str, Any]) -> dict[str, Any]:
    views = parse_view_sequence(payload.get("view_sequence") or payload.get("render_angles"))
    return {
        "asset_key": payload.get("asset_key"),
        "category": payload.get("category", "unknown"),
        "anchor_name": payload.get("anchor_name"),
        "view_sequence": views,
        "step_index": 0,
        "current_overrides": dict(payload.get("current_overrides") or {}),
        "observations": list(payload.get("observations") or []),
        "iterations": [],
        "complete": False,
    }


def next_render_request(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("complete"):
        return None
    index = int(state.get("step_index", 0))
    views = list(state.get("view_sequence") or DEFAULT_VIEW_SEQUENCE)
    if index >= len(views):
        return None
    return {
        "view": views[index],
        "step_index": index,
        "current_overrides": dict(state.get("current_overrides") or {}),
        "requires_fresh_render": True,
        "reason": "render-this-view-after-applying-previous-solve",
    }


def merge_fields_for_view(view: str | None) -> set[str]:
    if view_kind(view) in {"right-side", "left-side"}:
        return SIDE_MERGE_FIELDS
    return FRONT_MERGE_FIELDS


def apply_sequential_observation(state: dict[str, Any], observation: dict[str, Any], **solve_options: Any) -> dict[str, Any]:
    observations = [*list(state.get("observations") or []), dict(observation)]
    result = solve_placement(
        {
            **solve_options,
            "asset_key": state.get("asset_key"),
            "category": state.get("category", "unknown"),
            "anchor_name": state.get("anchor_name"),
            "current_overrides": dict(state.get("current_overrides") or {}),
            "observations": [dict(observation)],
        }
    )
    merged_overrides = dict(state.get("current_overrides") or {})
    for key in merge_fields_for_view(observation.get("view")):
        if key in result["fit_overrides"]:
            merged_overrides[key] = result["fit_overrides"][key]
    next_index = int(state.get("step_index", 0)) + 1
    views = list(state.get("view_sequence") or DEFAULT_VIEW_SEQUENCE)
    return {
        **state,
        "step_index": next_index,
        "current_overrides": merged_overrides,
        "observations": observations,
        "iterations": [
            *list(state.get("iterations") or []),
            {
                "step_index": int(state.get("step_index", 0)),
                "view": observation.get("view"),
                "solver": result,
            },
        ],
        "complete": next_index >= len(views),
    }
