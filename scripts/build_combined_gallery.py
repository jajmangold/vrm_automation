from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_batch_gallery import build_gallery, compact_godot_lipsync_validation, godot_lipsync_validation_index
from scripts.character_catalog_index import write_character_catalog_index_from_payload
from scripts.lipsync_quality import lipsync_quality_tags, summarize_lipsync_validation
from scripts.lipsync_timeline_overrides import (
    apply_job_lipsync_overrides,
    apply_lipsync_timeline_override,
    load_lipsync_timeline_overrides,
)
from scripts.make_person_manifest import load_accessories


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BATCH_RESULTS = [
    Path("results/batch_person_factory_in_blender_latest.json"),
    Path("results/batch_person_factory_now_latest.json"),
    Path("results/batch_person_factory_next24_latest.json"),
    Path("results/batch_person_factory_quality_next12_latest.json"),
    Path("results/batch_person_factory_quality_torso_back2_latest.json"),
    Path("results/batch_person_factory_facial_presets2_latest.json"),
    Path("results/batch_person_factory_lipsync_phoneme1_latest.json"),
    Path("results/batch_person_factory_standard_anim5_latest.json"),
    Path("results/batch_person_factory_lipsync_stt1_latest.json"),
    Path("results/batch_person_factory_lipsync_rhubarb1_latest.json"),
]

DYNAMIC_BATCH_PATTERNS = [
    Path("results/batch_person_factory_*_latest.json"),
    Path("results/batch_person_factory_lip-*_latest.json"),
    Path("results/batch_person_factory_talk-*_latest.json"),
    Path("results/batch_person_factory_text-*_latest.json"),
    Path("results/batch_person_factory_web-*_latest.json"),
    Path("results/batch_person_factory_auto-*_latest.json"),
    Path("results/batch_person_factory_batch_*_latest.json"),
    Path("results/batch_person_factory_chunked_*_latest.json"),
    Path("results/batch_*_rerender_latest.json"),
    Path("results/batch_*_probe_latest.json"),
    Path("results/batch_*_validation_latest.json"),
    Path("results/batch_*_refresh_latest.json"),
]

DYNAMIC_BATCH_EXCLUDE_NAMES = {
    "batch_person_factory_cached_latest.json",
}


def root_relative(path: Path, root: Path) -> Path:
    return path if not path.is_absolute() else path.relative_to(root)


def discover_batch_results(root: Path = Path("."), defaults: list[Path] | None = None) -> list[Path]:
    paths = []
    seen = set()

    def add(path: Path) -> None:
        normalized = root_relative(path, root)
        key = normalized.as_posix()
        if key in seen:
            return
        seen.add(key)
        paths.append(normalized)

    for path in defaults or DEFAULT_BATCH_RESULTS:
        add(path)
    for pattern in DYNAMIC_BATCH_PATTERNS:
        search_dir = root / pattern.parent
        if not search_dir.exists():
            continue
        for path in sorted(search_dir.glob(pattern.name)):
            if path.name in DYNAMIC_BATCH_EXCLUDE_NAMES:
                continue
            add(path.relative_to(root))
    return paths


def discover_godot_lipsync_validation_results(root: Path = Path(".")) -> list[Path]:
    results_dir = root / "results"
    if not results_dir.exists():
        return []
    latest = results_dir / "godot_lipsync_validation_latest.json"
    discovered = [
        path.relative_to(root)
        for path in sorted(results_dir.glob("godot_lipsync_validation*_latest.json"))
    ]
    ordered = []
    if latest.exists():
        ordered.append(latest.relative_to(root))
    for path in discovered:
        if path not in ordered:
            ordered.append(path)
    return ordered


def batch_result_run_report_path(path: Path) -> Path | None:
    name = path.name
    prefix = "batch_person_factory_"
    suffix = "_latest.json"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    run_slug = name.removeprefix(prefix).removesuffix(suffix)
    return path.with_name(f"run_cached_lipsync_batch_{run_slug}.json")


def is_publishable_batch_result(path: Path, *, root: Path = Path(".")) -> bool:
    report_path = batch_result_run_report_path(path)
    if report_path is None:
        return True
    resolved_report = root / report_path if not report_path.is_absolute() else report_path
    if not resolved_report.exists():
        return True
    try:
        report = json.loads(resolved_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return report.get("status") == "ok"


def publishable_batch_results(paths: list[Path], *, root: Path = Path(".")) -> list[Path]:
    return [path for path in paths if is_publishable_batch_result(path, root=root)]


def rejected_asset_keys_from_config(config_path: Path = Path("config/poly_pizza_assets.json")) -> set[str]:
    if not config_path.exists():
        return set()
    return {
        accessory["key"]
        for accessory in load_accessories(config_path, include_qualities={"reject"})
    }


def asset_anchor_tag_overlays_from_config(config_path: Path = Path("config/poly_pizza_assets.json")) -> dict[str, list[str]]:
    if not config_path.exists():
        return {}
    overlays = {}
    for accessory in load_accessories(config_path, include_qualities={"ship", "review", "fix", "reject"}):
        anchor_tags = [
            tag
            for tag in accessory.get("tags", [])
            if tag == "calibration:image-guided-anchor"
            or tag.startswith("anchor:")
            or tag.startswith("anchor-validation:")
            or tag.startswith("quality:")
        ]
        if anchor_tags:
            overlays[accessory["key"]] = anchor_tags
    return overlays


def refresh_anchor_tags(tags: list[str], overlays: dict[str, list[str]] | None) -> list[str]:
    if not overlays:
        return tags
    matching_keys = [key for key in overlays if key in tags]
    if not matching_keys:
        return tags
    refreshed = [
        tag
        for tag in tags
        if tag != "calibration:image-guided-anchor"
        and not tag.startswith("anchor:")
        and not tag.startswith("anchor-validation:")
        and not tag.startswith("quality:")
    ]
    for key in matching_keys:
        for tag in overlays[key]:
            if tag not in refreshed:
                refreshed.append(tag)
    return refreshed


def load_godot_lipsync_validation(path: Path = Path("results/godot_lipsync_validation_latest.json")) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_godot_lipsync_validations(paths: list[Path]) -> dict:
    return merge_godot_lipsync_validations(
        [load_godot_lipsync_validation(path) for path in paths]
    )


def merge_godot_lipsync_validations(reports: list[dict]) -> dict:
    checked_by_id: dict[str, dict] = {}
    order: list[str] = []
    issues = set()
    candidate_count = 0
    quality_review_count = 0
    transports: list[dict] = []

    for report in reports:
        if not isinstance(report, dict) or not report:
            continue
        candidate_count += int(report.get("candidate_count", 0) or 0)
        quality_review_count += int(report.get("quality_review_count", 0) or 0)
        issues.update(str(issue) for issue in report.get("issues", []) if str(issue))
        transport = report.get("validation_transport", {})
        if isinstance(transport, dict) and transport:
            transports.append(transport)
        for item in report.get("checked", []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "")).strip()
            if not item_id:
                continue
            if item_id not in checked_by_id:
                order.append(item_id)
            checked_by_id[item_id] = compact_godot_lipsync_validation(item)

    checked = [checked_by_id[item_id] for item_id in order if item_id in checked_by_id]
    if any(item.get("status") != "ok" for item in checked):
        issues.add("asset-review")
    merged = {
        "status": "ok" if checked and not issues else "review",
        "candidate_count": candidate_count,
        "checked_count": len(checked),
        "quality_review_count": quality_review_count,
        "issues": sorted(issues),
        "checked": checked,
    }
    if transports:
        modes = sorted({str(transport.get("mode", "")) for transport in transports if transport.get("mode")})
        merged["validation_transport"] = {
            "mode": modes[0] if len(modes) == 1 else "mixed",
            "modes": modes,
            "report_count": len(transports),
            "batch_request_count": sum(int(transport.get("batch_request_count") or 0) for transport in transports),
            "control_client_count_max": max(int(transport.get("control_client_count") or 0) for transport in transports),
            "fallback": any(bool(transport.get("fallback")) for transport in transports),
        }
    merged["summary"] = summarize_lipsync_validation(merged)
    return merged


def runtime_path_to_local(path: str | Path | None, root: Path = ROOT) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    if text.startswith("/workspace/"):
        return root / text.removeprefix("/workspace/")
    return Path(text)


def animation_report_lipsync_timeline(job: dict) -> str:
    environment = job.get("environment", {}) if isinstance(job.get("environment", {}), dict) else {}
    report_path = runtime_path_to_local(environment.get("ANIMATION_REPORT_JSON"))
    if not report_path or not report_path.exists():
        return ""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    lipsync = report.get("lipsync_animation", {})
    if not isinstance(lipsync, dict):
        return ""
    return str(lipsync.get("timeline", "")).strip()


def apply_lipsync_override_result(job: dict, result: dict, extra_tags: tuple[str, ...] = ()) -> dict:
    updated = dict(job)
    environment = dict(updated.get("environment", {}))
    metadata = dict(updated.get("metadata", {}))
    tags = list(metadata.get("tags", []))
    updated["lipsync_timeline_override"] = result["path"]
    updated["lipsync_timeline_override_source"] = result["source"]
    updated["lipsync_timeline_override_reason"] = result["reason"]
    updated["lipsync_timeline_json"] = result["path"]
    environment["LIPSYNC_TIMELINE_JSON"] = result["path"]
    for tag in ("lipsync-override:audio-derived", *extra_tags):
        if tag not in tags:
            tags.append(tag)
    metadata["tags"] = tags
    updated["environment"] = environment
    updated["metadata"] = metadata
    return updated


def validated_lipsync_rejected_asset_exception(job: dict, validation_by_id: dict[str, dict]) -> bool:
    validation = validation_by_id.get(str(job.get("id", "")))
    if not validation:
        return False
    if str(validation.get("status", "")) != "ok":
        return False
    if int(validation.get("cue_count", 0) or 0) <= 0:
        return False
    return bool(str(validation.get("timeline", "")).strip())


def combine_batch_results(
    paths: list[Path],
    rejected_asset_keys: set[str] | None = None,
    godot_lipsync_validation: dict | None = None,
    lipsync_timeline_overrides: dict[str, dict[str, str]] | None = None,
    asset_anchor_tag_overlays: dict[str, list[str]] | None = None,
) -> dict:
    sources = []
    jobs_by_id: dict[str, dict] = {}
    order: list[str] = []
    total_elapsed = 0.0
    rejected = rejected_asset_keys or set()
    filtered_job_count = 0
    validation_by_id = godot_lipsync_validation_index(godot_lipsync_validation or {})

    for path in paths:
        batch = json.loads(path.read_text(encoding="utf-8"))
        source_id = source_tag(path)
        jobs = batch.get("jobs", [])
        sources.append(
            {
                "path": str(path),
                "source_id": source_id,
                "job_count": len(jobs),
                "qa_summary": batch.get("qa_summary", {}),
            }
        )
        elapsed = batch.get("elapsed_seconds")
        if isinstance(elapsed, int | float):
            total_elapsed += float(elapsed)
        for job in jobs:
            updated = apply_job_lipsync_overrides(dict(job), lipsync_timeline_overrides)
            if lipsync_timeline_overrides and not updated.get("lipsync_timeline_override"):
                report_timeline = animation_report_lipsync_timeline(updated)
                override = apply_lipsync_timeline_override(report_timeline, lipsync_timeline_overrides)
                if override.get("changed"):
                    updated = apply_lipsync_override_result(
                        updated,
                        override,
                        extra_tags=("lipsync-override-from:animation-report",),
                    )
            metadata = dict(updated.get("metadata", {}))
            tags = list(metadata.get("tags", []))
            tags = refresh_anchor_tags(tags, asset_anchor_tag_overlays)
            if rejected and any(tag in rejected for tag in tags):
                if validated_lipsync_rejected_asset_exception(updated, validation_by_id):
                    tags.append("rejected-asset-kept:lipsync-validation")
                else:
                    filtered_job_count += 1
                    continue
            source_value = f"source:{source_id}"
            if source_value not in tags:
                tags.append(source_value)
            metadata["tags"] = tags
            updated["metadata"] = metadata
            if updated.get("id") not in jobs_by_id:
                order.append(updated.get("id", "unknown"))
            jobs_by_id[updated.get("id", "unknown")] = updated

    jobs = [jobs_by_id[job_id] for job_id in order if job_id in jobs_by_id]
    if godot_lipsync_validation:
        for job in jobs:
            validation = validation_by_id.get(str(job.get("id", "")))
            if not validation:
                continue
            metadata = dict(job.get("metadata", {}))
            tags = list(metadata.get("tags", []))
            override = apply_lipsync_timeline_override(
                validation.get("timeline"),
                lipsync_timeline_overrides,
            )
            if override.get("changed") and not job.get("lipsync_timeline_override"):
                job["lipsync_timeline_override"] = override["path"]
                job["lipsync_timeline_override_source"] = override["source"]
                job["lipsync_timeline_override_reason"] = override["reason"]
                job["lipsync_timeline_json"] = override["path"]
                environment = dict(job.get("environment", {}))
                environment["LIPSYNC_TIMELINE_JSON"] = override["path"]
                job["environment"] = environment
                for tag in (
                    "lipsync-override:audio-derived",
                    "lipsync-override-from:validation",
                ):
                    if tag not in tags:
                        tags.append(tag)
            validation_status = str(validation.get("status", "review"))
            for tag in (
                f"godot-lipsync:{validation_status}",
                "godot-lipsync-ok" if validation_status == "ok" else "godot-lipsync-review",
            ):
                if tag not in tags:
                    tags.append(tag)
            for tag in lipsync_quality_tags(validation.get("lipsync_quality", {})):
                if tag not in tags:
                    tags.append(tag)
            metadata["tags"] = tags
            job["metadata"] = metadata
    source_job_count = sum(source["job_count"] for source in sources)
    combined = {
        "status": "ok",
        "manifest": f"combined:{len(sources)}-sources",
        "elapsed_seconds": round(total_elapsed, 3),
        "batch_sources": sources,
        "source_job_count": source_job_count,
        "filtered_job_count": filtered_job_count,
        "deduped_job_count": source_job_count - filtered_job_count - len(jobs),
        "jobs": jobs,
    }
    if godot_lipsync_validation:
        combined["godot_lipsync_validation"] = godot_lipsync_validation
        combined["godot_lipsync_summary"] = summarize_lipsync_validation(godot_lipsync_validation)
    return combined


def source_tag(path: Path) -> str:
    stem = path.stem
    for prefix in ("batch_person_factory_", "batch_"):
        if stem.startswith(prefix):
            stem = stem.removeprefix(prefix)
    return stem.replace("_latest", "").replace("_", "-")


def combined_character_catalog_summary(job: dict, validation_by_id: dict[str, dict]) -> dict:
    metadata = dict(job.get("metadata", {}))
    qa = dict(job.get("qa", {}))
    environment = dict(job.get("environment", {}))
    job_id = str(job.get("id") or "unknown")
    validation = validation_by_id.get(job_id, {})
    quality = validation.get("lipsync_quality", {}) if isinstance(validation.get("lipsync_quality", {}), dict) else {}
    optimized_glb = ROOT / "outputs" / "batch_optimized" / f"{job_id}.glb"
    game_glb = ROOT / "godot_viewer" / "game_assets" / "glb" / f"{job_id}.glb"
    return {
        "id": job_id,
        "display_name": metadata.get("display_name") or job_id.replace("-", " ").title(),
        "persona": metadata.get("persona") or "",
        "notes": metadata.get("notes") or "",
        "status": job.get("status") or "unknown",
        "animation": str(environment.get("ANIMATION_PRESET") or "unknown"),
        "category": str(environment.get("OUTFIT_CATEGORY") or "none"),
        "tags": sorted({str(tag) for tag in metadata.get("tags", []) if str(tag).strip()}),
        "qa": {
            "grade": qa.get("qa_grade"),
            "score": qa.get("qa_score"),
            "priority": qa.get("review_priority"),
            "flags": qa.get("qa_flags", []),
        },
        "lipsync": {
            "status": validation.get("status") or "unchecked",
            "grade": quality.get("grade"),
            "cue_count": validation.get("cue_count") or quality.get("cue_count") or 0,
            "duration": quality.get("duration") or 0,
            "active_visemes": quality.get("active_visemes", []),
            "missing_visemes": quality.get("missing_expected_active_visemes", []),
            "source_mode": quality.get("source_mode") or "",
            "timeline": validation.get("timeline") or "",
        },
        "has_game_asset": game_glb.exists(),
        "has_optimized_glb": optimized_glb.exists(),
        "review_image": "",
        "links": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one combined review gallery from multiple batch results.")
    parser.add_argument("output", nargs="?", default="outputs/batch/person_factory_all.html")
    parser.add_argument("batch_results", nargs="*")
    parser.add_argument("--asset-config", default="config/poly_pizza_assets.json")
    parser.add_argument("--include-rejected-assets", action="store_true")
    parser.add_argument("--summary-json", default="results/person_factory_all_latest.json")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Write the combined summary JSON without rebuilding the static HTML gallery.",
    )
    parser.add_argument(
        "--character-index-json",
        default="",
        help="Optional compact character API index JSON to write from the combined summary.",
    )
    parser.add_argument(
        "--godot-lipsync-validation",
        action="append",
        default=None,
        help="Godot lip-sync validation JSON. May be passed multiple times; reports are merged by asset id.",
    )
    parser.add_argument("--lipsync-overrides", default="config/lipsync_timeline_overrides.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [Path(path) for path in args.batch_results] if args.batch_results else discover_batch_results()
    existing = publishable_batch_results([path for path in paths if path.exists()])
    if not existing:
        raise SystemExit("no batch result files found")

    rejected_asset_keys = set() if args.include_rejected_assets else rejected_asset_keys_from_config(Path(args.asset_config))
    validation_paths = [Path(path) for path in args.godot_lipsync_validation] if args.godot_lipsync_validation else discover_godot_lipsync_validation_results()
    combined = combine_batch_results(
        existing,
        rejected_asset_keys=rejected_asset_keys,
        godot_lipsync_validation=load_godot_lipsync_validations(validation_paths),
        lipsync_timeline_overrides=load_lipsync_timeline_overrides(Path(args.lipsync_overrides)),
        asset_anchor_tag_overlays=asset_anchor_tag_overlays_from_config(Path(args.asset_config)),
    )
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(combined, indent=2, sort_keys=True), encoding="utf-8")
    if args.character_index_json:
        write_character_catalog_index_from_payload(
            combined,
            source_path=summary_path,
            output_path=Path(args.character_index_json),
            root=ROOT,
            summarize_job=combined_character_catalog_summary,
        )
    if args.summary_only:
        print(summary_path)
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_gallery(combined, output_path, detail_mode="compact"), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
