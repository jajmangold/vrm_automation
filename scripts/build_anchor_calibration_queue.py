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

from scripts.accessory_visual_calibration import asset_catalog_key, anchor_name_for_category
from scripts.placement_methods import (
    CANONICAL_PLACEMENT_METHOD,
    canonical_placement_note,
    is_canonical_anchor_calibration,
)


DEFAULT_ASSET_CONFIG = Path("config/poly_pizza_assets.json")
DEFAULT_COMBINED_RESULT = Path("results/person_factory_all_latest.json")
DEFAULT_OUTPUT = Path("results/accessory_anchor_calibration_queue_latest.json")

HEADWEAR_TOKENS = ("hat", "helmet", "crown", "fedora")
EYE_LINE_TOKENS = ("glasses", "sunglasses", "monocle")
FACE_CENTER_TOKENS = ("mask",)
COLLAR_TOKENS = ("bowtie", "bow tie", "necktie", "tie")
NECK_LOOP_TOKENS = ("necklace",)


def quality_status(asset: dict[str, Any]) -> str:
    quality = asset.get("quality", "none")
    if isinstance(quality, dict):
        return str(quality.get("status", "none"))
    return str(quality or "none")


def asset_key(asset: dict[str, Any]) -> str:
    asset_id = str(asset.get("id") or asset.get("title") or "")
    return asset_catalog_key(asset_id)


def searchable_asset_text(asset: dict[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in (
            asset.get("id", ""),
            asset.get("title", ""),
            asset.get("creator", ""),
            asset.get("output_path", ""),
        )
    ).lower()


def contains_token(text: str, tokens: tuple[str, ...]) -> bool:
    for token in tokens:
        pattern = r"(?<![a-z0-9])" + re.escape(token).replace(r"\ ", r"[\s_-]+") + r"(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def target_anchor_name_for_asset(asset: dict[str, Any]) -> str:
    existing = ((asset.get("anchor_calibration") or {}).get("anchor_name") or "").strip()
    if existing:
        return existing

    text = searchable_asset_text(asset)
    category = str(asset.get("category") or "unknown").strip().lower().replace("-", "_")
    fit_anchor = str((asset.get("fit_overrides") or {}).get("anchor", "")).strip().lower()

    if fit_anchor == "hat_top" or contains_token(text, HEADWEAR_TOKENS):
        return "head_face:hat_top"
    if contains_token(text, EYE_LINE_TOKENS):
        return "head_face:eye_line"
    if contains_token(text, FACE_CENTER_TOKENS):
        return "head_face:face_center"
    if contains_token(text, COLLAR_TOKENS):
        return "neck_chest:collar_center"
    if contains_token(text, NECK_LOOP_TOKENS):
        return "neck_chest:neck_loop"
    if category == "torso_back":
        return "torso_back:back_center"
    if category == "torso_front":
        return "torso_front:torso_front_center"
    return anchor_name_for_category(category)


def calibration_state(asset: dict[str, Any]) -> str:
    anchor_calibration = asset.get("anchor_calibration") or {}
    validation = anchor_calibration.get("validation") or {}
    validation_status = str(validation.get("status", "")).strip().lower()
    if validation_status == "ok":
        if is_canonical_anchor_calibration(anchor_calibration):
            return "validated"
        return "needs-qwen-sam-calibration"
    if anchor_calibration:
        return "validate-existing-calibration"
    if asset.get("fit_overrides"):
        return "validate-existing-fit"
    return "needs-calibration"


def state_priority(state: str) -> int:
    return {
        "needs-calibration": 80,
        "validate-existing-fit": 70,
        "validate-existing-calibration": 60,
        "needs-qwen-sam-calibration": 75,
        "validated": 10,
    }.get(state, 50)


def quality_priority(status: str) -> int:
    return {
        "fix": 25,
        "review": 20,
        "reject": 15,
        "none": 10,
        "ship": 5,
    }.get(status, 0)


def sam_prompt_for_asset(asset: dict[str, Any], anchor_name: str) -> str:
    text = searchable_asset_text(asset)
    title = str(asset.get("title") or asset_key(asset)).strip().lower()
    if contains_token(text, ("bowtie", "bow tie")):
        return "red bow tie"
    if contains_token(text, ("necktie", "tie")):
        return "necktie"
    if contains_token(text, ("necklace",)):
        return "necklace"
    if contains_token(text, EYE_LINE_TOKENS):
        return "glasses"
    if contains_token(text, ("mask",)):
        return "face mask"
    if contains_token(text, HEADWEAR_TOKENS):
        return "hat"
    if contains_token(text, ("backpack",)):
        return "backpack"
    if contains_token(text, ("bag",)):
        return "bag"
    if anchor_name.endswith(":back_center"):
        return "back accessory"
    return title


def anchor_target_phrase(anchor_name: str) -> str:
    return {
        "head_face:hat_top": "the top of the head, seated naturally above the hair",
        "head_face:eye_line": "the eye line, aligned with both eyes",
        "head_face:face_center": "the center of the face, aligned to the nose and mouth",
        "neck_chest:collar_center": "the collar center directly under the neck",
        "neck_chest:neck_loop": "the lower neck, hanging evenly around the collar",
        "torso_back:back_center": "the upper back, centered between the shoulders",
        "torso_front:torso_front_center": "the upper torso front, centered on the chest",
    }.get(anchor_name, "the visually correct attachment point")


def qwen_prompt_for_asset(asset: dict[str, Any], anchor_name: str) -> str:
    title = str(asset.get("title") or asset_key(asset)).strip()
    return (
        f"Edit only the {title} accessory. Move and resize it so it sits on "
        f"{anchor_target_phrase(anchor_name)}. Preserve the same character, pose, body, face, "
        "hair, clothing, camera framing, lighting, and background. Do not add text or extra objects."
    )


def path_from_workspace(path: str | None, workspace_root: Path) -> Path | None:
    if not path:
        return None
    if path.startswith("/workspace/"):
        return workspace_root / path.removeprefix("/workspace/")
    return Path(path)


def render_pngs(render_dir: Path | None) -> list[str]:
    if not render_dir or not render_dir.exists():
        return []
    pngs = sorted(render_dir.glob("*.png"), key=lambda path: (0 if "portrait" in path.name else 1, path.name))
    return [str(path) for path in pngs[:6]]


def job_matches_asset(job: dict[str, Any], asset: dict[str, Any]) -> bool:
    key = asset_key(asset)
    tags = [str(tag) for tag in (job.get("metadata") or {}).get("tags", [])]
    if key in tags:
        return True
    output_path = Path(str(asset.get("output_path") or "")).name
    outfit_model = str((job.get("environment") or {}).get("OUTFIT_MODEL") or "")
    return bool(output_path and outfit_model.endswith(output_path))


def render_examples_for_asset(
    asset: dict[str, Any],
    jobs: list[dict[str, Any]],
    workspace_root: Path,
    limit: int = 3,
) -> list[dict[str, Any]]:
    examples = []
    for job in jobs:
        if not job_matches_asset(job, asset):
            continue
        environment = job.get("environment") or {}
        render_dir = path_from_workspace(environment.get("RENDER_DIR"), workspace_root)
        examples.append(
            {
                "job_id": job.get("id"),
                "render_dir": str(render_dir) if render_dir else None,
                "pose_renders": render_pngs(render_dir),
                "output_glb": environment.get("OUTPUT_GLB"),
            }
        )
        if len(examples) >= limit:
            break
    return examples


def command_template_for_asset(asset: dict[str, Any], anchor_name: str) -> str:
    key = asset_key(asset)
    return (
        "python3 scripts/accessory_visual_calibration.py "
        "--asset-config-json config/poly_pizza_assets.json "
        f"--asset-key {key} "
        "--current-overrides-from-asset-config "
        f"--category {asset.get('category', 'unknown')} "
        f"--anchor-name {anchor_name} "
        "--character-image <current_pose_png> "
        "--current-image <current_pose_png> "
        "--target-image <qwen_corrected_png> "
        "--image-box-mode sam-red-fallback "
        f"--sam-prompt \"{sam_prompt_for_asset(asset, anchor_name)}\" "
        "--qwen-device-map UnetLoaderGGUFMultiGPU=cuda:0 "
        "--qwen-device-map CLIPLoaderMultiGPU=cuda:0 "
        "--qwen-device-map VAELoaderMultiGPU=cuda:0 "
        "--center-correction-gain 0.42 "
        "--size-correction-gain 1.0 "
        f"--output-json outputs/calibration/{key}_anchor_calibration.json"
    )


def load_jobs(combined_result_path: Path | None) -> list[dict[str, Any]]:
    if not combined_result_path or not combined_result_path.exists():
        return []
    data = json.loads(combined_result_path.read_text(encoding="utf-8"))
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    return [job for job in jobs if isinstance(job, dict)]


def build_anchor_calibration_queue(
    asset_config_path: Path = DEFAULT_ASSET_CONFIG,
    combined_result_path: Path | None = DEFAULT_COMBINED_RESULT,
    workspace_root: Path = Path("."),
    include_rejects: bool = False,
) -> dict[str, Any]:
    config = json.loads(asset_config_path.read_text(encoding="utf-8"))
    assets = [asset for asset in config.get("assets", []) if isinstance(asset, dict)]
    jobs = load_jobs(combined_result_path)
    items = []
    for asset in assets:
        status = quality_status(asset)
        if status == "reject" and not include_rejects:
            continue
        state = calibration_state(asset)
        anchor_name = target_anchor_name_for_asset(asset)
        priority = state_priority(state) + quality_priority(status)
        item = {
            "asset_id": asset.get("id"),
            "asset_key": asset_key(asset),
            "title": asset.get("title"),
            "category": asset.get("category", "unknown"),
            "quality": status,
            "calibration_state": state,
            "canonical_placement_method": CANONICAL_PLACEMENT_METHOD,
            "canonical_placement": is_canonical_anchor_calibration(asset.get("anchor_calibration") or {}),
            "priority": priority,
            "target_anchor_name": anchor_name,
            "sam_prompt": sam_prompt_for_asset(asset, anchor_name),
            "qwen_prompt": qwen_prompt_for_asset(asset, anchor_name),
            "has_fit_overrides": bool(asset.get("fit_overrides")),
            "fit_overrides": asset.get("fit_overrides") or {},
            "anchor_validation_status": ((asset.get("anchor_calibration") or {}).get("validation") or {}).get(
                "status", "none"
            ),
            "output_path": asset.get("output_path"),
            "render_examples": render_examples_for_asset(asset, jobs, workspace_root),
            "calibration_command_template": command_template_for_asset(asset, anchor_name),
        }
        items.append(item)

    items.sort(key=lambda item: (-int(item["priority"]), item["asset_key"]))
    work_items = [item for item in items if item["calibration_state"] != "validated"]
    summary = {
        "asset_count": len(items),
        "validated_count": len(items) - len(work_items),
        "work_item_count": len(work_items),
        "state_counts": {},
        "anchor_counts": {},
        "canonical_method": CANONICAL_PLACEMENT_METHOD,
        "policy": canonical_placement_note(),
    }
    for item in items:
        summary["state_counts"][item["calibration_state"]] = summary["state_counts"].get(item["calibration_state"], 0) + 1
        summary["anchor_counts"][item["target_anchor_name"]] = summary["anchor_counts"].get(item["target_anchor_name"], 0) + 1

    return {
        "status": "ok",
        "asset_config": str(asset_config_path),
        "combined_result": str(combined_result_path) if combined_result_path else None,
        "summary": summary,
        "work_items": work_items,
        "all_items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a prioritized Qwen/SAM accessory anchor calibration queue.")
    parser.add_argument("--asset-config-json", default=str(DEFAULT_ASSET_CONFIG))
    parser.add_argument("--combined-result-json", default=str(DEFAULT_COMBINED_RESULT))
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--include-rejects", action="store_true")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_anchor_calibration_queue(
        asset_config_path=Path(args.asset_config_json),
        combined_result_path=Path(args.combined_result_json) if args.combined_result_json else None,
        workspace_root=Path(args.workspace_root),
        include_rejects=args.include_rejects,
    )
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
