from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accessory_visual_calibration import asset_catalog_key, find_asset  # noqa: E402


DEFAULT_SUGGESTIONS = Path("results/accessory_anchor_fit_suggestions_batch_latest.json")
DEFAULT_ASSET_CONFIG = Path("config/poly_pizza_assets.json")
DEFAULT_OUTPUT = Path("config/person_factory.anchor_candidate_probe_latest.json")

BASE_MODELS = {
    "female": "/workspace/input/base_models/vroid_hairsample_female_cc0.vrm",
    "male": "/workspace/input/base_models/vroid_hairsample_male_cc0.vrm",
}
OVERRIDE_KEY_MAP = {
    "scale_axis": "outfit_scale_axis",
    "target_size_ratio": "outfit_target_size_ratio",
    "vertical_center_ratio": "outfit_vertical_center_ratio",
    "horizontal_center_offset_ratio": "outfit_horizontal_center_offset_ratio",
    "surface_offset_ratio": "outfit_surface_offset_ratio",
    "anchor_z_percentile": "outfit_anchor_z_percentile",
    "rotation_z_degrees": "outfit_rotation_z_degrees",
    "anchor": "outfit_anchor",
    "fit_scope": "outfit_fit_scope",
    "exclude_materials": "outfit_exclude_materials",
    "anchor_offset": "outfit_anchor_offset",
}


def normalize_tag(value: str) -> str:
    cleaned = str(value).strip().lower().replace("_", "-").replace(":", "-")
    cleaned = re.sub(r"[^a-z0-9-]+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned.strip("-")


def workspace_path(path: str) -> str:
    cleaned = str(path).strip()
    if cleaned.startswith("/workspace/"):
        return cleaned
    return f"/workspace/{cleaned.removeprefix('./')}"


def selected_suggestions(
    suggestions: dict[str, Any],
    include_review: bool = False,
    limit: int = 0,
    asset_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    selected = []
    normalized_asset_keys = {asset_catalog_key(key) for key in (asset_keys or set())}
    for suggestion in suggestions.get("suggestions") or []:
        if not isinstance(suggestion, dict):
            continue
        status = str(suggestion.get("status") or "").lower()
        if status != "candidate" and not (include_review and status == "review"):
            continue
        if normalized_asset_keys and asset_catalog_key(str(suggestion.get("asset_key") or "")) not in normalized_asset_keys:
            continue
        selected.append(suggestion)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def apply_fit_overrides(job: dict[str, Any], overrides: dict[str, Any]) -> None:
    for source_key, job_key in OVERRIDE_KEY_MAP.items():
        if source_key in overrides and overrides[source_key] is not None:
            job[job_key] = overrides[source_key]


def base_model_for_name(name: str) -> str:
    cleaned = name.strip().lower()
    if cleaned not in BASE_MODELS:
        raise ValueError(f"unsupported base: {name}; expected one of {', '.join(sorted(BASE_MODELS))}")
    return BASE_MODELS[cleaned]


def render_settings_for_category(category: str, fallback_angles: str, fallback_frames: str) -> tuple[str, str, list[str]]:
    normalized = normalize_tag(category)
    if normalized == "torso-back":
        return "front,portrait,back", "24,72", ["review:torso-back"]
    if normalized == "neck-chest":
        return "front,portrait", "24,72", ["review:neck-chest"]
    if normalized == "head-face":
        return "front,portrait", "24,72", ["review:head-face"]
    return fallback_angles, fallback_frames, []


def build_probe_manifest(
    suggestions: dict[str, Any],
    asset_config: dict[str, Any],
    id_prefix: str = "anchor-candidate-probe",
    bases: list[str] | None = None,
    include_review: bool = False,
    asset_keys: set[str] | None = None,
    limit: int = 0,
    render_angles: str = "front,portrait",
    render_pose_frames: str = "24,72",
    category_aware_rendering: bool = False,
) -> dict[str, Any]:
    bases = bases or ["female"]
    jobs = []
    selected = selected_suggestions(
        suggestions,
        include_review=include_review,
        limit=limit,
        asset_keys=asset_keys,
    )
    for suggestion in selected:
        asset_key = str(suggestion.get("asset_key") or "")
        asset = find_asset(asset_config, asset_key)
        target_anchor_name = str(suggestion.get("target_anchor_name") or "")
        fit_overrides = dict(suggestion.get("suggested_fit_overrides") or {})
        for base in bases:
            base = base.strip().lower()
            job_index = len(jobs) + 1
            normalized_asset_key = asset_catalog_key(asset_key)
            category = str(asset.get("category") or fit_overrides.get("category") or "unknown")
            job_render_angles = render_angles
            job_render_pose_frames = render_pose_frames
            review_tags = []
            if category_aware_rendering:
                job_render_angles, job_render_pose_frames, review_tags = render_settings_for_category(
                    category,
                    render_angles,
                    render_pose_frames,
                )
            job = {
                "id": f"{id_prefix}-{job_index:03d}",
                "display_name": f"Anchor Candidate {asset.get('title') or normalized_asset_key} {base.title()}",
                "persona": f"{base} accessory fit candidate for {normalized_asset_key}",
                "model_path": base_model_for_name(base),
                "outfit_model": workspace_path(str(asset.get("output_path") or "")),
                "category": category,
                "animation_preset": "talk_idle",
                "facial_preset": "neutral",
                "export_blend": "0",
                "export_glb": "1",
                "export_vrm": "0",
                "render_angles": job_render_angles,
                "render_pose_frames": job_render_pose_frames,
                "render_width": "640",
                "render_height": "960",
                "license": asset.get("license"),
                "source_url": asset.get("source_url"),
                "creator": asset.get("creator"),
                "notes": (
                    f"Probe render for {normalized_asset_key} using batch SAM anchor suggestion; "
                    "not catalog-promoted."
                ),
                "tags": [
                    "generated",
                    "anchor-candidate",
                    normalized_asset_key,
                    normalize_tag(category),
                    f"anchor:{normalize_tag(target_anchor_name)}",
                    f"base:{base}-hairsample",
                    "source:anchor-fit-suggestion",
                    *review_tags,
                ],
            }
            apply_fit_overrides(job, fit_overrides)
            jobs.append(job)

    return {
        "defaults": {
            "cache_base_scenes": "1",
            "export_blend": "0",
            "export_glb": "1",
            "export_vrm": "0",
            "render_engine": "BLENDER_WORKBENCH",
            "render_pose_stills": "1",
            "render_width": "640",
            "render_height": "960",
        },
        "source": {
            "suggestion_count": len(selected),
            "include_review": include_review,
            "bases": bases,
        },
        "jobs": jobs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a small person-factory probe manifest from anchor fit suggestions.")
    parser.add_argument("--suggestions-json", default=str(DEFAULT_SUGGESTIONS))
    parser.add_argument("--asset-config-json", default=str(DEFAULT_ASSET_CONFIG))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--id-prefix", default="anchor-candidate-probe")
    parser.add_argument("--bases", default="female")
    parser.add_argument("--include-review", action="store_true")
    parser.add_argument("--asset-key", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--render-angles", default="front,portrait")
    parser.add_argument("--render-pose-frames", default="24,72")
    parser.add_argument("--category-aware-rendering", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    suggestions = json.loads(Path(args.suggestions_json).read_text(encoding="utf-8"))
    asset_config = json.loads(Path(args.asset_config_json).read_text(encoding="utf-8"))
    manifest = build_probe_manifest(
        suggestions,
        asset_config,
        id_prefix=args.id_prefix,
        bases=[base.strip() for base in args.bases.split(",") if base.strip()],
        include_review=args.include_review,
        asset_keys=set(args.asset_key),
        limit=args.limit,
        render_angles=args.render_angles,
        render_pose_frames=args.render_pose_frames,
        category_aware_rendering=args.category_aware_rendering,
    )
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
