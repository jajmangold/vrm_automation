from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_CONFIG_PATH = ROOT / "config" / "poly_pizza_assets.json"
FATAL_LOG_MARKERS = ("Traceback (most recent call last):", "Error: Python:")


def load_manifest(path: Path | str) -> dict:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    jobs = manifest.get("jobs")
    if not jobs:
        raise ValueError("manifest must contain at least one job")
    for job in jobs:
        if not job.get("id"):
            raise ValueError("each job requires an id")
    return manifest


def normalized_asset_path(value: str) -> str:
    cleaned = value.strip()
    cleaned = cleaned.removeprefix("/workspace/")
    return cleaned.replace("\\", "/")


def catalog_fit_overrides_for_outfit(outfit_model: str | None, config_path: Path = ASSET_CONFIG_PATH) -> dict:
    if not outfit_model or not config_path.exists():
        return {}
    requested = normalized_asset_path(outfit_model)
    requested_name = Path(requested).name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for asset in config.get("assets", []):
        output_path = normalized_asset_path(str(asset.get("output_path", "")))
        if not output_path:
            continue
        if requested == output_path or requested.endswith(output_path) or Path(output_path).name == requested_name:
            return dict(asset.get("fit_overrides") or {})
    return {}


def job_or_catalog_value(job: dict, job_key: str, catalog: dict, catalog_key: str):
    value = job.get(job_key)
    if value is not None:
        return value
    return catalog.get(catalog_key)


def planned_job_environment(manifest: dict, job: dict) -> dict[str, str]:
    defaults = manifest.get("defaults", {})
    job_id = job["id"]
    output_prefix = job.get("output_prefix", f"/workspace/outputs/batch/{job_id}")
    report_prefix = job.get("report_prefix", f"/workspace/results/batch/{job_id}")
    export_vrm = str(job.get("export_vrm", defaults.get("export_vrm", "1"))) == "1"
    catalog_overrides = catalog_fit_overrides_for_outfit(job.get("outfit_model"))

    env = {
        "INPUT_MODEL": job.get("model_path", defaults.get("model_path", "/workspace/input/model.vrm")),
        "ANIMATION_REPORT_JSON": f"{report_prefix}_animation.json",
        "OUTPUT_BLEND": f"{output_prefix}.blend",
        "OUTPUT_GLB": f"{output_prefix}.glb",
        "OUTPUT_VRM": f"{output_prefix}.vrm" if export_vrm else "",
        "EXPORT_BLEND": str(job.get("export_blend", defaults.get("export_blend", "1"))),
        "EXPORT_GLB": str(job.get("export_glb", defaults.get("export_glb", "1"))),
        "ANIMATION_PRESET": job.get("animation_preset", defaults.get("animation_preset", "wave")),
        "FACIAL_PRESET": job.get("facial_preset", defaults.get("facial_preset", "")),
        "LIPSYNC_TIMELINE_JSON": job.get("lipsync_timeline_json", defaults.get("lipsync_timeline_json", "")),
        "RENDER_DIR": f"/workspace/outputs/batch/{job_id}_pose_renders",
        "RENDER_ANGLES": job.get("render_angles", defaults.get("render_angles", "front,side,three_quarter")),
        "RENDER_POSE_FRAMES": job.get("render_pose_frames", defaults.get("render_pose_frames", "")),
        "RENDER_POSE_STILLS": str(job.get("render_pose_stills", defaults.get("render_pose_stills", "1"))),
        "RENDER_ENGINE": job.get("render_engine", defaults.get("render_engine", "BLENDER_WORKBENCH")),
        "RENDER_COMPACT_ARMS": str(job.get("render_compact_arms", defaults.get("render_compact_arms", "0"))),
        "RENDER_PORTRAIT_LENS": str(job.get("render_portrait_lens", defaults.get("render_portrait_lens", "72"))),
        "RENDER_WIDTH": str(job.get("render_width", defaults.get("render_width", "768"))),
        "RENDER_HEIGHT": str(job.get("render_height", defaults.get("render_height", "1152"))),
        "ADD_OUTFIT_PROBE": "0" if job.get("outfit_model") else str(job.get("add_outfit_probe", defaults.get("add_outfit_probe", "1"))),
    }
    if job.get("outfit_model"):
        env["OUTFIT_MODEL"] = job["outfit_model"]
    if job.get("category"):
        env["OUTFIT_CATEGORY"] = job["category"]

    env_mapping = {
        "OUTFIT_SCALE_AXIS": ("outfit_scale_axis", "scale_axis"),
        "OUTFIT_TARGET_SIZE_RATIO": ("outfit_target_size_ratio", "target_size_ratio"),
        "OUTFIT_VERTICAL_CENTER_RATIO": ("outfit_vertical_center_ratio", "vertical_center_ratio"),
        "OUTFIT_HORIZONTAL_CENTER_OFFSET_RATIO": (
            "outfit_horizontal_center_offset_ratio",
            "horizontal_center_offset_ratio",
        ),
        "OUTFIT_SURFACE_OFFSET_RATIO": ("outfit_surface_offset_ratio", "surface_offset_ratio"),
        "OUTFIT_ANCHOR_Z_PERCENTILE": ("outfit_anchor_z_percentile", "anchor_z_percentile"),
        "OUTFIT_ROTATION_X_DEGREES": ("outfit_rotation_x_degrees", "rotation_x_degrees"),
        "OUTFIT_ROTATION_Y_DEGREES": ("outfit_rotation_y_degrees", "rotation_y_degrees"),
        "OUTFIT_ROTATION_Z_DEGREES": ("outfit_rotation_z_degrees", "rotation_z_degrees"),
        "OUTFIT_SURFACE_CONFORMER": ("outfit_surface_conformer", "surface_conformer"),
        "OUTFIT_SURFACE_CONFORM_RATIO": ("outfit_surface_conform_ratio", "surface_conform_ratio"),
        "OUTFIT_SURFACE_CONFORM_EXPONENT": ("outfit_surface_conform_exponent", "surface_conform_exponent"),
        "OUTFIT_SURFACE_CONFORM_PIN_TOP_RATIO": (
            "outfit_surface_conform_pin_top_ratio",
            "surface_conform_pin_top_ratio",
        ),
        "OUTFIT_SURFACE_SNAP": ("outfit_surface_snap", "surface_snap"),
        "OUTFIT_SURFACE_SNAP_GAP_RATIO": ("outfit_surface_snap_gap_ratio", "surface_snap_gap_ratio"),
        "OUTFIT_ANCHOR": ("outfit_anchor", "anchor"),
        "OUTFIT_FIT_SCOPE": ("outfit_fit_scope", "fit_scope"),
        "OUTFIT_GEOMETRY_CONDITIONER": ("outfit_geometry_conditioner", "geometry_conditioner"),
    }
    for env_key, (job_key, catalog_key) in env_mapping.items():
        value = job_or_catalog_value(job, job_key, catalog_overrides, catalog_key)
        if value is not None:
            env[env_key] = str(value)

    front_offset = job_or_catalog_value(job, "front_offset_ratio", catalog_overrides, "front_offset_ratio")
    if front_offset is not None:
        env["OUTFIT_FRONT_OFFSET_RATIO"] = str(front_offset)

    offset = job_or_catalog_value(job, "outfit_anchor_offset", catalog_overrides, "anchor_offset")
    if offset:
        env["OUTFIT_ANCHOR_OFFSET_X"] = str(offset[0])
        env["OUTFIT_ANCHOR_OFFSET_Y"] = str(offset[1])
        env["OUTFIT_ANCHOR_OFFSET_Z"] = str(offset[2])
    exclude_materials = job_or_catalog_value(job, "outfit_exclude_materials", catalog_overrides, "exclude_materials")
    if exclude_materials:
        env["OUTFIT_EXCLUDE_MATERIALS"] = ",".join(exclude_materials)
    return env


def workspace_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute() and str(path).startswith("/workspace/"):
        return ROOT / str(path).removeprefix("/workspace/")
    return path if path.is_absolute() else ROOT / path


def fatal_log_markers(stdout: str) -> list[str]:
    return [marker for marker in FATAL_LOG_MARKERS if marker in stdout]


def validate_animation_report(report_path_value: str | None) -> tuple[dict | None, list[str]]:
    report_path = workspace_path(report_path_value)
    if report_path is None:
        return None, ["missing-animation-report-path"]
    if not report_path.exists():
        return None, [f"missing-animation-report:{report_path}"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"invalid-animation-report-json:{exc.msg}"]
    if isinstance(report, dict) and report.get("status") == "error":
        return report, ["animation-report-status:error"]
    return report if isinstance(report, dict) else None, [] if isinstance(report, dict) else ["invalid-animation-report-shape"]


def run_job(manifest: dict, job: dict, dry_run: bool = False) -> dict:
    env = planned_job_environment(manifest, job)
    result = {
        "id": job["id"],
        "metadata": {
            "display_name": job.get("display_name", job["id"].replace("-", " ").title()),
            "license": job.get("license"),
            "persona": job.get("persona"),
            "source_url": job.get("source_url"),
            "tags": job.get("tags", []),
            "notes": job.get("notes"),
        },
        "environment": env,
        "status": "planned" if dry_run else "pending",
    }
    if dry_run:
        return result

    command_env = os.environ.copy()
    command_env.update(env)
    completed = subprocess.run(
        ["docker", "compose", "--profile", "tools", "run", "--rm", "animate-smoke"],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    result["returncode"] = completed.returncode
    result["log_tail"] = completed.stdout.splitlines()[-80:]

    errors = []
    if completed.returncode != 0:
        errors.append(f"docker-returncode:{completed.returncode}")
    errors.extend(f"fatal-log-marker:{marker}" for marker in fatal_log_markers(completed.stdout))
    animation_report, report_errors = validate_animation_report(env.get("ANIMATION_REPORT_JSON"))
    errors.extend(report_errors)
    result["animation_report_status"] = animation_report.get("status") if animation_report else None
    result["validation_errors"] = errors
    result["status"] = "error" if errors else "ok"
    return result


def run_jobs(manifest: dict, dry_run: bool = False, workers: int = 1) -> list[dict]:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    jobs = manifest["jobs"]
    if dry_run or workers == 1 or len(jobs) == 1:
        return [run_job(manifest, job, dry_run=dry_run) for job in jobs]

    results: list[dict | None] = [None] * len(jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(run_job, manifest, job, dry_run): index for index, job in enumerate(jobs)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            results[future_to_index[future]] = future.result()
    return [result for result in results if result is not None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a person-factory batch manifest.")
    parser.add_argument("manifest", nargs="?", default="config/outfit_batch.example.json")
    parser.add_argument("legacy_output_json", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-json", default=None)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent jobs to run. Default: 1 for deterministic low-load serial execution.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = args.dry_run
    manifest_path = Path(args.manifest)
    output_path = Path(args.output_json or args.legacy_output_json or "results/batch_manifest_latest.json")

    manifest = load_manifest(manifest_path)
    results = run_jobs(manifest, dry_run=dry_run, workers=args.workers)
    output = {"manifest": str(manifest_path), "dry_run": dry_run, "workers": args.workers, "jobs": results}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))

    if any(job["status"] == "error" for job in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
