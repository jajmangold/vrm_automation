from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.accessory_visual_calibration import (
    DEFAULT_QWEN_WORKFLOW_SEARCH_ROOTS,
    anchor_name_for_category,
    asset_catalog_key,
    calibrated_fit_overrides,
    find_asset,
    parse_box,
    qwen_workflow_search_roots,
    resolve_qwen_workflow_path,
)
from scripts.make_person_manifest import asset_quality, asset_quality_notes
from scripts.placement_methods import (
    CANONICAL_PLACEMENT_METHOD,
    canonical_placement_note,
    is_canonical_anchor_calibration,
)
from scripts.placement_solver import solve_placement


ROOT = Path(__file__).resolve().parents[1]
ASSET_CONFIG_PATH = ROOT / "config" / "poly_pizza_assets.json"

PLACEMENT_PROFILES = {
    "rough": {
        "description": "Single-view, low-cost Qwen/SAM calibration target for fast override discovery.",
        "render_angles": "portrait",
        "render_pose_frames": "9",
        "render_width": "512",
        "render_height": "768",
        "minimum_views": 1,
        "center_correction_gain": 0.42,
        "size_correction_gain": 1.0,
        "qwen_run": True,
        "qwen_denoise": 0.72,
        "qwen_steps": 3,
        "qwen_megapixels": 0.25,
        "qwen_timeout_seconds": 360,
        "sam_box_mode": "sam-red-fallback",
    },
    "promote": {
        "description": "Multi-view validation profile before moving an accessory into the ship pool.",
        "render_angles": "front,portrait",
        "render_pose_frames": "9,16",
        "render_width": "640",
        "render_height": "960",
        "minimum_views": 2,
        "center_correction_gain": 0.42,
        "size_correction_gain": 1.0,
        "qwen_run": True,
        "qwen_denoise": 0.74,
        "qwen_steps": 4,
        "qwen_megapixels": 0.35,
        "qwen_timeout_seconds": 600,
        "sam_box_mode": "sam-red-fallback",
    },
    "multiview": {
        "description": "Canonical sequential Qwen/SAM solve with Blender silhouette pose optimization.",
        "render_angles": "front,side,three_quarter,portrait",
        "view_sequence": "front,side,three_quarter,portrait",
        "sequential_multiview": True,
        "render_pose_frames": "9,16",
        "render_width": "768",
        "render_height": "1152",
        "zoom_levels": "full,anchor,tight",
        "minimum_views": 3,
        "require_body_registration": True,
        "max_body_registration_aspect_change": 0.28,
        "center_correction_gain": 0.42,
        "size_correction_gain": 1.0,
        "qwen_run": True,
        "qwen_denoise": 0.74,
        "qwen_steps": 8,
        "qwen_megapixels": 0.75,
        "qwen_timeout_seconds": 900,
        "sam_box_mode": "sam-red-fallback",
        "pose_optimizer": "blender-silhouette-cma",
        "pose_parameters": ["x", "y", "z", "rot_x", "rot_y", "rot_z", "scale"],
        "mask_scoring": ["iou", "centroid-distance", "bbox-size-error", "collision", "floating", "offscreen", "depth"],
    },
}


def load_asset_config(config_path: Path = ASSET_CONFIG_PATH) -> dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def asset_key(asset: dict[str, Any]) -> str:
    return asset_catalog_key(str(asset.get("id", "")))


def placement_status_for_asset(asset: dict[str, Any]) -> dict[str, Any]:
    quality = asset_quality(asset)
    anchor_calibration = asset.get("anchor_calibration") or {}
    validation = anchor_calibration.get("validation") or {}
    fit_overrides = asset.get("fit_overrides") or {}
    canonical = is_canonical_anchor_calibration(anchor_calibration)
    needs_calibration = (
        quality != "ship"
        or validation.get("status") not in {"ok", "ship"}
        or not fit_overrides
        or not canonical
    )
    return {
        "key": asset_key(asset),
        "id": asset.get("id"),
        "title": asset.get("title"),
        "category": asset.get("category", "unknown"),
        "quality": quality,
        "quality_notes": asset_quality_notes(asset),
        "fit_overrides": fit_overrides,
        "anchor_name": anchor_calibration.get("anchor_name") or anchor_name_for_category(asset.get("category")),
        "anchor_validation_status": validation.get("status"),
        "anchor_method": anchor_calibration.get("method"),
        "canonical_placement": canonical,
        "canonical_method": CANONICAL_PLACEMENT_METHOD,
        "needs_calibration": needs_calibration,
        "placement_priority": placement_priority(quality, validation.get("status"), fit_overrides, canonical),
    }


def placement_priority(
    quality: str,
    validation_status: str | None,
    fit_overrides: dict[str, Any],
    canonical: bool = False,
) -> str:
    if quality == "ship" and validation_status == "ok" and fit_overrides and canonical:
        return "use-saved-overrides"
    if validation_status == "ok" and fit_overrides and not canonical:
        return "qwen-sam-recalibration-required"
    if quality == "review":
        return "rough-calibration"
    if quality == "reject":
        return "replace-or-manual-calibration"
    return "rough-calibration" if not fit_overrides else "promote-validation"


def placement_assets(config_path: Path = ASSET_CONFIG_PATH, include_qualities: set[str] | None = None) -> dict[str, Any]:
    config = load_asset_config(config_path)
    assets = [placement_status_for_asset(asset) for asset in config.get("assets", [])]
    if include_qualities:
        assets = [asset for asset in assets if asset["quality"] in include_qualities]
    counts: dict[str, int] = {}
    priorities: dict[str, int] = {}
    for asset in assets:
        counts[asset["quality"]] = counts.get(asset["quality"], 0) + 1
        priority = asset["placement_priority"]
        priorities[priority] = priorities.get(priority, 0) + 1
    return {
        "status": "ok",
        "assets": assets,
        "counts": counts,
        "placement_priorities": priorities,
        "profiles": PLACEMENT_PROFILES,
        "canonical_method": CANONICAL_PLACEMENT_METHOD,
        "policy": canonical_placement_note(),
    }


def placement_plan(
    asset_key_value: str,
    *,
    profile: str = "rough",
    config_path: Path = ASSET_CONFIG_PATH,
    qwen_workflow_json: str = "auto",
    qwen_workflow_search_roots_values: list[str] | None = None,
) -> dict[str, Any]:
    if profile not in PLACEMENT_PROFILES:
        raise ValueError(f"unknown placement profile: {profile}")
    config = load_asset_config(config_path)
    asset = find_asset(config, asset_key_value)
    status = placement_status_for_asset(asset)
    settings = dict(PLACEMENT_PROFILES[profile])
    workflow_path = ""
    workflow_summary = None
    try:
        roots = qwen_workflow_search_roots(qwen_workflow_search_roots_values or [])
        if not roots:
            roots = list(DEFAULT_QWEN_WORKFLOW_SEARCH_ROOTS)
        path, workflow_summary = resolve_qwen_workflow_path(qwen_workflow_json, roots)
        workflow_path = str(path)
    except (FileNotFoundError, ValueError):
        workflow_path = ""
    qwen_prompt = qwen_prompt_for_asset(asset, status["anchor_name"])
    command_template = [
        "python3",
        "scripts/accessory_visual_calibration.py",
        "--asset-config-json",
        str(config_path),
        "--asset-key",
        status["key"],
        "--current-overrides-from-asset-config",
        "--category",
        str(status["category"]),
        "--anchor-name",
        str(status["anchor_name"]),
        "--character-image",
        "<current_pose_png>",
        "--current-image",
        "<current_pose_png>",
        "--target-image",
        "<qwen_corrected_png>",
        "--image-box-mode",
        str(settings["sam_box_mode"]),
        "--sam-prompt",
        sam_prompt_for_asset(asset),
        "--qwen-prompt",
        qwen_prompt,
        "--qwen-run",
        "--qwen-steps",
        str(settings["qwen_steps"]),
        "--qwen-megapixels",
        str(settings["qwen_megapixels"]),
        "--qwen-denoise",
        str(settings["qwen_denoise"]),
        "--qwen-timeout-seconds",
        str(settings["qwen_timeout_seconds"]),
        "--qwen-device-map",
        "UnetLoaderGGUFMultiGPU=cuda:0",
        "--qwen-device-map",
        "CLIPLoaderMultiGPU=cuda:0",
        "--qwen-device-map",
        "VAELoaderMultiGPU=cuda:0",
        "--center-correction-gain",
        str(settings["center_correction_gain"]),
        "--size-correction-gain",
        str(settings["size_correction_gain"]),
        "--minimum-views",
        str(settings["minimum_views"]),
        "--output-json",
        f"outputs/calibration/{status['key']}_{profile}_placement.json",
    ]
    if settings.get("require_body_registration"):
        command_template.extend(
            [
                "--measurement-mode",
                "mask-registration",
            ]
        )
    if workflow_path:
        command_template.extend(["--qwen-workflow-json", workflow_path])
    pose_optimizer_command_template = [
        "docker",
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "blender-silhouette-fit",
        "blender",
        "--background",
        "<scene_or_blend_file>",
        "--python",
        "scripts/blender_silhouette_fit.py",
        "--",
        "--object-name",
        "<accessory_object_name>",
        "--target-mask",
        "<sam_target_mask_png_or_json>",
        "--report-json",
        f"/workspace/results/{status['key']}_{profile}_silhouette_fit.json",
        "--output-blend",
        f"/workspace/outputs/batch/{status['key']}_{profile}_silhouette_fit.blend",
        "--debug-dir",
        f"/workspace/outputs/calibration/{status['key']}_{profile}_silhouette_fit_debug",
        "--width",
        "256",
        "--height",
        "256",
        "--population-size",
        "32",
        "--generations",
        "24",
        "--scale-prior-weight",
        "0.35",
        "--area-prior-weight",
        "0.5",
        "--lock-scale-on-small-target",
        "--apply",
    ]
    return {
        "status": "ok",
        "profile": profile,
        "settings": settings,
        "asset": status,
        "qwen": {
            "workflow_template": workflow_path,
            "workflow_discovery": workflow_summary,
            "prompt": qwen_prompt,
            "run_by_default": settings["qwen_run"],
            "denoise": settings["qwen_denoise"],
            "steps": settings["qwen_steps"],
            "megapixels": settings["qwen_megapixels"],
        },
        "sam": {
            "prompt": sam_prompt_for_asset(asset),
            "box_mode": settings["sam_box_mode"],
        },
        "render": {
            "angles": settings["render_angles"],
            "view_sequence": settings.get("view_sequence", settings["render_angles"]),
            "sequential_multiview": bool(settings.get("sequential_multiview")),
            "pose_frames": settings["render_pose_frames"],
            "width": settings["render_width"],
            "height": settings["render_height"],
            "zoom_levels": settings.get("zoom_levels", "default"),
        },
        "solver": {
            "require_body_registration": bool(settings.get("require_body_registration")),
            "max_body_registration_aspect_change": settings.get("max_body_registration_aspect_change"),
            "observation_contract": {
                "required": ["view", "zoom", "current_box", "target_box", "character_box"],
                "registered_zoom_fields": ["current_body_box", "target_body_box"],
                "sequential_rule": "render each view from the latest solved overrides before measuring the next view",
            },
            "pose_optimizer": settings.get("pose_optimizer", "body-relative-box-solver"),
            "pose_parameters": settings.get("pose_parameters", []),
            "mask_scoring": settings.get("mask_scoring", []),
            "opencv_role": "mask metrics only; Blender optimizer moves the object"
            if settings.get("pose_optimizer")
            else "box/mask registration",
            "optimizer_command_template": pose_optimizer_command_template if settings.get("pose_optimizer") else [],
        },
        "command_template": command_template,
    }


def qwen_prompt_for_asset(asset: dict[str, Any], anchor_name: str) -> str:
    title = str(asset.get("title") or asset_key(asset)).strip()
    target = {
        "head_face:hat_top": "the top of the head, seated naturally above the hair",
        "head_face:eye_line": "the eye line, aligned with both eyes",
        "neck_chest:collar_center": "the collar center directly under the neck",
        "neck_chest:neck_loop": "the lower neck, hanging evenly around the collar",
        "torso_back:back_center": "the upper back, centered between the shoulders",
    }.get(anchor_name, "the visually correct attachment point")
    return (
        f"Edit only the {title} accessory. Move and resize it so it sits on {target}. "
        "Preserve the same character, pose, body, face, hair, clothing, camera framing, lighting, "
        "and background. Do not add text or extra objects."
    )


def sam_prompt_for_asset(asset: dict[str, Any]) -> str:
    text = f"{asset.get('title', '')} {asset.get('id', '')}".lower()
    if "bowtie" in text or "bow tie" in text:
        return "red bow tie"
    if "necktie" in text or " tie" in text:
        return "necktie"
    if "glasses" in text:
        return "glasses"
    if "hat" in text or "crown" in text or "helmet" in text:
        return "hat"
    if "backpack" in text or "bag" in text:
        return "backpack"
    if "necklace" in text:
        return "necklace"
    return "accessory"


def normalize_box(value: Any) -> list[float]:
    if isinstance(value, str):
        return parse_box(value)
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return parse_box(",".join(str(item) for item in value))
    raise ValueError("box must be a list of four numbers or x1,y1,x2,y2 string")


def placement_suggestion(payload: dict[str, Any], config_path: Path = ASSET_CONFIG_PATH) -> dict[str, Any]:
    asset_key_value = str(payload.get("asset_key") or payload.get("asset") or "").strip()
    if not asset_key_value:
        raise ValueError("asset_key is required")
    config = load_asset_config(config_path)
    try:
        asset = find_asset(config, asset_key_value)
    except ValueError:
        if not (payload.get("allow_uncataloged") and (payload.get("solve_3d") or payload.get("observations"))):
            raise
        asset = {
            "id": asset_key_value,
            "title": payload.get("title") or asset_key_value,
            "category": payload.get("category", "unknown"),
            "fit_overrides": payload.get("current_overrides") or {},
            "anchor_calibration": {"anchor_name": payload.get("anchor_name")},
            "quality": "review",
            "notes": ["uncataloged placement request"],
        }
    status = placement_status_for_asset(asset)
    if payload.get("solve_3d") or payload.get("observations"):
        result = solve_placement(
            {
                **payload,
                "asset_key": status["key"],
                "category": payload.get("category") or status["category"],
                "anchor_name": payload.get("anchor_name") or status["anchor_name"],
                "current_overrides": payload.get("current_overrides") or status["fit_overrides"],
            }
        )
        return {
            "status": "ok",
            "asset": status,
            "suggestion": result,
        }
    result = calibrated_fit_overrides(
        current_box=normalize_box(payload.get("current_box")),
        target_box=normalize_box(payload.get("target_box")),
        character_box=normalize_box(payload.get("character_box")),
        current_overrides=payload.get("current_overrides") or status["fit_overrides"],
        asset_key=status["key"],
        category=status["category"],
        source=str(payload.get("source") or "placement-api-boxes"),
        anchor_name=str(payload.get("anchor_name") or status["anchor_name"]),
        center_correction_gain=float(payload.get("center_correction_gain", 1.0)),
        size_correction_gain=float(payload.get("size_correction_gain", 1.0)),
    )
    return {
        "status": "ok",
        "asset": status,
        "suggestion": result,
    }
