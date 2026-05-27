#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accessory_attachment_profiles import load_attachment_profiles


def find_profile(profile_id: str, config_path: Path) -> dict[str, Any]:
    data = load_attachment_profiles(config_path)
    for profile in data["profiles"]:
        if profile["id"] == profile_id:
            return profile
    raise ValueError(f"unknown attachment profile: {profile_id}")


def workspace_path(path: str | Path) -> str:
    value = str(path)
    if value.startswith("/workspace/"):
        return value
    path_obj = Path(value)
    if path_obj.is_absolute():
        try:
            return f"/workspace/{path_obj.relative_to(ROOT)}"
        except ValueError:
            return value
    return f"/workspace/{value}"


def local_path(path: str | Path) -> Path:
    value = str(path)
    if value.startswith("/workspace/"):
        return ROOT / value.removeprefix("/workspace/")
    path_obj = Path(value)
    return path_obj if path_obj.is_absolute() else ROOT / path_obj


def build_sam_command(args: argparse.Namespace, profile: dict[str, Any], target_mask_dir: Path) -> list[str]:
    command = [
        "python3",
        "scripts/build_complete_target_mask.py",
        "--image",
        str(local_path(args.qwen_target_image)),
        "--output-dir",
        str(target_mask_dir),
        "--sam-endpoint",
        args.sam_endpoint,
        "--confidence-threshold",
        str(args.sam_confidence_threshold),
    ]
    for prompt in profile["placement"].get("target_prompts", []):
        command.extend(["--prompt", prompt])
    if args.expected_min_bbox_aspect is not None:
        command.extend(["--expected-min-bbox-aspect", str(args.expected_min_bbox_aspect)])
    if args.target_bbox_aspect is not None:
        command.extend(["--target-bbox-aspect", str(args.target_bbox_aspect)])
    if args.bbox_aspect_tolerance is not None:
        command.extend(["--bbox-aspect-tolerance", str(args.bbox_aspect_tolerance)])
    return command


def build_silhouette_command(args: argparse.Namespace, target_mask: Path, report_json: Path, output_blend: Path, debug_dir: Path) -> list[str]:
    command = [
        "docker",
        "compose",
        "--profile",
        "tools",
        "run",
        "--rm",
        "blender-silhouette-fit",
        "blender",
        "--background",
        workspace_path(args.source_blend),
        "--python",
        "scripts/install_addons.py",
        "--python",
        "scripts/blender_silhouette_fit.py",
        "--",
        "--object-name",
        args.object_name,
        "--target-mask",
        workspace_path(target_mask),
        "--report-json",
        workspace_path(report_json),
        "--output-blend",
        workspace_path(output_blend),
        "--debug-dir",
        workspace_path(debug_dir),
        "--width",
        str(args.fit_width),
        "--height",
        str(args.fit_height),
        "--population-size",
        str(args.population_size),
        "--generations",
        str(args.generations),
        "--sigma",
        str(args.sigma),
        "--seed",
        str(args.seed),
        "--scale-prior-weight",
        str(args.scale_prior_weight),
        "--area-prior-weight",
        str(args.area_prior_weight),
        "--apply",
    ]
    if args.expected_min_bbox_aspect is not None:
        command.extend(["--expected-min-bbox-aspect", str(args.expected_min_bbox_aspect)])
    if args.lock_scale_on_small_target:
        command.append("--lock-scale-on-small-target")
    if args.lower_bounds:
        command.append(f"--lower-bounds={args.lower_bounds}")
    if args.upper_bounds:
        command.append(f"--upper-bounds={args.upper_bounds}")
    return command


def run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "log_tail": completed.stdout.splitlines()[-80:],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an attachment profile through Qwen-target/SAM-mask/Blender-silhouette fitting.")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--source-blend", required=True)
    parser.add_argument("--object-name", required=True)
    parser.add_argument("--qwen-target-image", help="Qwen Image Edit output image. Required unless --target-mask is supplied.")
    parser.add_argument("--qwen-source-image", help="Original render supplied to Qwen, recorded for traceability.")
    parser.add_argument("--target-mask", help="Reviewed SAM/object-compatible target mask. Skips SAM mask building when supplied.")
    parser.add_argument("--run-id", default="attachment-anchor-integrated")
    parser.add_argument("--profiles-json", default="config/accessory_attachment_profiles.json")
    parser.add_argument("--output-root", default="outputs/calibration")
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--sam-endpoint", default="http://127.0.0.1:8105")
    parser.add_argument("--sam-confidence-threshold", type=float, default=0.25)
    parser.add_argument("--target-bbox-aspect", type=float)
    parser.add_argument("--expected-min-bbox-aspect", type=float)
    parser.add_argument("--bbox-aspect-tolerance", type=float, default=0.25)
    parser.add_argument("--fit-width", type=int, default=256)
    parser.add_argument("--fit-height", type=int, default=256)
    parser.add_argument("--population-size", type=int, default=32)
    parser.add_argument("--generations", type=int, default=24)
    parser.add_argument("--sigma", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--scale-prior-weight", type=float, default=0.35)
    parser.add_argument("--area-prior-weight", type=float, default=0.5)
    parser.add_argument("--lock-scale-on-small-target", action="store_true")
    parser.add_argument("--lower-bounds", help="Comma-separated x,y,z,rot_x,rot_y,rot_z,scale lower bounds for silhouette fitting.")
    parser.add_argument("--upper-bounds", help="Comma-separated x,y,z,rot_x,rot_y,rot_z,scale upper bounds for silhouette fitting.")
    parser.add_argument("--run", action="store_true", help="Execute commands. Without this, writes a dry-run plan only.")
    parser.add_argument("--report-json")
    return parser.parse_args(argv)


def build_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    if not args.qwen_target_image and not args.target_mask:
        raise ValueError("--qwen-target-image is required unless --target-mask is supplied")
    profile = find_profile(args.profile_id, local_path(args.profiles_json))
    output_dir = local_path(args.output_root) / args.run_id
    target_mask_dir = output_dir / "sam_target_mask"
    target_mask = local_path(args.target_mask) if args.target_mask else target_mask_dir / "target_mask_union.png"
    fit_report = local_path(args.results_root) / f"{args.run_id}_silhouette_fit.json"
    output_blend = ROOT / "outputs" / "batch" / f"{args.run_id}_silhouette_fit.blend"
    debug_dir = output_dir / "silhouette_fit_debug"

    steps: list[dict[str, Any]] = [
        {
            "name": "qwen-image-edit-target",
            "status": "external-input",
            "source_image": args.qwen_source_image,
            "target_image": args.qwen_target_image,
            "prompts": profile["placement"].get("target_prompts", []),
            "note": "Qwen Image Edit supplies the visual target; this pipeline consumes the reviewed target image.",
        }
    ]
    if args.target_mask:
        steps.append(
            {
                "name": "sam-target-mask",
                "status": "provided",
                "target_mask": str(target_mask),
                "note": "Using a reviewed target mask; SAM command is skipped.",
            }
        )
    else:
        steps.append(
            {
                "name": "sam-target-mask",
                "status": "planned",
                "command": build_sam_command(args, profile, target_mask_dir),
                "target_mask": str(target_mask),
                "review_sheet": str(target_mask_dir / "complete_target_mask_review_sheet.png"),
            }
        )
    steps.append(
        {
            "name": "blender-silhouette-fit",
            "status": "planned",
            "command": build_silhouette_command(args, target_mask, fit_report, output_blend, debug_dir),
            "report_json": str(fit_report),
            "output_blend": str(output_blend),
            "debug_dir": str(debug_dir),
            "optimizer": profile["placement"].get("optimizer"),
            "opencv_role": "metrics only; object movement is real Blender transform optimization",
        }
    )
    return {
        "status": "planned",
        "run_id": args.run_id,
        "profile": profile,
        "source_blend": str(local_path(args.source_blend)),
        "object_name": args.object_name,
        "target_mask": str(target_mask),
        "steps": steps,
    }


def execute_pipeline(plan: dict[str, Any]) -> dict[str, Any]:
    status = "ok"
    for step in plan["steps"]:
        command = step.get("command")
        if not command:
            continue
        result = run_command(command)
        step.update(result)
        step["status"] = "ok" if result["returncode"] == 0 else "error"
        if result["returncode"] != 0:
            status = "error"
            break
    plan["status"] = status
    return plan


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    plan = build_pipeline(args)
    if args.run:
        plan = execute_pipeline(plan)
    report_path = local_path(args.report_json) if args.report_json else local_path(args.results_root) / f"{args.run_id}_attachment_pipeline.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
