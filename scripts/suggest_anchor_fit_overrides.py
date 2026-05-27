from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accessory_visual_calibration import asset_catalog_key, clamp, rounded
from scripts.asset_classifier import placement_profile


DEFAULT_MEASUREMENTS = Path("results/accessory_anchor_current_measurements_top3_latest.json")
DEFAULT_ASSET_CONFIG = Path("config/poly_pizza_assets.json")
DEFAULT_OUTPUT = Path("results/accessory_anchor_fit_suggestions_latest.json")

TARGET_PROFILES: dict[str, dict[str, float]] = {
    "head_face:eye_line": {"center_x": 0.5, "center_y": 0.43, "width": 0.42, "height": 0.16},
    "head_face:hat_top": {"center_x": 0.5, "center_y": 0.16, "width": 0.45, "height": 0.24},
    "head_face:face_center": {"center_x": 0.5, "center_y": 0.48, "width": 0.36, "height": 0.36},
    "neck_chest:collar_center": {"center_x": 0.5, "center_y": 0.41, "width": 0.2, "height": 0.1},
    "neck_chest:neck_loop": {"center_x": 0.5, "center_y": 0.5, "width": 0.34, "height": 0.2},
    "torso_back:back_center": {"center_x": 0.5, "center_y": 0.5, "width": 0.34, "height": 0.34},
    "torso_front:torso_front_center": {"center_x": 0.5, "center_y": 0.52, "width": 0.3, "height": 0.32},
}

VERTICAL_SUGGESTION_LIMITS: dict[str, tuple[float, float]] = {
    "neck_chest:collar_center": (0.58, 0.84),
    "neck_chest:neck_loop": (0.58, 0.84),
}
SIZE_SUGGESTION_LIMITS: dict[str, tuple[float, float]] = {
    "torso_back:back_center": (0.08, 0.32),
}


def load_asset_config(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    assets = {}
    for asset in config.get("assets", []):
        if isinstance(asset, dict):
            assets[asset_catalog_key(str(asset.get("id") or ""))] = asset
    return assets


def current_overrides_for_asset(asset: dict[str, Any] | None, anchor_name: str) -> dict[str, Any]:
    if asset and asset.get("fit_overrides"):
        return dict(asset["fit_overrides"])
    category = str((asset or {}).get("category") or anchor_name.split(":", 1)[0] or "unknown")
    overrides = placement_profile(category)
    if anchor_name == "head_face:hat_top":
        overrides.update({"anchor": "hat_top", "fit_scope": "headwear", "scale_axis": "height"})
    if anchor_name == "head_face:eye_line":
        overrides.update({"scale_axis": "width", "fit_scope": "head-face"})
    return overrides


def target_profile_for_anchor(anchor_name: str) -> dict[str, float]:
    return TARGET_PROFILES.get(anchor_name, {"center_x": 0.5, "center_y": 0.5, "width": 0.3, "height": 0.3})


def suggest_fit_overrides(
    measurement: dict[str, Any],
    current_overrides: dict[str, Any],
    center_correction_gain: float = 0.42,
    horizontal_correction_gain: float = 0.0,
    size_correction_gain: float = 1.0,
) -> dict[str, Any]:
    anchor_name = str(measurement.get("target_anchor_name") or "")
    target = target_profile_for_anchor(anchor_name)
    measured = measurement["measurement"]
    center = measured["center_ratio"]
    size = measured["size_ratio"]
    scale_axis = str(current_overrides.get("scale_axis", "width"))
    current_size_ratio = float(current_overrides.get("target_size_ratio", 0.22))
    current_vertical = float(current_overrides.get("vertical_center_ratio", 0.9))
    current_horizontal = float(current_overrides.get("horizontal_center_offset_ratio", 0.0))

    if scale_axis == "height":
        raw_size_scale = target["height"] / max(float(size.get("height", 0.0)), 1e-6)
    else:
        scale_axis = "width"
        raw_size_scale = target["width"] / max(float(size.get("width", 0.0)), 1e-6)
    size_scale = 1.0 + ((raw_size_scale - 1.0) * size_correction_gain)

    raw_center_dx = target["center_x"] - float(center.get("x", 0.0))
    raw_center_dy = target["center_y"] - float(center.get("y", 0.0))
    center_dx = raw_center_dx * horizontal_correction_gain
    center_dy = raw_center_dy * center_correction_gain

    suggested = dict(current_overrides)
    raw_size_ratio = current_size_ratio * size_scale
    size_min, size_max = SIZE_SUGGESTION_LIMITS.get(anchor_name, (0.01, 0.6))
    suggested["scale_axis"] = scale_axis
    suggested["target_size_ratio"] = rounded(clamp(raw_size_ratio, size_min, size_max))
    raw_vertical = current_vertical - center_dy
    vertical_min, vertical_max = VERTICAL_SUGGESTION_LIMITS.get(anchor_name, (0.0, 1.1))
    suggested["vertical_center_ratio"] = rounded(clamp(raw_vertical, vertical_min, vertical_max))
    if abs(center_dx) >= 0.005 or "horizontal_center_offset_ratio" in current_overrides:
        suggested["horizontal_center_offset_ratio"] = rounded(clamp(current_horizontal + center_dx, -0.5, 0.5))

    review_warnings = []
    if abs(raw_center_dx) > 0.12:
        review_warnings.append("large-horizontal-correction")
    if abs(raw_center_dy) > 0.12:
        review_warnings.append("large-vertical-correction")
    if raw_size_scale < 0.55 or raw_size_scale > 1.6:
        review_warnings.append("large-size-correction")
    if raw_size_ratio < size_min or raw_size_ratio > size_max:
        review_warnings.append("torso-back-size-clamp" if anchor_name == "torso_back:back_center" else "size-clamp")
    if raw_vertical < vertical_min or raw_vertical > vertical_max:
        review_warnings.append("neck-chest-vertical-clamp" if anchor_name.startswith("neck_chest:") else "near-vertical-clamp")
    if suggested["vertical_center_ratio"] >= 1.05 or suggested["vertical_center_ratio"] <= 0.05:
        review_warnings.append("near-vertical-clamp")

    return {
        "asset_key": measurement.get("asset_key"),
        "target_anchor_name": anchor_name,
        "target_profile": target,
        "measurement": measured,
        "current_fit_overrides": current_overrides,
        "suggested_fit_overrides": suggested,
        "correction": {
            "center_dx": rounded(raw_center_dx),
            "center_dy": rounded(raw_center_dy),
            "applied_center_dx": rounded(center_dx),
            "applied_center_dy": rounded(center_dy),
            "size_scale": rounded(size_scale),
        },
        "correction_gain": {
            "center": center_correction_gain,
            "horizontal": horizontal_correction_gain,
            "size": size_correction_gain,
        },
        "review_warnings": review_warnings,
        "status": "review" if review_warnings else "candidate",
    }


def build_suggestions(measurements_path: Path, asset_config_path: Path) -> dict[str, Any]:
    measurement_report = json.loads(measurements_path.read_text(encoding="utf-8"))
    assets = load_asset_config(asset_config_path)
    suggestions = []
    for measurement in measurement_report.get("measurements", []):
        if measurement.get("status") != "ok" or not measurement.get("measurement"):
            suggestions.append(
                {
                    "asset_key": measurement.get("asset_key"),
                    "status": "review",
                    "review_warnings": ["missing-measurement"],
                    "measurement": measurement,
                }
            )
            continue
        key = asset_catalog_key(str(measurement.get("asset_key") or ""))
        asset = assets.get(key)
        overrides = current_overrides_for_asset(asset, str(measurement.get("target_anchor_name") or ""))
        suggestions.append(suggest_fit_overrides(measurement, overrides))

    return {
        "status": "ok",
        "measurements": str(measurements_path),
        "asset_config": str(asset_config_path),
        "suggestions": suggestions,
        "summary": {
            "count": len(suggestions),
            "candidate_count": sum(1 for item in suggestions if item.get("status") == "candidate"),
            "review_count": sum(1 for item in suggestions if item.get("status") == "review"),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggest deterministic fit_overrides from SAM anchor measurements.")
    parser.add_argument("--measurements-json", default=str(DEFAULT_MEASUREMENTS))
    parser.add_argument("--asset-config-json", default=str(DEFAULT_ASSET_CONFIG))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_suggestions(
        measurements_path=Path(args.measurements_json),
        asset_config_path=Path(args.asset_config_json),
    )
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
