from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.finalize_batch import finalize_batch


def batch_id_from_result_path(path: Path) -> str:
    stem = path.stem
    for prefix in ("batch_person_factory_", "batch_"):
        if stem.startswith(prefix):
            stem = stem.removeprefix(prefix)
            break
    if stem.endswith("_latest"):
        stem = stem.removesuffix("_latest")
    return stem.replace("_", "-") or "batch"


def result_slug(batch_id: str) -> str:
    return batch_id.replace("-", "_")


def default_paths(batch_result: Path) -> dict[str, Path | str]:
    batch_id = batch_id_from_result_path(batch_result)
    slug = result_slug(batch_id)
    return {
        "batch_id": batch_id,
        "gallery": Path(f"outputs/batch/person_factory_{batch_id}.html"),
        "summary": Path(f"results/promote_batch_{slug}_latest.json"),
        "optimized_dir": Path("outputs/batch_optimized"),
        "combined_gallery": Path("outputs/batch/person_factory_all.html"),
        "combined_summary": Path("results/person_factory_all_latest.json"),
    }


def root_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_root_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def run_combined_gallery(output: Path, summary_json: Path) -> dict:
    command = [
        "python3",
        "scripts/build_combined_gallery.py",
        root_relative(output),
        "--summary-json",
        root_relative(summary_json),
    ]
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, text=True)
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "command": command,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def promote_batch_assets(
    batch_result: Path,
    *,
    gallery_path: Path | None = None,
    optimized_dir: Path | None = None,
    summary_path: Path | None = None,
    combined_gallery_path: Path | None = None,
    combined_summary_path: Path | None = None,
    texture_size: int = 768,
    texture_compress: str = "auto",
    geometry_compress: str = "false",
    export_godot: bool = True,
    godot_url: str = "http://127.0.0.1:8790",
    godot_skip_existing: bool = True,
    skip_existing_optimized: bool = True,
    rebuild_combined: bool = True,
    dry_run: bool = False,
) -> dict:
    defaults = default_paths(batch_result)
    resolved_batch = resolve_root_path(batch_result)
    resolved_gallery = resolve_root_path(gallery_path or defaults["gallery"])
    resolved_optimized_dir = resolve_root_path(optimized_dir or defaults["optimized_dir"])
    resolved_summary = resolve_root_path(summary_path or defaults["summary"])
    resolved_combined_gallery = resolve_root_path(combined_gallery_path or defaults["combined_gallery"])
    resolved_combined_summary = resolve_root_path(combined_summary_path or defaults["combined_summary"])

    report = {
        "status": "dry-run" if dry_run else "running",
        "batch_id": defaults["batch_id"],
        "batch_result": root_relative(resolved_batch),
        "gallery": root_relative(resolved_gallery),
        "optimized_dir": root_relative(resolved_optimized_dir),
        "summary_json": root_relative(resolved_summary),
        "combined_gallery": root_relative(resolved_combined_gallery) if rebuild_combined else None,
        "combined_summary": root_relative(resolved_combined_summary) if rebuild_combined else None,
        "promotion_profile": "standard",
        "texture_size": texture_size,
        "texture_compress": texture_compress,
        "geometry_compress": geometry_compress,
        "export_godot": export_godot,
        "skip_existing_optimized": skip_existing_optimized,
        "stages": {},
    }
    resolved_summary.parent.mkdir(parents=True, exist_ok=True)
    resolved_summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if dry_run:
        return report

    started = time.monotonic()
    finalize_started = time.monotonic()
    finalize_summary = finalize_batch(
        resolved_batch,
        resolved_gallery,
        optimized_dir=resolved_optimized_dir,
        summary_path=resolved_summary,
        texture_size=texture_size,
        texture_compress=texture_compress,
        geometry_compress=geometry_compress,
        optimization_profile="standard",
        skip_existing_optimized=skip_existing_optimized,
        export_godot=export_godot,
        godot_url=godot_url,
        godot_skip_existing=godot_skip_existing,
    )
    report["stages"]["finalize"] = {
        "status": finalize_summary.get("status", "review"),
        "elapsed_seconds": round(time.monotonic() - finalize_started, 3),
    }
    report["finalize"] = finalize_summary
    report["optimization"] = finalize_summary.get("optimization")

    if rebuild_combined:
        combined = run_combined_gallery(resolved_combined_gallery, resolved_combined_summary)
        report["stages"]["combined"] = combined
        if combined["status"] != "ok":
            report["status"] = "review"

    if report.get("status") != "review":
        report["status"] = "ok" if finalize_summary.get("status") == "ok" else "review"
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    resolved_summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a fast QA batch to standard-optimized assets.")
    parser.add_argument("batch_result")
    parser.add_argument("--gallery")
    parser.add_argument("--optimized-dir")
    parser.add_argument("--summary-json")
    parser.add_argument("--combined-gallery")
    parser.add_argument("--combined-summary")
    parser.add_argument("--texture-size", type=int, default=768)
    parser.add_argument("--texture-compress", default="auto")
    parser.add_argument("--geometry-compress", default="false")
    parser.add_argument("--godot-url", default="http://127.0.0.1:8790")
    parser.add_argument("--skip-godot-export", action="store_true")
    parser.add_argument("--force-godot-export", action="store_true")
    parser.add_argument("--force-optimize", action="store_true")
    parser.add_argument("--skip-combined", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = promote_batch_assets(
        Path(args.batch_result),
        gallery_path=Path(args.gallery) if args.gallery else None,
        optimized_dir=Path(args.optimized_dir) if args.optimized_dir else None,
        summary_path=Path(args.summary_json) if args.summary_json else None,
        combined_gallery_path=Path(args.combined_gallery) if args.combined_gallery else None,
        combined_summary_path=Path(args.combined_summary) if args.combined_summary else None,
        texture_size=args.texture_size,
        texture_compress=args.texture_compress,
        geometry_compress=args.geometry_compress,
        export_godot=not args.skip_godot_export,
        godot_url=args.godot_url,
        godot_skip_existing=not args.force_godot_export,
        skip_existing_optimized=not args.force_optimize,
        rebuild_combined=not args.skip_combined,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] not in {"ok", "review", "dry-run"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
