from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_batch_gallery import build_gallery
from scripts.build_pose_contact_sheet import build_contact_sheet
from scripts.optimize_glb import ROOT, optimize_batch, to_workspace_path
from scripts.score_batch import score_batch


def default_contact_sheet_path(gallery_path: Path) -> Path:
    return gallery_path.with_name(f"{gallery_path.stem}_contact_sheet.html")


def batch_asset_ids(batch_result: dict) -> list[str]:
    output: list[str] = []
    jobs = batch_result.get("jobs", [])
    if not isinstance(jobs, list):
        return output
    for job in jobs:
        if not isinstance(job, dict):
            continue
        asset_id = str(job.get("id") or "").strip()
        if asset_id and asset_id not in output:
            output.append(asset_id)
    return output


def post_godot_export_all(
    godot_url: str,
    timeout: int = 120,
    *,
    skip_existing: bool = True,
    asset_ids: list[str] | None = None,
) -> dict:
    url = godot_url.rstrip("/") + "/export-all-game-assets"
    payload = {"skip_existing": skip_existing}
    if asset_ids is not None:
        payload["asset_ids"] = asset_ids
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_godot_reload_assets(
    godot_url: str,
    batch_result_path: Path | None = None,
    timeout: int = 120,
    *,
    scoped: bool = True,
) -> dict:
    url = godot_url.rstrip("/") + "/reload-assets"
    payload = {"scoped": scoped}
    if batch_result_path:
        payload["batch_result"] = to_workspace_path(batch_result_path, ROOT)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def finalize_batch(
    batch_path: Path,
    gallery_path: Path,
    *,
    optimized_dir: Path,
    summary_path: Path,
    optimize_assets: bool = True,
    score_assets: bool = True,
    export_godot: bool = False,
    godot_url: str = "http://127.0.0.1:8790",
    godot_skip_existing: bool = True,
    texture_size: int = 1024,
    texture_compress: str = "auto",
    geometry_compress: str = "false",
    optimization_profile: str = "standard",
    skip_existing_optimized: bool = False,
    build_gallery_asset: bool = True,
    build_contact_sheet_assets: bool = True,
    contact_sheet_path: Path | None = None,
) -> dict:
    resolved_contact_sheet_path = contact_sheet_path or default_contact_sheet_path(gallery_path)
    started = time.monotonic()
    summary = {
        "status": "ok",
        "batch_result": str(batch_path),
        "gallery": str(gallery_path) if build_gallery_asset else None,
        "contact_sheet": str(resolved_contact_sheet_path) if build_contact_sheet_assets else None,
        "optimized_dir": str(optimized_dir),
        "optimization": None,
        "qa_summary": None,
        "godot_reload": None,
        "godot_export": None,
        "timings": {},
    }

    if optimize_assets:
        optimize_started = time.monotonic()
        optimization_args = SimpleNamespace(
            texture_size=texture_size,
            texture_compress=texture_compress,
            geometry_compress=geometry_compress,
            preserve_sparse_accessors=False,
            profile=optimization_profile,
            skip_existing=skip_existing_optimized,
        )
        summary["optimization"] = optimize_batch(batch_path, optimized_dir, optimization_args)
        summary["timings"]["optimize_seconds"] = round(time.monotonic() - optimize_started, 3)
        if summary["optimization"].get("status") != "ok":
            summary["status"] = "review"

    batch_result = json.loads(batch_path.read_text(encoding="utf-8"))
    if score_assets:
        score_started = time.monotonic()
        batch_result = score_batch(batch_result)
        batch_path.write_text(json.dumps(batch_result, indent=2, sort_keys=True), encoding="utf-8")
        summary["qa_summary"] = batch_result.get("qa_summary")
        summary["timings"]["score_seconds"] = round(time.monotonic() - score_started, 3)

    if build_gallery_asset:
        gallery_started = time.monotonic()
        gallery_path.parent.mkdir(parents=True, exist_ok=True)
        gallery_path.write_text(build_gallery(batch_result, gallery_path), encoding="utf-8")
        summary["timings"]["gallery_seconds"] = round(time.monotonic() - gallery_started, 3)

    if build_contact_sheet_assets:
        contact_started = time.monotonic()
        resolved_contact_sheet_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_contact_sheet_path.write_text(
            build_contact_sheet(batch_result, resolved_contact_sheet_path),
            encoding="utf-8",
        )
        summary["timings"]["contact_sheet_seconds"] = round(time.monotonic() - contact_started, 3)

    if export_godot:
        current_asset_ids = batch_asset_ids(batch_result)
        godot_started = time.monotonic()
        summary["godot_reload"] = post_godot_reload_assets(godot_url, batch_path)
        summary["timings"]["godot_reload_seconds"] = round(time.monotonic() - godot_started, 3)
        godot_started = time.monotonic()
        summary["godot_export"] = post_godot_export_all(
            godot_url,
            skip_existing=godot_skip_existing,
            asset_ids=current_asset_ids,
        )
        summary["timings"]["godot_export_seconds"] = round(time.monotonic() - godot_started, 3)
        if summary["godot_reload"].get("status") != "ok" or summary["godot_export"].get("status") != "ok":
            summary["status"] = "review"

    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize a generated person batch for review/game export.")
    parser.add_argument("batch_result", nargs="?", default="results/batch_person_factory_in_blender_latest.json")
    parser.add_argument("gallery", nargs="?", default="outputs/batch/person_factory_review.html")
    parser.add_argument("--optimized-dir", default="outputs/batch_optimized")
    parser.add_argument("--summary-json", default="results/finalize_batch_latest.json")
    parser.add_argument("--skip-optimize", action="store_true")
    parser.add_argument("--skip-score", action="store_true")
    parser.add_argument("--export-godot", action="store_true")
    parser.add_argument("--godot-url", default="http://127.0.0.1:8790")
    parser.add_argument(
        "--force-godot-export",
        action="store_true",
        help="Re-export every known Godot asset instead of skipping current files.",
    )
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--texture-compress", default="auto")
    parser.add_argument("--geometry-compress", default="false")
    parser.add_argument(
        "--optimization-profile",
        choices=["standard", "rough_preview"],
        default="standard",
        help="Use rough_preview to copy GLBs for fast QA while preserving optimized output paths.",
    )
    parser.add_argument(
        "--skip-existing-optimized",
        action="store_true",
        help="Reuse optimized GLBs whose animation report metadata still matches the source and options.",
    )
    parser.add_argument("--skip-gallery", action="store_true")
    parser.add_argument("--contact-sheet", default="", help="Optional output path for the pose-render contact sheet.")
    parser.add_argument("--skip-contact-sheet", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = finalize_batch(
        Path(args.batch_result),
        Path(args.gallery),
        optimized_dir=Path(args.optimized_dir),
        summary_path=Path(args.summary_json),
        optimize_assets=not args.skip_optimize,
        score_assets=not args.skip_score,
        export_godot=args.export_godot,
        godot_url=args.godot_url,
        godot_skip_existing=not args.force_godot_export,
        texture_size=args.texture_size,
        texture_compress=args.texture_compress,
        geometry_compress=args.geometry_compress,
        optimization_profile=args.optimization_profile,
        skip_existing_optimized=args.skip_existing_optimized,
        build_gallery_asset=not args.skip_gallery,
        build_contact_sheet_assets=not args.skip_contact_sheet,
        contact_sheet_path=Path(args.contact_sheet) if args.contact_sheet else None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] not in {"ok", "review"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
