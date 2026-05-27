from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_person_manifest import slug


def batch_paths(batch_id: str) -> dict[str, Path]:
    batch_slug = slug(batch_id) or "cached-lipsync"
    result_slug = batch_slug.replace("-", "_")
    return {
        "requests": Path(f"config/person_factory.{batch_slug}.requests.json"),
        "manifest": Path(f"config/person_factory.{batch_slug}.json"),
        "result": Path(f"results/batch_person_factory_{result_slug}_latest.json"),
        "gallery": Path(f"outputs/batch/person_factory_{batch_slug}.html"),
        "summary": Path(f"results/finalize_person_factory_{result_slug}_latest.json"),
        "promotion": Path(f"results/promote_batch_{result_slug}_latest.json"),
        "matrix_report": Path(f"results/render_matrix_batch_{result_slug}.json"),
        "validation": Path(f"results/godot_lipsync_validation_{result_slug}_latest.json"),
        "combined_summary": Path("results/person_factory_all_latest.json"),
        "combined_gallery": Path("outputs/batch/person_factory_all.html"),
        "combined_contact": Path("outputs/batch/person_factory_all_contact_sheet.html"),
        "report": Path(f"results/run_cached_lipsync_batch_{result_slug}.json"),
    }


def path_arg(path: Path) -> str:
    return path.as_posix()


def resolve_optimization_profile(selected: str, render_profile: str) -> str:
    if selected != "auto":
        return selected
    return "rough_preview" if render_profile in {"rough_lipsync", "thumbnail_lipsync", "control_lipsync"} else "standard"


def build_commands(
    *,
    batch_id: str,
    count: int,
    accessories: str,
    bases: str,
    animations: str,
    text: str,
    audio_cache_key: str,
    lipsync_timeline: str,
    cache_lines: list[dict] | None = None,
    texture_size: int = 768,
    render_profile: str = "fast_lipsync",
    optimization_profile: str = "auto",
    start_index: int = 1,
    promote_after: bool = False,
    two_pass_promote: bool = False,
    skip_godot_export: bool = False,
    godot_url: str = "http://127.0.0.1:8790",
    validation_urls: str = "",
    gallery_detail_mode: str = "full",
) -> dict[str, list[str]]:
    paths = batch_paths(batch_id)
    resolved_optimization_profile = (
        "standard"
        if promote_after and not two_pass_promote and optimization_profile == "auto"
        else resolve_optimization_profile(optimization_profile, render_profile)
    )
    generate = [
        "python3",
        "scripts/build_cached_lipsync_requests.py",
        "--batch-id",
        batch_id,
        "--count",
        str(count),
        "--accessories",
        accessories,
        "--bases",
        bases,
        "--animations",
        animations,
        "--text",
        text,
        "--audio-cache-key",
        audio_cache_key,
        "--lipsync-timeline",
        lipsync_timeline,
        "--render-profile",
        render_profile,
        "--start-index",
        str(start_index),
        "--output",
        path_arg(paths["requests"]),
    ]
    if cache_lines:
        generate.extend(["--cache-lines-json", json.dumps(cache_lines, separators=(",", ":"))])

    commands = {
        "generate": generate,
        "render": [
            "python3",
            "scripts/render_matrix_batch.py",
            "--requests-json",
            path_arg(paths["requests"]),
            "--batch-id",
            batch_id,
            "--manifest",
            path_arg(paths["manifest"]),
            "--result",
            path_arg(paths["result"]),
            "--gallery",
            path_arg(paths["gallery"]),
            "--summary-json",
            path_arg(paths["summary"]),
            "--texture-size",
            str(texture_size),
            "--optimization-profile",
            resolved_optimization_profile,
            "--report-json",
            path_arg(paths["matrix_report"]),
            "--skip-finalize-review-assets",
            "--godot-url",
            godot_url,
        ],
        "validate": [
            "python3",
            "scripts/validate_godot_lipsync.py",
            "--id-prefix",
            f"{slug(batch_id)}-",
            "--batch-result",
            path_arg(paths["result"]),
            "--max-assets",
            str(count),
            "--wait-seconds",
            "0.0",
            "--output",
            path_arg(paths["validation"]),
        ],
        "batch_gallery": [
            "python3",
            "scripts/build_batch_gallery.py",
            path_arg(paths["result"]),
            path_arg(paths["gallery"]),
            "--godot-lipsync-validation",
            path_arg(paths["validation"]),
            "--detail-mode",
            gallery_detail_mode,
        ],
        "combined": [
            "python3",
            "scripts/build_combined_gallery.py",
            path_arg(paths["combined_gallery"]),
            "--summary-json",
            path_arg(paths["combined_summary"]),
            "--godot-lipsync-validation",
            path_arg(paths["validation"]),
        ],
        "contact": [
            "python3",
            "scripts/build_pose_contact_sheet.py",
            path_arg(paths["combined_summary"]),
            path_arg(paths["combined_contact"]),
        ],
    }
    if skip_godot_export:
        commands["render"].append("--skip-godot-export")
    if validation_urls:
        commands["validate"].extend(["--control-urls", validation_urls])
    else:
        commands["validate"].extend(["--control-url", godot_url])
    if promote_after and two_pass_promote:
        commands["promote"] = [
            "python3",
            "scripts/promote_batch_assets.py",
            path_arg(paths["result"]),
            "--gallery",
            path_arg(paths["gallery"]),
            "--summary-json",
            path_arg(paths["promotion"]),
            "--texture-size",
            str(texture_size),
            "--godot-url",
            godot_url,
            "--skip-combined",
        ]
    return commands


def batch_urls(batch_id: str) -> dict[str, str]:
    batch_slug = slug(batch_id) or "cached-lipsync"
    return {
        "batch_gallery": f"http://127.0.0.1:8780/person_factory_{batch_slug}.html",
        "batch_contact": f"http://127.0.0.1:8780/person_factory_{batch_slug}_contact_sheet.html",
        "combined_gallery": "http://127.0.0.1:8780/person_factory_all.html",
        "combined_contact": "http://127.0.0.1:8780/person_factory_all_contact_sheet.html",
    }


def run_checked(command: list[str]) -> dict:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, text=True)
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return {
        "command": command,
        "elapsed_seconds": round(elapsed, 3),
        "returncode": completed.returncode,
        "status": "ok",
    }


def stage_timing_summary(stages: list[dict]) -> dict:
    completed = [stage for stage in stages if isinstance(stage.get("elapsed_seconds"), int | float)]
    total = round(sum(float(stage["elapsed_seconds"]) for stage in completed), 3)
    slowest = max(completed, key=lambda stage: float(stage["elapsed_seconds"]), default={})
    return {
        "stage_count": len(stages),
        "completed_stage_count": len(completed),
        "total_stage_seconds": total,
        "slowest_stage": slowest.get("name", ""),
        "slowest_stage_seconds": round(float(slowest.get("elapsed_seconds", 0.0) or 0.0), 3),
        "stages": [
            {
                "name": stage.get("name", ""),
                "elapsed_seconds": round(float(stage.get("elapsed_seconds", 0.0) or 0.0), 3),
                "percent": round((float(stage.get("elapsed_seconds", 0.0) or 0.0) / total) * 100, 1)
                if total
                else 0.0,
                "status": stage.get("status", ""),
            }
            for stage in stages
        ],
    }


def read_json(path: Path) -> dict:
    resolved = ROOT / path
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def write_report(path: Path, report: dict) -> None:
    resolved = ROOT / path
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_pipeline(
    *,
    batch_id: str,
    count: int,
    accessories: str,
    bases: str,
    animations: str,
    text: str,
    audio_cache_key: str,
    lipsync_timeline: str,
    cache_lines: list[dict] | None = None,
    texture_size: int = 768,
    render_profile: str = "fast_lipsync",
    optimization_profile: str = "auto",
    start_index: int = 1,
    dry_run: bool = False,
    promote_after: bool = False,
    two_pass_promote: bool = False,
    publish_combined: bool = True,
    godot_url: str = "http://127.0.0.1:8790",
    validation_urls: str = "",
    skip_godot_export: bool = False,
    gallery_detail_mode: str = "full",
) -> dict:
    paths = batch_paths(batch_id)
    commands = build_commands(
        batch_id=batch_id,
        count=count,
        accessories=accessories,
        bases=bases,
        animations=animations,
        text=text,
        audio_cache_key=audio_cache_key,
        lipsync_timeline=lipsync_timeline,
        cache_lines=cache_lines,
        texture_size=texture_size,
        render_profile=render_profile,
        optimization_profile=optimization_profile,
        start_index=start_index,
        promote_after=promote_after,
        two_pass_promote=two_pass_promote,
        skip_godot_export=skip_godot_export,
        godot_url=godot_url,
        validation_urls=validation_urls,
        gallery_detail_mode=gallery_detail_mode,
    )
    stages = ["generate", "render"]
    if promote_after and two_pass_promote:
        stages.append("promote")
    stages.extend(["validate", "batch_gallery"])
    if publish_combined:
        stages.extend(["combined", "contact"])
    report = {
        "status": "dry-run" if dry_run else "running",
        "batch_id": batch_id,
        "count": count,
        "promote_after": promote_after,
        "promotion_mode": "two-pass" if promote_after and two_pass_promote else (
            "single-pass-standard" if promote_after else "none"
        ),
        "publish_combined": publish_combined,
        "paths": {key: path_arg(value) for key, value in paths.items()},
        "urls": batch_urls(batch_id),
        "commands": commands,
        "stages": [],
    }
    write_report(paths["report"], report)
    if dry_run:
        return report

    started = time.monotonic()
    for stage in stages:
        stage_report = {"name": stage, **run_checked(commands[stage])}
        report["stages"].append(stage_report)
        write_report(paths["report"], report)

    report.update(
        {
            "status": "ok",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stage_summary": stage_timing_summary(report["stages"]),
            "request": read_json(paths["requests"]),
            "finalize": read_json(paths["summary"]),
            "promotion": read_json(paths["promotion"]) if promote_after and two_pass_promote else {},
            "validation": read_json(paths["validation"]),
            "combined": read_json(paths["combined_summary"]) if publish_combined else {},
        }
    )
    write_report(paths["report"], report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate, render, validate, and publish a cached lip-sync batch.")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--accessories", default="aviator,pirate,necktie,cowboy,necklace")
    parser.add_argument("--bases", default="female,male")
    parser.add_argument("--animations", default="talk_idle,present_explain,listening_nod,confident_point")
    parser.add_argument("--text", required=True)
    parser.add_argument("--audio-cache-key", required=True)
    parser.add_argument("--lipsync-timeline", required=True)
    parser.add_argument("--cache-lines-json", default="")
    parser.add_argument("--texture-size", type=int, default=768)
    parser.add_argument("--render-profile", default="fast_lipsync")
    parser.add_argument("--optimization-profile", choices=["auto", "standard", "rough_preview"], default="auto")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--promote-after", action="store_true", help="Promote rough-preview assets before Godot validation.")
    parser.add_argument(
        "--two-pass-promote",
        action="store_true",
        help="Use the legacy rough-preview render followed by a separate standard promotion pass.",
    )
    parser.add_argument("--godot-url", default="http://127.0.0.1:8790")
    parser.add_argument("--validation-urls", default="", help="Comma-separated Godot control URLs for validation sharding.")
    parser.add_argument("--skip-godot-export", action="store_true", help="Skip chunk-local Godot reload/export; validation can load GLBs directly.")
    parser.add_argument(
        "--skip-combined-refresh",
        action="store_true",
        help="Skip global combined gallery/contact refresh; useful for child chunks that are merged by a parent job.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gallery-detail-mode", choices=["auto", "full", "compact"], default="auto")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gallery_detail_mode = args.gallery_detail_mode
    if gallery_detail_mode == "auto":
        gallery_detail_mode = "compact" if args.skip_combined_refresh else "full"
    report = run_pipeline(
        batch_id=args.batch_id,
        count=args.count,
        accessories=args.accessories,
        bases=args.bases,
        animations=args.animations,
        text=args.text,
        audio_cache_key=args.audio_cache_key,
        lipsync_timeline=args.lipsync_timeline,
        cache_lines=json.loads(args.cache_lines_json) if args.cache_lines_json else None,
        texture_size=args.texture_size,
        render_profile=args.render_profile,
        optimization_profile=args.optimization_profile,
        start_index=args.start_index,
        dry_run=args.dry_run,
        promote_after=args.promote_after,
        two_pass_promote=args.two_pass_promote,
        publish_combined=not args.skip_combined_refresh,
        godot_url=args.godot_url,
        validation_urls=args.validation_urls,
        skip_godot_export=args.skip_godot_export,
        gallery_detail_mode=gallery_detail_mode,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
