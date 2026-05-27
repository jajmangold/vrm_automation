from __future__ import annotations

import concurrent.futures
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.person_factory_jobs import (
    DEFAULTS,
    JobStore,
    build_matrix_cache_warm_jobs,
    build_matrix_warm_render_pipeline,
    build_text_person_command,
    generated_job_id,
    matrix_cache_preflight_plan,
    max_batch_jobs,
    max_chunked_matrix_jobs,
    normalize_bool,
    normalize_batch_job_requests,
    normalize_list,
    normalize_job_request,
    normalize_matrix_job_requests,
    slug,
    tail_lines,
)
from scripts.build_batch_gallery import build_gallery
from scripts.build_combined_gallery import combine_batch_results, merge_godot_lipsync_validations
from scripts.character_catalog_index import (
    build_character_catalog_payload as build_character_catalog_payload_base,
    write_character_catalog_index_from_payload as write_character_catalog_index_from_payload_base,
)
from scripts.lipsync_quality import analyze_lipsync_timeline
from scripts.make_person_manifest import ANIMATIONS, BASE_MODELS, load_accessories
from scripts.placement_api import placement_assets, placement_plan, placement_suggestion
from scripts.run_phrasebank_thumbnail_batch import (
    DEFAULT_ACCESSORIES as PHRASEBANK_THUMBNAIL_ACCESSORIES,
    DEFAULT_ANIMATIONS as PHRASEBANK_THUMBNAIL_ANIMATIONS,
    DEFAULT_BASES as PHRASEBANK_THUMBNAIL_BASES,
    DEFAULT_PHRASE_BANK,
    DEFAULT_RENDER_PROFILE as PHRASEBANK_THUMBNAIL_RENDER_PROFILE,
    load_phrasebank_cache_lines,
)
from scripts.run_cached_lipsync_batch import stage_timing_summary
from scripts.storage_audit import audit_storage


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs/batch"
WEBAPP_DIR = ROOT / "webapp"
JOB_STORE = JobStore(ROOT / "results/web_jobs/jobs.json")
LOG_DIR = ROOT / "logs/web_jobs"
JOB_MAX_CONCURRENT = int(os.environ.get("WEBAPP_MAX_CONCURRENT_JOBS", "1"))
JOB_SEMAPHORE = threading.BoundedSemaphore(JOB_MAX_CONCURRENT)
EXPECTED_VISEMES = ("aa", "ee", "ih", "oh", "ou")
DEFAULT_ACCESSORY_QUALITIES = {"ship"}
CHARACTER_CATALOG_CACHE: dict[str, object] = {"mtime": None, "payload": None}
CHARACTER_CATALOG_SCHEMA_VERSION = 3
RECENT_GALLERY_SUMMARY_CACHE: dict[str, dict] = {}
CHILD_CHUNK_BATCH_RE = re.compile(r"-chunk-\d{3}$")
RECENT_GALLERY_BENCHMARK_LIMIT = 24


def cached_lipsync_chunk_workers() -> int:
    try:
        requested = int(os.environ.get("PERSON_FACTORY_CHUNK_WORKERS", str(min(2, JOB_MAX_CONCURRENT))))
    except ValueError:
        requested = 1
    return max(1, min(requested, max(1, JOB_MAX_CONCURRENT)))


def render_chunk_workers() -> int:
    try:
        requested = int(os.environ.get("PERSON_FACTORY_RENDER_CHUNK_WORKERS", "2"))
    except ValueError:
        requested = 2
    return max(1, min(requested, cached_lipsync_chunk_workers()))


def cached_lipsync_pipeline_worker_count(pipeline: dict, jobs: list[dict]) -> int:
    if not jobs:
        return 1
    try:
        requested = int(pipeline.get("chunk_workers") or cached_lipsync_chunk_workers())
    except (TypeError, ValueError):
        requested = cached_lipsync_chunk_workers()
    return max(1, min(requested, len(jobs), cached_lipsync_chunk_workers()))


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def static_response(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        handler.send_error(404)
        return
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def selected_gallery() -> Path:
    preferred = os.environ.get("WEBAPP_GALLERY_FILE", "person_factory_all.html")
    for name in (
        preferred,
        "person_factory_all.html",
        "person_factory_review.html",
        "person_factory_gallery.html",
        "person_factory_in_blender_gallery.html",
    ):
        candidate = OUTPUT_DIR / name
        if candidate.exists():
            return candidate
    html_files = sorted(
        OUTPUT_DIR.glob("*.html"),
        key=lambda path: (-path.stat().st_mtime, path.name),
    )
    return html_files[0] if html_files else OUTPUT_DIR / "missing.html"


def batch_result_slug(batch_id: str) -> str:
    return batch_id.replace("-", "_")


def counted(values) -> dict:
    return dict(Counter(str(value) for value in values if value))


def derived_qa_summary(jobs: list[dict]) -> dict:
    grades = counted(
        job.get("qa", {}).get("qa_grade")
        for job in jobs
        if isinstance(job.get("qa"), dict)
    )
    priorities = counted(
        job.get("qa", {}).get("review_priority")
        for job in jobs
        if isinstance(job.get("qa"), dict)
    )
    return {
        "grades": grades,
        "review_count": sum(1 for job in jobs if job.get("qa", {}).get("review_priority") != "ship"),
        "ship_count": priorities.get("ship", 0),
    }


def derived_lipsync_counts(validation: dict) -> dict:
    summary = validation.get("summary", {}) if isinstance(validation.get("summary"), dict) else {}
    checked = validation.get("checked", []) if isinstance(validation.get("checked"), list) else []
    qualities = [
        item.get("lipsync_quality", {})
        for item in checked
        if isinstance(item, dict) and isinstance(item.get("lipsync_quality"), dict)
    ]
    grade_counts = validation.get("grade_counts") or summary.get("grade_counts") or counted(
        quality.get("grade") for quality in qualities
    )
    source_counts = validation.get("source_counts") or summary.get("source_counts") or counted(
        quality.get("source_mode") for quality in qualities
    )
    return {
        "checked_count": validation.get("checked_count") or summary.get("checked_count") or len(checked),
        "grade_counts": grade_counts,
        "source_counts": source_counts,
    }


def aggregate_child_render_cache(batch_id: str, result: dict) -> dict:
    render_cache = result.get("render_cache", {}) if isinstance(result.get("render_cache"), dict) else {}
    if render_cache:
        return {
            "hit_count": render_cache.get("hit_count", 0),
            "miss_count": render_cache.get("miss_count", 0),
        }
    chunked_parent = result.get("chunked_parent", {}) if isinstance(result.get("chunked_parent"), dict) else {}
    child_batch_ids = chunked_parent.get("child_batch_ids", []) if isinstance(chunked_parent.get("child_batch_ids"), list) else []
    totals = Counter()
    for child_id in child_batch_ids:
        child_report = read_json_if_exists(ROOT / "results" / f"render_matrix_batch_{batch_result_slug(str(child_id))}.json")
        child_cache = child_report.get("render_cache", {}) if isinstance(child_report.get("render_cache"), dict) else {}
        totals["hit_count"] += int(child_cache.get("hit_count", 0) or 0)
        totals["miss_count"] += int(child_cache.get("miss_count", 0) or 0)
    if totals:
        return {"hit_count": totals["hit_count"], "miss_count": totals["miss_count"]}
    jobs = result.get("jobs", []) if isinstance(result.get("jobs"), list) else []
    for job in jobs:
        cache = job.get("render_cache", {}) if isinstance(job.get("render_cache"), dict) else {}
        status = cache.get("status")
        if status == "hit":
            totals["hit_count"] += 1
        elif status in {"miss", "stored"}:
            totals["miss_count"] += 1
    return {"hit_count": totals["hit_count"], "miss_count": totals["miss_count"]}


def aggregate_child_validation_cache(result: dict, validation: dict) -> dict:
    validation_cache = validation.get("validation_cache", {}) if isinstance(validation.get("validation_cache"), dict) else {}
    if validation_cache:
        return {
            "hit_count": validation_cache.get("hit_count", 0),
            "miss_count": validation_cache.get("miss_count", 0),
        }
    chunked_parent = result.get("chunked_parent", {}) if isinstance(result.get("chunked_parent"), dict) else {}
    child_batch_ids = chunked_parent.get("child_batch_ids", []) if isinstance(chunked_parent.get("child_batch_ids"), list) else []
    totals = Counter()
    for child_id in child_batch_ids:
        child_validation = read_json_if_exists(
            ROOT / "results" / f"godot_lipsync_validation_{batch_result_slug(str(child_id))}_latest.json"
        )
        child_cache = (
            child_validation.get("validation_cache", {})
            if isinstance(child_validation.get("validation_cache"), dict)
            else {}
        )
        totals["hit_count"] += int(child_cache.get("hit_count", 0) or 0)
        totals["miss_count"] += int(child_cache.get("miss_count", 0) or 0)
    return {"hit_count": totals["hit_count"], "miss_count": totals["miss_count"]}


def derived_timing(result: dict, run: dict) -> dict:
    stage_summary = run.get("stage_summary", {}) if isinstance(run.get("stage_summary"), dict) else {}
    elapsed = run.get("elapsed_seconds", 0)
    slowest_stage = stage_summary.get("slowest_stage", "")
    slowest_stage_seconds = stage_summary.get("slowest_stage_seconds", 0)
    if elapsed or slowest_stage or slowest_stage_seconds:
        return {
            "elapsed_seconds": elapsed,
            "slowest_stage": slowest_stage,
            "slowest_stage_seconds": slowest_stage_seconds,
        }

    pipeline_timing = result.get("pipeline_timing", {}) if isinstance(result.get("pipeline_timing"), dict) else {}
    chunked_parent = result.get("chunked_parent", {}) if isinstance(result.get("chunked_parent"), dict) else {}
    if not pipeline_timing and isinstance(chunked_parent.get("pipeline_timing"), dict):
        pipeline_timing = chunked_parent["pipeline_timing"]
    child_reports = pipeline_timing.get("child_reports", []) if isinstance(pipeline_timing.get("child_reports"), list) else []
    slowest_child = max(
        (report for report in child_reports if isinstance(report, dict)),
        key=lambda report: float(report.get("elapsed_seconds", 0) or 0),
        default={},
    )
    return {
        "elapsed_seconds": pipeline_timing.get("wall_elapsed_seconds", result.get("elapsed_seconds", 0)),
        "slowest_stage": slowest_child.get("slowest_stage", ""),
        "slowest_stage_seconds": slowest_child.get("elapsed_seconds", 0),
        "pipeline_timing": {
            key: value
            for key, value in pipeline_timing.items()
            if key != "child_reports"
        },
    }


def file_signature(path: Path) -> tuple[float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


def recent_gallery_summary_paths(batch_id: str) -> dict[str, Path]:
    result_slug = batch_result_slug(batch_id)
    return {
        "result": ROOT / "results" / f"batch_person_factory_{result_slug}_latest.json",
        "validation": ROOT / "results" / f"godot_lipsync_validation_{result_slug}_latest.json",
        "run": ROOT / "results" / f"run_cached_lipsync_batch_{result_slug}.json",
        "outfits": ROOT / "config/poly_pizza_assets.json",
    }


def recent_gallery_summary_cache_key(batch_id: str) -> dict:
    paths = recent_gallery_summary_paths(batch_id)
    return {
        "batch_id": batch_id,
        "files": {name: file_signature(path) for name, path in paths.items()},
    }


def recent_gallery_summary(batch_id: str) -> dict:
    cache_key = recent_gallery_summary_cache_key(batch_id)
    cached = RECENT_GALLERY_SUMMARY_CACHE.get(batch_id)
    if cached and cached.get("key") == cache_key:
        return cached["summary"]
    paths = recent_gallery_summary_paths(batch_id)
    result = read_json_if_exists(paths["result"])
    validation = read_json_if_exists(paths["validation"])
    run = read_json_if_exists(paths["run"])
    jobs = result.get("jobs", []) if isinstance(result.get("jobs"), list) else []
    qa = result.get("qa_summary", {}) if isinstance(result.get("qa_summary"), dict) else derived_qa_summary(jobs)
    lipsync = derived_lipsync_counts(validation) if validation else {"checked_count": 0, "grade_counts": {}, "source_counts": {}}
    validation_summary = validation.get("summary", {}) if isinstance(validation.get("summary"), dict) else {}
    timing = derived_timing(result, run)
    render_cache = aggregate_child_render_cache(batch_id, result)
    validation_cache = aggregate_child_validation_cache(result, validation)
    render_dedupe = result.get("render_dedupe", {}) if isinstance(result.get("render_dedupe"), dict) else {}
    character_count = len(jobs)
    elapsed_seconds = float(timing.get("elapsed_seconds", 0) or 0)
    render_cache_total = int(render_cache.get("hit_count", 0) or 0) + int(render_cache.get("miss_count", 0) or 0)
    validation_cache_total = int(validation_cache.get("hit_count", 0) or 0) + int(validation_cache.get("miss_count", 0) or 0)
    environments = [job.get("environment", {}) for job in jobs if isinstance(job.get("environment"), dict)]
    bases = {env.get("INPUT_MODEL") for env in environments if env.get("INPUT_MODEL")}
    accessories = {env.get("OUTFIT_MODEL") for env in environments if env.get("OUTFIT_MODEL")}
    animations = {env.get("ANIMATION_PRESET") for env in environments if env.get("ANIMATION_PRESET")}
    categories = sorted({env.get("OUTFIT_CATEGORY") for env in environments if env.get("OUTFIT_CATEGORY")})
    ship_outfit_models = current_ship_outfit_models()
    non_ship_outfits = sorted(accessories - ship_outfit_models) if ship_outfit_models else []
    summary = {
        "character_count": character_count,
        "status": result.get("status", "unknown") if result else "unknown",
        "chunked": bool(result.get("chunked_parent") or run.get("chunked") or run.get("pipeline")),
        "qa_grades": qa.get("grades", {}),
        "review_count": qa.get("review_count", 0),
        "ship_count": qa.get("ship_count", 0),
        "lipsync_status": validation.get("status", "unknown") if validation else "unknown",
        "lipsync_checked_count": lipsync.get("checked_count", 0),
        "lipsync_grades": lipsync.get("grade_counts", {}),
        "lipsync_sources": lipsync.get("source_counts", {}),
        "lipsync_quality": {
            "active_visemes": validation.get("active_visemes") or validation_summary.get("active_visemes", []) if validation else [],
            "missing_active_viseme_counts": validation.get("missing_active_viseme_counts")
            or validation_summary.get("missing_active_viseme_counts", {})
            if validation
            else {},
            "cue_count_min": validation.get("cue_count_min") or validation_summary.get("cue_count_min", 0) if validation else 0,
            "cue_count_max": validation.get("cue_count_max") or validation_summary.get("cue_count_max", 0) if validation else 0,
            "expression_count_min": validation.get("expression_count_min")
            or validation_summary.get("expression_count_min", 0)
            if validation
            else 0,
            "expression_count_max": validation.get("expression_count_max")
            or validation_summary.get("expression_count_max", 0)
            if validation
            else 0,
        },
        "render_cache": {
            "hit_count": render_cache.get("hit_count", 0),
            "miss_count": render_cache.get("miss_count", 0),
        },
        "render_dedupe": {
            "requested_job_count": render_dedupe.get("requested_job_count", character_count),
            "source_job_count": render_dedupe.get("source_job_count", character_count),
            "materialized_duplicate_count": render_dedupe.get("materialized_duplicate_count", 0),
        },
        "elapsed_seconds": timing.get("elapsed_seconds", 0),
        "characters_per_second": round(character_count / elapsed_seconds, 3) if elapsed_seconds > 0 else 0,
        "slowest_stage": timing.get("slowest_stage", ""),
        "slowest_stage_seconds": timing.get("slowest_stage_seconds", 0),
        "pipeline_timing": timing.get("pipeline_timing", {}),
        "validation_cache": {
            "hit_count": validation_cache.get("hit_count", 0),
            "miss_count": validation_cache.get("miss_count", 0),
        },
        "render_cache_hit_rate": round(render_cache.get("hit_count", 0) / render_cache_total, 3)
        if render_cache_total
        else 0.0,
        "validation_cache_hit_rate": round(validation_cache.get("hit_count", 0) / validation_cache_total, 3)
        if validation_cache_total
        else 0.0,
        "variation": {
            "base_count": len(bases),
            "accessory_count": len(accessories),
            "animation_count": len(animations),
            "category_count": len(categories),
            "categories": categories,
        },
        "ship_compatible": not non_ship_outfits,
        "non_ship_outfit_count": len(non_ship_outfits),
    }
    RECENT_GALLERY_SUMMARY_CACHE[batch_id] = {"key": cache_key, "summary": summary}
    return summary


def current_ship_outfit_models() -> set[str]:
    config_path = ROOT / "config/poly_pizza_assets.json"
    if not config_path.exists():
        return set()
    return {
        accessory["outfit_model"]
        for accessory in load_accessories(config_path, include_qualities={"ship"})
        if accessory.get("outfit_model")
    }


def recent_batch_galleries(limit: int = 12) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    galleries = []
    seen: set[Path] = set()
    for path in OUTPUT_DIR.glob("person_factory*.html"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        stat = path.stat()
        stem = path.stem
        batch_id = stem.removeprefix("person_factory_")
        if batch_id == stem:
            batch_id = stem.removeprefix("person_factory")
        if CHILD_CHUNK_BATCH_RE.search(batch_id):
            continue
        result_slug = batch_result_slug(batch_id)
        batch_result = ROOT / "results" / f"batch_person_factory_{result_slug}_latest.json"
        validation_result = ROOT / "results" / f"godot_lipsync_validation_{result_slug}_latest.json"
        run_result = ROOT / "results" / f"run_cached_lipsync_batch_{result_slug}.json"
        galleries.append(
            {
                "name": path.name,
                "href": path.name,
                "batch_id": batch_id,
                "mtime": stat.st_mtime,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
                "size_bytes": stat.st_size,
                "batch_result": web_href(batch_result) if batch_result.exists() else "",
                "validation_result": web_href(validation_result) if validation_result.exists() else "",
                "run_result": web_href(run_result) if run_result.exists() else "",
            }
        )
    galleries.sort(key=lambda item: (-float(item["mtime"]), item["name"]))
    selected_limit = max(1, int(limit))
    selected = galleries[:selected_limit]
    benchmark_galleries = galleries[: max(selected_limit, RECENT_GALLERY_BENCHMARK_LIMIT)]
    summarized: set[str] = set()
    for gallery in selected:
        gallery["summary"] = recent_gallery_summary(str(gallery.get("batch_id", "")))
        summarized.add(str(gallery.get("batch_id", "")))
    for gallery in benchmark_galleries:
        batch_id = str(gallery.get("batch_id", ""))
        if batch_id in summarized:
            continue
        gallery["summary"] = recent_gallery_summary(batch_id)
    return {"status": "ok", "galleries": selected, "benchmark": gallery_benchmark(benchmark_galleries)}


def gallery_benchmark(galleries: list[dict]) -> dict:
    def throughput(gallery: dict) -> float:
        summary = gallery.get("summary", {}) if isinstance(gallery.get("summary"), dict) else {}
        return float(summary.get("characters_per_second", 0) or 0)

    def median(values: list[float]) -> float:
        if not values:
            return 0
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[midpoint]
        return (ordered[midpoint - 1] + ordered[midpoint]) / 2

    comparable_candidates: dict[tuple[str, int, bool], dict] = {}
    for gallery in galleries:
        summary = gallery.get("summary", {}) if isinstance(gallery.get("summary"), dict) else {}
        if throughput(gallery) <= 0:
            continue
        if summary.get("ship_compatible") is False or int(summary.get("review_count", 0) or 0) > 0:
            continue
        key = (
            benchmark_source_root(str(gallery.get("batch_id", ""))),
            int(summary.get("character_count", 0) or 0),
            bool(summary.get("chunked")),
        )
        comparable_candidates.setdefault(key, gallery)
    ranked = list(comparable_candidates.values())
    ranked.sort(key=lambda gallery: (-throughput(gallery), -int(gallery.get("summary", {}).get("character_count", 0) or 0), gallery.get("batch_id", "")))
    review_batches = [
        gallery.get("batch_id", "")
        for gallery in galleries
        if int(gallery.get("summary", {}).get("review_count", 0) or 0) > 0
        or gallery.get("summary", {}).get("status") not in {"ok", "unknown"}
        or gallery.get("summary", {}).get("lipsync_status") not in {"ok", "unknown"}
    ]
    best = ranked[0] if ranked else {}
    best_summary = best.get("summary", {}) if isinstance(best.get("summary"), dict) else {}
    latest = galleries[0] if galleries else {}
    best_count = int(best_summary.get("character_count", 0) or 0)
    recommended_count = max(1, min(best_count or 16, max_chunked_matrix_jobs()))
    best_was_chunked = bool(best_summary.get("chunked"))
    best_cache = best_summary.get("render_cache", {}) if isinstance(best_summary.get("render_cache"), dict) else {}
    best_dedupe = best_summary.get("render_dedupe", {}) if isinstance(best_summary.get("render_dedupe"), dict) else {}
    cache_hit_count = int(best_cache.get("hit_count", 0) or 0)
    cache_miss_count = int(best_cache.get("miss_count", 0) or 0)
    source_job_count = int(best_dedupe.get("source_job_count", 0) or 0)
    cache_checked_count = cache_hit_count + cache_miss_count
    cache_ready = source_job_count > 0 and cache_hit_count >= source_job_count and cache_miss_count == 0
    queue_chunked = best_was_chunked or recommended_count > max_batch_jobs()
    queue_chunk_size = max(1, max_batch_jobs()) if queue_chunked else recommended_count
    queue_chunk_count = math.ceil(recommended_count / queue_chunk_size) if queue_chunk_size else 0
    queue_references = [
        gallery
        for gallery in galleries
        if throughput(gallery) > 0
        and int(gallery.get("summary", {}).get("character_count", 0) or 0) == recommended_count
        and bool(gallery.get("summary", {}).get("chunked")) == queue_chunked
        and gallery.get("summary", {}).get("ship_compatible") is not False
        and int(gallery.get("summary", {}).get("review_count", 0) or 0) == 0
        and gallery.get("summary", {}).get("status") in {"ok", "unknown"}
        and gallery.get("summary", {}).get("lipsync_status") in {"ok", "unknown"}
    ]
    queue_references.sort(key=lambda gallery: (-float(gallery.get("mtime", 0) or 0), -throughput(gallery)))
    queue_reference = queue_references[0] if queue_references else {}
    queue_reference_summary = (
        queue_reference.get("summary", {}) if isinstance(queue_reference.get("summary"), dict) else {}
    )
    queue_reference_elapsed = float(queue_reference_summary.get("elapsed_seconds", 0) or 0)
    queue_reference_cps = float(queue_reference_summary.get("characters_per_second", 0) or 0)
    queue_reference_timing = (
        queue_reference_summary.get("pipeline_timing", {})
        if isinstance(queue_reference_summary.get("pipeline_timing"), dict)
        else {}
    )
    queue_estimate_references = queue_references[:5]
    queue_estimate_values = []
    queue_estimate_overhead_values = []
    for estimate_reference in queue_estimate_references:
        estimate_summary = (
            estimate_reference.get("summary", {})
            if isinstance(estimate_reference.get("summary"), dict)
            else {}
        )
        estimate_timing = (
            estimate_summary.get("pipeline_timing", {})
            if isinstance(estimate_summary.get("pipeline_timing"), dict)
            else {}
        )
        estimate_elapsed = float(estimate_summary.get("elapsed_seconds", 0) or 0)
        estimate_cps = float(estimate_summary.get("characters_per_second", 0) or 0)
        estimate_count = int(estimate_summary.get("character_count", 0) or 0)
        estimate_overhead = float(estimate_timing.get("orchestration_overhead_seconds", 0) or 0)
        if estimate_overhead > 0:
            queue_estimate_overhead_values.append(estimate_overhead)
        if estimate_elapsed > 0 and estimate_count == recommended_count:
            queue_estimate_values.append(estimate_elapsed)
        elif estimate_cps > 0:
            queue_estimate_values.append(recommended_count / estimate_cps)
    median_estimated_wall = median(queue_estimate_values)
    median_overhead = median(queue_estimate_overhead_values)
    latest_overhead = float(queue_reference_timing.get("orchestration_overhead_seconds", 0) or 0)
    use_latest_runtime_regime = (
        queue_reference_elapsed > 0
        and median_estimated_wall > 0
        and latest_overhead > 0
        and median_overhead > 0
        and latest_overhead <= median_overhead * 0.5
        and queue_reference_elapsed < median_estimated_wall
    )
    if use_latest_runtime_regime:
        queue_estimated_wall = round(queue_reference_elapsed, 3)
        queue_estimate_mode = "latest-runtime-regime"
    elif queue_estimate_values:
        queue_estimated_wall = round(median_estimated_wall, 3)
        queue_estimate_mode = "median"
    elif queue_reference_cps > 0:
        queue_estimated_wall = round(recommended_count / queue_reference_cps, 3)
        queue_estimate_mode = "throughput"
    else:
        queue_estimated_wall = 0
        queue_estimate_mode = "unavailable"
    queue_mode = "published-catalog"
    return {
        "best_throughput": {
            "batch_id": best.get("batch_id", ""),
            "href": best.get("href", ""),
            "characters_per_second": best_summary.get("characters_per_second", 0),
            "character_count": best_summary.get("character_count", 0),
            "mode": "chunked-published" if best_was_chunked else "fast-preview",
        },
        "latest": {
            "batch_id": latest.get("batch_id", ""),
            "href": latest.get("href", ""),
        },
        "review_batches": [batch_id for batch_id in review_batches if batch_id],
        "benchmark_sample_count": len(ranked),
        "recommendation": {
            "batch_id": next_recommendation_batch_id(best.get("batch_id", "web-thumb") if best else "web-thumb"),
            "count": recommended_count,
            "chunked": best_was_chunked,
            "fast_publish": True,
            "queue_chunked": queue_chunked,
            "queue_chunk_count": queue_chunk_count,
            "queue_chunk_size": queue_chunk_size,
            "queue_fast_publish": False,
            "queue_publish_combined": True,
            "queue_mode": queue_mode,
            "queue_estimated_wall_seconds": queue_estimated_wall,
            "queue_estimate_mode": queue_estimate_mode,
            "queue_estimate_sample_count": len(queue_estimate_values),
            "queue_estimate_reference_batch_ids": [
                estimate_reference.get("batch_id", "") for estimate_reference in queue_estimate_references
            ],
            "queue_estimate_orchestration_overhead_seconds": round(median_overhead, 3)
            if queue_estimate_overhead_values
            else 0,
            "queue_reference_batch_id": queue_reference.get("batch_id", ""),
            "queue_reference_characters_per_second": queue_reference_cps,
            "queue_reference_elapsed_seconds": queue_reference_elapsed,
            "queue_reference_chunk_wall_seconds": float(queue_reference_timing.get("chunk_wall_elapsed_seconds", 0) or 0),
            "queue_reference_orchestration_overhead_seconds": float(
                queue_reference_timing.get("orchestration_overhead_seconds", 0) or 0
            ),
            "source_batch_id": best.get("batch_id", ""),
            "cache_ready": cache_ready,
            "cache_hit_count": cache_hit_count,
            "cache_miss_count": cache_miss_count,
            "cache_checked_count": cache_checked_count,
            "source_job_count": source_job_count,
        },
    }


def benchmark_source_root(batch_id: str) -> str:
    return re.sub(r"-next(?:-\d{3})?$", "", batch_id or "")


def next_recommendation_batch_id(source_batch_id: str) -> str:
    source_root = benchmark_source_root(source_batch_id or "web-thumb") or "web-thumb"
    base = f"{source_root}-next"
    for index in range(1, 1000):
        candidate = base if index == 1 else f"{base}-{index:03d}"
        result_slug = batch_result_slug(candidate)
        paths = [
            OUTPUT_DIR / f"person_factory_{candidate}.html",
            ROOT / "results" / f"batch_person_factory_{result_slug}_latest.json",
            ROOT / "results" / f"run_cached_lipsync_batch_{result_slug}.json",
            ROOT / "config" / f"person_factory.{candidate}.json",
        ]
        if not any(path.exists() for path in paths):
            return candidate
    return f"{base}-{int(time.time())}"


def accessory_quality_filter() -> set[str]:
    raw = os.environ.get("PERSON_FACTORY_ACCESSORY_QUALITIES", "ship")
    values = {value.strip().lower() for value in raw.split(",") if value.strip()}
    return values or set(DEFAULT_ACCESSORY_QUALITIES)


def prepare_static_links() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for link_name, target in {
        "batch_optimized": "../batch_optimized",
        "musetalk": "../musetalk",
        "lipsync": "../lipsync",
        "speech": "../speech",
        "results": "../../results",
    }.items():
        link = OUTPUT_DIR / link_name
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)
        except OSError:
            pass
    index = OUTPUT_DIR / "index.html"
    try:
        if index.exists() or index.is_symlink():
            index.unlink()
        index.symlink_to(selected_gallery().name)
    except OSError:
        pass


def workspace_path(value: str | None) -> Path | None:
    if not value:
        return None
    text = str(value)
    if text.startswith("/workspace/"):
        return ROOT / text.removeprefix("/workspace/")
    path = Path(text)
    return path if path.is_absolute() else ROOT / path


def read_json_if_exists(path: Path | None) -> dict:
    if not path or not path.exists() or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def web_href(path: Path | None) -> str:
    if not path:
        return ""
    resolved = path.resolve()
    for source_root, alias in (
        (OUTPUT_DIR, ""),
        (ROOT / "outputs" / "batch_optimized", "batch_optimized"),
        (ROOT / "outputs" / "musetalk", "musetalk"),
        (ROOT / "outputs" / "lipsync", "lipsync"),
        (ROOT / "outputs" / "speech", "speech"),
        (ROOT / "results", "results"),
    ):
        try:
            mapped = resolved.relative_to(source_root.resolve()).as_posix()
        except ValueError:
            continue
        return f"{alias}/{mapped}" if alias else mapped
    return ""


def workspace_api_path(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return "/workspace/" + path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def add_output_link(links: list[dict], label: str, path: Path | None) -> None:
    href = web_href(path)
    if not href:
        return
    if not path or not path.exists():
        return
    if any(link["href"] == href for link in links):
        return
    links.append({"label": label, "href": href})


def batch_job_report(job_id: str, batch_result: dict) -> dict:
    for item in batch_result.get("jobs", []):
        if str(item.get("id", "")) == job_id:
            return item
    return {}


def preferred_review_image(job_id: str, batch_job: dict) -> Path | None:
    render_dir = OUTPUT_DIR / f"{job_id}_pose_renders"
    preferred = batch_job.get("qa", {}).get("preferred_review_frame", "")
    if preferred:
        candidate = render_dir / preferred
        if candidate.exists():
            return candidate
    images = sorted(render_dir.glob("*.png"))
    return images[0] if images else None


def timeline_path_for_job(job: dict, batch_job: dict, animation_report: dict) -> Path | None:
    request = job.get("request", {})
    environment = batch_job.get("environment", {})
    lipsync = animation_report.get("lipsync_animation", {})
    for value in (
        request.get("lipsync_timeline"),
        request.get("lipsync_timeline_json"),
        environment.get("LIPSYNC_TIMELINE_JSON"),
        lipsync.get("timeline"),
    ):
        path = workspace_path(value)
        if path and path.exists():
            return path
    return None


def lipsync_summary(timeline_path: Path | None, animation_report: dict | None = None) -> dict:
    timeline = read_json_if_exists(timeline_path)
    quality = analyze_lipsync_timeline(timeline)
    cues = timeline.get("cues", [])
    expressions = timeline.get("expressions", [])
    viseme_counts: dict[str, int] = {}
    if isinstance(cues, list):
        for cue in cues:
            if not isinstance(cue, dict):
                continue
            viseme = str(cue.get("viseme", "")).strip()
            if not viseme:
                continue
            viseme_counts[viseme] = viseme_counts.get(viseme, 0) + 1
    lipsync_report = (animation_report or {}).get("lipsync_animation", {})
    keyed_visemes = sorted({str(value) for value in lipsync_report.get("keyed_visemes", []) if value})
    reported_missing = sorted({str(value) for value in lipsync_report.get("missing_visemes", []) if value})
    coverage_missing = [
        viseme
        for viseme in EXPECTED_VISEMES
        if viseme not in viseme_counts and (not keyed_visemes or viseme in keyed_visemes)
    ]
    return {
        "cue_count": len(cues) if isinstance(cues, list) else 0,
        "duration": timeline.get("duration", 0.0) or 0.0,
        "expression_count": len(expressions) if isinstance(expressions, list) else 0,
        "visemes": list(viseme_counts),
        "viseme_counts": viseme_counts,
        "keyed_visemes": keyed_visemes,
        "missing_visemes": sorted(set(reported_missing + coverage_missing)),
        "source_mode": quality.get("source_mode", "unknown"),
        "source_event_count": int(quality.get("source_event_count", 0) or 0),
        "source_phoneme_count": int(quality.get("source_phoneme_count", 0) or 0),
        "source_input_mode": quality.get("source_input_mode", ""),
        "source_text": quality.get("source_text", ""),
        "source_schema": quality.get("source_schema", ""),
        "source_path": quality.get("source_path", ""),
        "source_unique_phonemes": quality.get("source_unique_phonemes", []),
        "source_phoneme_counts": quality.get("source_phoneme_counts", {}),
        "quality": quality,
    }


def ordered_visemes(values) -> list[str]:
    seen = {str(value) for value in values if value}
    ordered = [viseme for viseme in EXPECTED_VISEMES if viseme in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered


def lip_sync_readiness(has_game_asset: bool, has_timeline: bool, lipsync: dict, animation_report: dict) -> dict:
    reasons = []
    face_profile = animation_report.get("face_profile", {})
    face_quality = face_profile.get("quality", {}) if isinstance(face_profile, dict) else {}
    face_visemes = face_profile.get("visemes", {}) if isinstance(face_profile, dict) else {}
    required = list(EXPECTED_VISEMES)

    if isinstance(face_visemes, dict) and face_visemes:
        supported = ordered_visemes(face_visemes.keys())
        missing = ordered_visemes(face_quality.get("missing_visemes", []))
    elif face_quality.get("missing_visemes") is not None:
        missing = ordered_visemes(face_quality.get("missing_visemes", []))
        supported = [viseme for viseme in required if viseme not in missing]
    else:
        keyed = lipsync.get("keyed_visemes", [])
        reported_missing = lipsync.get("missing_visemes", [])
        supported = ordered_visemes(keyed)
        missing = ordered_visemes(reported_missing or [viseme for viseme in required if viseme not in supported])
        if has_game_asset:
            reasons.append("missing-face-profile")

    if not has_game_asset:
        reasons.append("missing-game-asset")
    if not has_timeline:
        reasons.append("missing-timeline")
    elif not lipsync.get("cue_count"):
        reasons.append("empty-timeline")
    if missing:
        reasons.append("missing-visemes")

    status = "ready" if not reasons else "review"
    return {
        "status": status,
        "label": "Lip-ready" if status == "ready" else "Needs lip fix",
        "required_visemes": required,
        "supported_visemes": supported,
        "missing_visemes": missing,
        "reasons": sorted(set(reasons)),
    }


def cached_batch_has_game_assets(finalize_report: dict) -> bool:
    if not isinstance(finalize_report, dict):
        return False
    export = finalize_report.get("godot_export", {})
    if isinstance(export, dict):
        exported = export.get("exported", [])
        if isinstance(exported, list) and exported:
            return True
        asset_ids = export.get("asset_ids", [])
        if isinstance(asset_ids, list) and asset_ids:
            return True
    reload_report = finalize_report.get("godot_reload", {})
    if isinstance(reload_report, dict) and int(reload_report.get("asset_count") or 0) > 0:
        return True
    return False


def cached_batch_lipsync_summary(batch_run_report: dict) -> dict:
    validation = batch_run_report.get("validation", {}) if isinstance(batch_run_report, dict) else {}
    validation_summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
    active_visemes = ordered_visemes(validation_summary.get("active_visemes", []))
    missing_counts = validation_summary.get("missing_active_viseme_counts", {})
    missing = ordered_visemes(missing_counts.keys() if isinstance(missing_counts, dict) else [])
    cue_count = int(validation_summary.get("cue_count_max") or validation_summary.get("cue_count_min") or 0)
    duration = float(validation_summary.get("duration_max") or validation_summary.get("duration_min") or 0.0)
    expression_count = int(
        validation_summary.get("expression_count_max") or validation_summary.get("expression_count_min") or 0
    )
    source_counts = validation_summary.get("source_counts", {})
    source_mode = ""
    if isinstance(source_counts, dict) and source_counts:
        source_mode = max(source_counts.items(), key=lambda item: int(item[1] or 0))[0]
    return {
        "cue_count": cue_count,
        "duration": duration,
        "expression_count": expression_count,
        "visemes": active_visemes,
        "viseme_counts": {},
        "keyed_visemes": active_visemes,
        "missing_visemes": missing,
        "source_mode": source_mode,
        "source_event_count": 0,
        "source_phoneme_count": 0,
        "source_input_mode": "",
        "source_text": "",
        "source_schema": "",
        "source_path": "",
        "source_unique_phonemes": [],
        "source_phoneme_counts": {},
        "quality": {
            "status": "ok" if validation_summary.get("review_count", 0) == 0 else "review",
            "grade_counts": validation_summary.get("grade_counts", {}),
            "checked_count": validation.get("checked_count", 0),
        },
    }


def job_output_summary(job: dict) -> dict:
    job_id = str(job.get("id", ""))
    request = job.get("request", {}) if isinstance(job.get("request", {}), dict) else {}
    output_batch_id = slug(str(request.get("batch_id") or job_id)) or job_id
    batch_result_path = ROOT / "results" / f"batch_person_factory_{output_batch_id.replace('-', '_')}_latest.json"
    batch_run_report_path = ROOT / "results" / f"run_cached_lipsync_batch_{output_batch_id.replace('-', '_')}.json"
    animation_report_path = ROOT / "results" / "batch" / f"{job_id}_animation.json"
    text_report_path = ROOT / "results" / "talking_person" / f"{job_id}.text.json"
    batch_result = read_json_if_exists(batch_result_path)
    batch_job = batch_job_report(job_id, batch_result)
    animation_report = read_json_if_exists(animation_report_path)
    text_report = read_json_if_exists(text_report_path)
    batch_run_report = read_json_if_exists(batch_run_report_path)
    finalize_report_path = ROOT / "results" / f"finalize_person_factory_{output_batch_id.replace('-', '_')}_latest.json"
    finalize_report = read_json_if_exists(finalize_report_path)
    batch_stage_summary = batch_run_report.get("stage_summary", {}) if batch_run_report else {}
    if batch_run_report and not batch_stage_summary and batch_run_report.get("stages"):
        batch_stage_summary = stage_timing_summary(batch_run_report.get("stages", []))
    links: list[dict] = []

    parent_gallery = job.get("parent_gallery", {}) if isinstance(job.get("parent_gallery", {}), dict) else {}
    if not parent_gallery:
        parent_gallery = inferred_cached_lipsync_parent_gallery(job)
    if parent_gallery.get("status") == "ok":
        add_output_link(links, "Parent Gallery", workspace_path(parent_gallery.get("gallery")))
        add_output_link(links, "Parent Result JSON", workspace_path(parent_gallery.get("batch_result")))
        add_output_link(links, "Parent Lip Validation", workspace_path(parent_gallery.get("validation_result")))

    add_output_link(links, "Gallery", OUTPUT_DIR / f"person_factory_{output_batch_id}.html")
    add_output_link(links, "Result JSON", batch_result_path)
    add_output_link(links, "Animation JSON", animation_report_path)
    optimized_glb = ROOT / "outputs" / "batch_optimized" / f"{job_id}.glb"
    raw_glb = OUTPUT_DIR / f"{job_id}.glb"
    review_image = preferred_review_image(job_id, batch_job)
    add_output_link(links, "Optimized GLB", optimized_glb)
    add_output_link(links, "GLB", raw_glb)
    add_output_link(links, "Review PNG", review_image)

    timeline_path = timeline_path_for_job(job, batch_job, animation_report)
    add_output_link(links, "Timeline JSON", timeline_path)
    audio_path = workspace_path(request.get("audio_wav") or text_report.get("audio_wav"))
    add_output_link(links, "Speech WAV", audio_path)

    qa = batch_job.get("qa", {})
    has_game_asset = optimized_glb.exists() or raw_glb.exists()
    has_timeline = bool(timeline_path)
    lipsync = {
        **lipsync_summary(timeline_path, animation_report),
        "path": workspace_api_path(timeline_path),
    }
    if batch_run_report and batch_run_report.get("validation"):
        batch_lipsync = cached_batch_lipsync_summary(batch_run_report)
        if batch_lipsync.get("cue_count"):
            has_timeline = True
            lipsync = {**batch_lipsync, "path": ""}
        if cached_batch_has_game_assets(finalize_report):
            has_game_asset = True
    batch_run = {}
    if batch_run_report:
        batch_validation = batch_run_report.get("validation", {})
        batch_validation_summary = batch_validation.get("summary", {}) if isinstance(batch_validation, dict) else {}
        batch_run = {
            "elapsed_seconds": batch_run_report.get("elapsed_seconds"),
            "stage_summary": batch_stage_summary,
        }
        if batch_validation:
            batch_run["validation"] = {
                "checked_count": batch_validation.get("checked_count", 0),
                "grade_counts": batch_validation_summary.get("grade_counts", {}),
                "status_counts": batch_validation_summary.get("status_counts", {}),
            }
            batch_run["validation_cache"] = batch_validation.get("validation_cache", {})
            batch_run["validation_transport"] = batch_validation.get("validation_transport", {})
    readiness_report = animation_report
    if batch_run_report and batch_run_report.get("validation") and lipsync.get("keyed_visemes"):
        readiness_report = {
            **animation_report,
            "face_profile": {
                "quality": {"missing_visemes": lipsync.get("missing_visemes", [])},
                "visemes": {viseme: {} for viseme in lipsync.get("keyed_visemes", [])},
            },
        }
    summary = {
        "links": links,
        "has_game_asset": has_game_asset,
        "has_timeline": has_timeline,
        "review_image": web_href(review_image),
        "qa": {
            "grade": qa.get("qa_grade"),
            "score": qa.get("qa_score"),
            "priority": qa.get("review_priority"),
        },
        "lipsync": lipsync,
        "lip_sync_readiness": lip_sync_readiness(has_game_asset, has_timeline, lipsync, readiness_report),
        "batch_run": batch_run,
    }
    pipeline_timing = job.get("pipeline_timing", {})
    if isinstance(pipeline_timing, dict) and pipeline_timing:
        summary["pipeline_timing"] = pipeline_timing
    estimate_accuracy = job.get("estimate_accuracy", {})
    if isinstance(estimate_accuracy, dict) and estimate_accuracy:
        summary["estimate_accuracy"] = estimate_accuracy
    return summary


def job_with_log(job: dict, *, log_count: int = 80) -> dict:
    enriched = dict(job)
    enriched["log_tail"] = tail_lines(LOG_DIR / f"{job['id']}.log", count=log_count)
    output_summary = job_output_summary(job)
    if output_summary["links"] or output_summary.get("pipeline_timing") or output_summary.get("estimate_accuracy"):
        enriched["output_summary"] = output_summary
    return enriched


def compact_output_summary(summary: dict) -> dict:
    if not isinstance(summary, dict) or not summary:
        return {}
    compact = {
        key: summary.get(key)
        for key in (
            "has_game_asset",
            "has_timeline",
            "lip_sync_readiness",
            "pipeline_timing",
            "estimate_accuracy",
        )
        if key in summary
    }
    lipsync = summary.get("lipsync", {}) if isinstance(summary.get("lipsync"), dict) else {}
    if lipsync:
        compact["lipsync"] = {
            key: lipsync.get(key)
            for key in ("path", "cue_count", "duration", "quality")
            if key in lipsync
        }
    batch_run = summary.get("batch_run", {}) if isinstance(summary.get("batch_run"), dict) else {}
    stage_summary = batch_run.get("stage_summary", {}) if isinstance(batch_run.get("stage_summary"), dict) else {}
    if stage_summary:
        compact["batch_run"] = {"stage_summary": stage_summary}
    return compact


def compact_job_for_list(job: dict, *, include_summary: bool = True, include_logs: bool = True) -> dict:
    enriched = dict(job)
    if include_logs:
        enriched["log_tail"] = tail_lines(LOG_DIR / f"{job['id']}.log", count=20)
    if include_summary:
        output_summary = job_output_summary(job)
        if output_summary["links"] or output_summary.get("pipeline_timing") or output_summary.get("estimate_accuracy"):
            enriched["output_summary"] = output_summary
    request = enriched.get("request", {}) if isinstance(enriched.get("request"), dict) else {}
    compact = {
        key: enriched.get(key)
        for key in (
            "id",
            "status",
            "returncode",
            "created_at",
            "updated_at",
            "child_job_ids",
            "warm_job_ids",
            "render_job_ids",
            "publish_result",
            "output_summary",
            "log_tail",
        )
        if key in enriched
    }
    if isinstance(compact.get("output_summary"), dict):
        compact["output_summary"] = compact_output_summary(compact["output_summary"])
    compact["request"] = {
        key: request.get(key)
        for key in ("id", "name", "text", "batch_id", "pipeline")
        if key in request
    }
    return compact


def limited_jobs_for_response(params: dict[str, list[str]]) -> tuple[list[dict], bool, bool, bool]:
    compact = normalize_bool((params.get("compact") or ["0"])[0])
    include_summary = normalize_bool((params.get("summary") or ["1"])[0])
    include_logs = normalize_bool((params.get("logs") or ["1"])[0])
    try:
        limit = int((params.get("limit") or (["80"] if compact else ["0"]))[0])
    except ValueError:
        limit = 80 if compact else 0
    if compact and not include_summary and not include_logs and limit > 0:
        jobs = JOB_STORE.list_recent_jobs(limit)
    else:
        jobs = JOB_STORE.list_jobs()
        if limit > 0:
            jobs = jobs[-limit:]
    return jobs, compact, include_summary, include_logs


def catalog_options() -> dict:
    quality_filter = accessory_quality_filter()
    accessories = load_accessories(ROOT / "config/poly_pizza_assets.json", include_qualities=quality_filter)
    return {
        "defaults": {
            "base": "female",
            "accessory": "necklace-quaternius",
            "animation": "talk_idle",
        },
        "quality_filter": sorted(quality_filter),
        "limits": {
            "matrix_jobs": max_batch_jobs(),
            "chunked_matrix_jobs": max_chunked_matrix_jobs(),
            "max_concurrent_jobs": JOB_MAX_CONCURRENT,
            "cached_lipsync_chunk_workers": cached_lipsync_chunk_workers(),
            "render_chunk_workers": render_chunk_workers(),
        },
        "base_models": [
            {
                "value": item["key"],
                "label": item["key"].replace("-", " ").title(),
                "tags": item.get("tags", []),
            }
            for item in BASE_MODELS
        ],
        "accessories": [
            {
                "value": item["key"],
                "label": item.get("title") or item["key"].replace("-", " ").title(),
                "category": item.get("category"),
                "tags": item.get("tags", []),
                "quality": item.get("quality"),
                "license": item.get("license"),
            }
            for item in accessories
        ],
        "animations": [
            {
                "value": item["preset"],
                "label": item["preset"].replace("_", " ").title(),
                "tags": item.get("tags", []),
            }
            for item in ANIMATIONS
        ],
    }


def character_catalog_summary(job: dict, validation_by_id: dict[str, dict]) -> dict:
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    environment = job.get("environment", {}) if isinstance(job.get("environment", {}), dict) else {}
    qa = job.get("qa", {}) if isinstance(job.get("qa", {}), dict) else {}
    job_id = str(job.get("id", ""))
    validation = validation_by_id.get(job_id, {})
    quality = validation.get("lipsync_quality", {}) if isinstance(validation.get("lipsync_quality", {}), dict) else {}
    animation = str(environment.get("ANIMATION_PRESET") or "unknown")
    category = str(environment.get("OUTFIT_CATEGORY") or "none")
    tags = sorted({str(tag) for tag in metadata.get("tags", []) if str(tag).strip()})
    report_path = workspace_path(environment.get("ANIMATION_REPORT_JSON"))
    report = read_json_if_exists(report_path)
    optimization = report.get("asset_optimization", {}) if isinstance(report.get("asset_optimization"), dict) else {}
    glb_path = workspace_path(environment.get("OUTPUT_GLB"))
    optimized_glb = ROOT / "outputs" / "batch_optimized" / f"{job_id}.glb"
    game_glb = ROOT / "godot_viewer" / "game_assets" / "glb" / f"{job_id}.glb"
    source_bytes = glb_path.stat().st_size if glb_path and glb_path.exists() else int(optimization.get("source_bytes", 0) or 0)
    optimized_bytes = optimized_glb.stat().st_size if optimized_glb.exists() else int(optimization.get("optimized_bytes", 0) or 0)
    game_bytes = game_glb.stat().st_size if game_glb.exists() else 0
    size_ratio = optimized_bytes / source_bytes if source_bytes and optimized_bytes else optimization.get("size_ratio")
    saved_pct = max(0, round((1 - float(size_ratio)) * 100)) if size_ratio is not None else 0
    review_image = preferred_review_image(job_id, job)
    output_mtimes = [path.stat().st_mtime for path in (optimized_glb, game_glb, review_image) if path and path.exists()]
    links = []
    add_output_link(links, "Report", report_path)
    add_output_link(links, "GLB", glb_path)
    add_output_link(links, "Optimized", optimized_glb)
    return {
        "id": job_id,
        "display_name": metadata.get("display_name") or job_id.replace("-", " ").title(),
        "persona": metadata.get("persona") or "",
        "notes": metadata.get("notes") or "",
        "status": job.get("status") or "unknown",
        "animation": animation,
        "category": category,
        "tags": tags,
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
        "asset_size": {
            "source_bytes": source_bytes,
            "optimized_bytes": optimized_bytes,
            "game_bytes": game_bytes,
            "size_ratio": round(float(size_ratio), 4) if size_ratio is not None else None,
            "saved_pct": saved_pct,
            "optimization_status": optimization.get("status") or ("ok" if optimized_glb.exists() else "none"),
            "optimization_profile": optimization.get("profile", ""),
        },
        "updated_at": max(output_mtimes) if output_mtimes else 0,
        "review_image": web_href(review_image),
        "links": links,
    }


def character_catalog_summary_path() -> Path:
    return ROOT / "results" / "person_factory_all_latest.json"


def character_catalog_index_path() -> Path:
    return ROOT / "results" / "person_factory_character_catalog_latest.json"


def load_fresh_character_catalog_index(source_mtime: float) -> dict | None:
    index_path = character_catalog_index_path()
    if not index_path.exists():
        return None
    data = read_json_if_exists(index_path)
    if data.get("source_mtime") != source_mtime:
        return None
    if data.get("schema_version") != CHARACTER_CATALOG_SCHEMA_VERSION:
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    characters = payload.get("characters", [])
    if isinstance(characters, list) and any("updated_at" not in character for character in characters):
        return None
    return payload


def build_character_catalog_payload(data: dict, *, source_path: Path, source_mtime: float) -> dict:
    return build_character_catalog_payload_base(
        data,
        source_path=source_path,
        source_mtime=source_mtime,
        root=ROOT,
        summarize_job=character_catalog_summary,
    )


def write_character_catalog_index() -> dict:
    source_path = character_catalog_summary_path()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    source_mtime = source_path.stat().st_mtime
    payload = build_character_catalog_payload(
        read_json_if_exists(source_path),
        source_path=source_path,
        source_mtime=source_mtime,
    )
    index = {
        "status": "ok",
        "source": str(source_path.relative_to(ROOT)),
        "source_mtime": source_mtime,
        "schema_version": CHARACTER_CATALOG_SCHEMA_VERSION,
        "payload": payload,
    }
    index_path = character_catalog_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    return index


def write_character_catalog_index_from_payload(
    data: dict,
    *,
    source_path: Path,
    output_path: Path,
) -> dict:
    return write_character_catalog_index_from_payload_base(
        data,
        source_path=source_path,
        output_path=output_path,
        root=ROOT,
        summarize_job=character_catalog_summary,
    )


def load_character_catalog() -> dict:
    path = character_catalog_summary_path()
    if not path.exists():
        return {"status": "missing", "characters": [], "summary": {}, "source": str(path)}
    mtime = path.stat().st_mtime
    if CHARACTER_CATALOG_CACHE.get("mtime") == mtime and CHARACTER_CATALOG_CACHE.get("payload"):
        return CHARACTER_CATALOG_CACHE["payload"]  # type: ignore[return-value]
    payload = load_fresh_character_catalog_index(mtime)
    if payload is None:
        payload = build_character_catalog_payload(read_json_if_exists(path), source_path=path, source_mtime=mtime)
        try:
            write_character_catalog_index()
        except OSError:
            pass
    CHARACTER_CATALOG_CACHE.update({"mtime": mtime, "payload": payload})
    return payload


def character_catalog_page(params: dict[str, list[str]]) -> dict:
    catalog = load_character_catalog()
    characters = list(catalog.get("characters", []))
    query = (params.get("q") or [""])[0].strip().lower()
    tag = (params.get("tag") or [""])[0].strip()
    priority = (params.get("priority") or [""])[0].strip()
    lip = (params.get("lip") or [""])[0].strip()
    sort_mode = (params.get("sort") or ["ready"])[0].strip() or "ready"
    try:
        page = max(1, int((params.get("page") or ["1"])[0]))
    except ValueError:
        page = 1
    try:
        per_page = int((params.get("per_page") or ["48"])[0])
    except ValueError:
        per_page = 48
    per_page = max(1, min(per_page, 120))

    def matches(character: dict) -> bool:
        if tag and tag not in character.get("tags", []):
            return False
        if priority and character.get("qa", {}).get("priority") != priority:
            return False
        if lip and character.get("lipsync", {}).get("status") != lip:
            return False
        if query:
            haystack = " ".join(
                [
                    character.get("id", ""),
                    character.get("display_name", ""),
                    character.get("persona", ""),
                    character.get("notes", ""),
                    character.get("animation", ""),
                    character.get("category", ""),
                    " ".join(character.get("tags", [])),
                ]
            ).lower()
            if query not in haystack:
                return False
        return True

    filtered = [character for character in characters if matches(character)]
    if sort_mode == "ready":
        filtered.sort(key=character_ready_sort_key)
    elif sort_mode == "newest":
        filtered.sort(key=character_newest_sort_key)
    elif sort_mode == "id":
        filtered.sort(key=lambda character: str(character.get("id", "")))
    elif sort_mode == "smallest":
        filtered.sort(key=character_smallest_sort_key)
    elif sort_mode == "largest":
        filtered.sort(key=character_largest_sort_key)
    else:
        sort_mode = "ready"
        filtered.sort(key=character_ready_sort_key)
    total = len(filtered)
    page_count = max(1, math.ceil(total / per_page))
    page = min(page, page_count)
    start = (page - 1) * per_page
    return {
        "status": catalog.get("status", "ok"),
        "source": catalog.get("source"),
        "summary": catalog.get("summary", {}),
        "filters": {"q": query, "tag": tag, "priority": priority, "lip": lip, "sort": sort_mode},
        "pagination": {
            "page": page,
            "per_page": per_page,
            "page_count": page_count,
            "total": total,
            "start": start + 1 if total else 0,
            "end": min(total, start + per_page),
        },
        "characters": filtered[start : start + per_page],
    }


def character_ready_sort_key(character: dict) -> tuple:
    qa = character.get("qa", {}) if isinstance(character.get("qa"), dict) else {}
    lipsync = character.get("lipsync", {}) if isinstance(character.get("lipsync"), dict) else {}
    lip_ready = lipsync.get("status") == "ok" and lipsync.get("grade") == "A"
    ship_ready = qa.get("priority") == "ship" and qa.get("grade") == "A"
    return (
        0 if lip_ready else 1,
        0 if ship_ready else 1,
        0 if character.get("has_game_asset") else 1,
        0 if character.get("has_optimized_glb") else 1,
        -float(character.get("updated_at", 0) or 0),
        -int(lipsync.get("cue_count", 0) or 0),
        str(character.get("id", "")),
    )


def character_newest_sort_key(character: dict) -> tuple:
    return (
        -float(character.get("updated_at", 0) or 0),
        str(character.get("id", "")),
    )


def character_asset_size_bytes(character: dict) -> int:
    asset_size = character.get("asset_size", {}) if isinstance(character.get("asset_size"), dict) else {}
    for key in ("optimized_bytes", "game_bytes", "source_bytes"):
        value = int(asset_size.get(key, 0) or 0)
        if value > 0:
            return value
    return 0


def character_smallest_sort_key(character: dict) -> tuple:
    size = character_asset_size_bytes(character)
    return (
        0 if size else 1,
        size or 10**18,
        str(character.get("id", "")),
    )


def character_largest_sort_key(character: dict) -> tuple:
    size = character_asset_size_bytes(character)
    return (
        0 if size else 1,
        -size,
        str(character.get("id", "")),
    )


def lipsync_cache_entries() -> list[dict]:
    entries: dict[str, dict] = {}
    for path in sorted((ROOT / "results" / "talking_person").glob("*.text.json")):
        data = read_json_if_exists(path)
        key = str(data.get("audio_cache_key") or "").strip()
        cache_paths = data.get("cache_paths", {}) if isinstance(data.get("cache_paths"), dict) else {}
        timeline = str(cache_paths.get("lipsync_timeline") or "")
        if not key and timeline:
            key = Path(timeline).name.removesuffix(".face.json")
        if not key:
            continue
        entries.setdefault(key, {}).update(
            {
                "audio_cache_key": key,
                "text": str(data.get("text") or ""),
                "timeline": timeline or f"outputs/lipsync/cache/{key}.face.json",
                "audio_wav": str(cache_paths.get("audio_wav") or f"outputs/speech/cache/{key}.wav"),
                "normalized_audio": str(cache_paths.get("normalized_audio") or f"outputs/speech/cache/{key}_clean.wav"),
                "manifest": web_href(path),
                "reused_audio": bool(data.get("reused_audio", False)),
            }
        )

    for timeline_path in sorted((ROOT / "outputs" / "lipsync" / "cache").glob("*.face.json")):
        key = timeline_path.name.removesuffix(".face.json")
        entry = entries.setdefault(
            key,
            {
                "audio_cache_key": key,
                "text": "",
                "timeline": web_href(timeline_path),
                "audio_wav": f"outputs/speech/cache/{key}.wav",
                "normalized_audio": f"outputs/speech/cache/{key}_clean.wav",
                "manifest": "",
                "reused_audio": False,
            },
        )
        timeline = read_json_if_exists(timeline_path)
        cues = timeline.get("cues", [])
        expressions = timeline.get("expressions", [])
        quality = analyze_lipsync_timeline(timeline)
        entry.update(
            {
                "timeline": str(entry.get("timeline") or web_href(timeline_path)),
                "duration": timeline.get("duration", 0.0) or 0.0,
                "cue_count": len(cues) if isinstance(cues, list) else 0,
                "expression_count": len(expressions) if isinstance(expressions, list) else 0,
                "quality_status": quality.get("status", "review"),
                "quality_grade": quality.get("grade", "D"),
                "source_mode": quality.get("source_mode", "unknown"),
                "active_visemes": quality.get("active_visemes", []),
                "missing_active_visemes": quality.get("missing_expected_active_visemes", []),
                "timeline_exists": True,
                "audio_exists": (ROOT / str(entry.get("audio_wav", ""))).exists(),
                "normalized_audio_exists": (ROOT / str(entry.get("normalized_audio", ""))).exists(),
            }
        )
        entry["quality"] = {
            "status": entry["quality_status"],
            "grade": entry["quality_grade"],
            "source_mode": entry["source_mode"],
            "active_visemes": entry["active_visemes"],
            "missing_active_visemes": entry["missing_active_visemes"],
            "cue_count": entry["cue_count"],
            "duration": entry["duration"],
            "expression_count": entry["expression_count"],
        }

    return sorted(
        entries.values(),
        key=lambda item: (
            len(item.get("missing_active_visemes", [])),
            not bool(item.get("text")),
            -float(item.get("duration", 0.0) or 0.0),
            item["audio_cache_key"],
        ),
    )


def lipsync_cache_response(entries: list[dict] | None = None) -> dict:
    resolved_entries = entries if entries is not None else lipsync_cache_entries()
    status_counts: dict[str, int] = {}
    grade_counts: dict[str, int] = {}
    full_viseme_count = 0
    for entry in resolved_entries:
        status = str(entry.get("quality_status") or entry.get("quality", {}).get("status") or "unknown")
        grade = str(entry.get("quality_grade") or entry.get("quality", {}).get("grade") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        if not entry.get("missing_active_visemes"):
            full_viseme_count += 1
    return {
        "status": "ok",
        "entries": resolved_entries,
        "summary": {
            "entry_count": len(resolved_entries),
            "full_viseme_count": full_viseme_count,
            "quality_status_counts": dict(sorted(status_counts.items())),
            "quality_grade_counts": dict(sorted(grade_counts.items())),
        },
    }


def requested_catalog_values(payload: dict, plural_key: str, singular_key: str, default_value: str) -> list[str]:
    return normalize_list(payload.get(plural_key)) or normalize_list(payload.get(singular_key)) or [default_value]


def accessory_matches_catalog(query: str, accessories: list[dict]) -> bool:
    wanted = slug(query)
    if not wanted:
        return False
    for accessory in accessories:
        values = [
            accessory.get("key", ""),
            accessory.get("title", ""),
            accessory.get("role", ""),
            accessory.get("category", ""),
            " ".join(accessory.get("tags", [])),
        ]
        if any(wanted == slug(value) or wanted in slug(value) for value in values):
            return True
    return False


def validate_catalog_choices(payload: dict) -> None:
    base_values = {item["key"] for item in BASE_MODELS}
    animation_values = {item["preset"] for item in ANIMATIONS}
    accessories = load_accessories(
        ROOT / "config/poly_pizza_assets.json",
        include_qualities=accessory_quality_filter(),
    )

    for base in requested_catalog_values(payload, "bases", "base", DEFAULTS["base"]):
        if base not in base_values:
            raise ValueError(f"unknown base: {base}")
    for animation in requested_catalog_values(payload, "animations", "animation", DEFAULTS["animation"]):
        if animation not in animation_values:
            raise ValueError(f"unknown animation: {animation}")
    for accessory in requested_catalog_values(payload, "accessories", "accessory", DEFAULTS["accessory"]):
        if not accessory_matches_catalog(accessory, accessories):
            raise ValueError(f"unknown accessory: {accessory}")


def post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, timeout: int = 120) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def default_godot_control_url() -> str:
    return "http://godot-viewer:8790" if Path("/.dockerenv").exists() else "http://127.0.0.1:8790"


def godot_control_url() -> str:
    return os.environ.get("GODOT_CONTROL_URL", default_godot_control_url()).rstrip("/")


def proxy_godot_post(path: str, payload: dict) -> dict:
    godot_url = godot_control_url()
    return post_json(f"{godot_url}{path}", payload)


def proxy_godot_get(path: str) -> dict:
    godot_url = godot_control_url()
    return get_json(f"{godot_url}{path}")


def workspace_result_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("/workspace/"):
        return text
    resolved = workspace_path(text)
    if not resolved:
        return text
    try:
        relative = resolved.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return text
    return f"/workspace/{relative.as_posix()}"


def batch_result_asset_ids(batch_result: str) -> list[str]:
    path = workspace_path(batch_result)
    data = read_json_if_exists(path)
    asset_ids = []
    for job in data.get("jobs", []) if isinstance(data.get("jobs"), list) else []:
        if not isinstance(job, dict):
            continue
        asset_id = str(job.get("id", "")).strip()
        if asset_id and asset_id not in asset_ids:
            asset_ids.append(asset_id)
    return asset_ids


def sync_godot_assets(batch_result: str | None = None) -> dict:
    godot_url = godot_control_url()
    requested_batch_result = batch_result or os.environ.get("GODOT_SYNC_BATCH_RESULT", "/workspace/results/person_factory_all_latest.json")
    selected_batch_result = workspace_result_path(requested_batch_result)
    scoped = bool(batch_result)
    asset_ids = batch_result_asset_ids(requested_batch_result) if scoped else []
    skip_existing = os.environ.get("GODOT_EXPORT_SKIP_EXISTING", "1") == "1"
    reload_payload = {"batch_result": selected_batch_result}
    if scoped:
        reload_payload["scoped"] = True
    reload_result = post_json(f"{godot_url}/reload-assets", reload_payload)
    export_payload = {"skip_existing": skip_existing}
    if asset_ids:
        export_payload["asset_ids"] = asset_ids
    export_result = post_json(f"{godot_url}/export-all-game-assets", export_payload)
    status = "ok" if reload_result.get("status") == "ok" and export_result.get("status") == "ok" else "review"
    return {
        "status": status,
        "godot_url": godot_url,
        "batch_result": selected_batch_result,
        "asset_ids": asset_ids,
        "reload": reload_result,
        "export": export_result,
    }


def validate_godot_lipsync_outputs(id_prefix: str = "") -> dict:
    godot_url = godot_control_url()
    output = os.environ.get("GODOT_LIPSYNC_VALIDATION_JSON", "results/godot_lipsync_validation_latest.json")
    max_assets = os.environ.get("GODOT_LIPSYNC_VALIDATION_MAX_ASSETS", "100")
    wait_seconds = os.environ.get("GODOT_LIPSYNC_VALIDATION_WAIT_SECONDS", "0.05")
    command = [
        "python3",
        "scripts/validate_godot_lipsync.py",
        "--control-url",
        godot_url,
        "--max-assets",
        max_assets,
        "--wait-seconds",
        wait_seconds,
        "--output",
        output,
    ]
    if id_prefix:
        command.extend(["--id-prefix", id_prefix])
    validation = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "returncode": validation.returncode,
        "command": command,
        "stdout_tail": validation.stdout.splitlines()[-20:],
        "stderr_tail": validation.stderr.splitlines()[-20:],
        "report_path": output,
        "report": read_json_if_exists(ROOT / output),
    }


def build_combined_gallery_result() -> dict:
    gallery = subprocess.run(
        ["python3", "scripts/build_combined_gallery.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "returncode": gallery.returncode,
        "stdout_tail": gallery.stdout.splitlines()[-20:],
        "stderr_tail": gallery.stderr.splitlines()[-20:],
    }


def build_refresh_combined_gallery_command(*, summary_only: bool = True) -> list[str]:
    command = ["python3", "scripts/refresh_combined_gallery.py"]
    if summary_only:
        command.append("--summary-only")
    return command


def validated_results_path(value: str | None) -> Path:
    path = workspace_path(value or "results/batch_person_factory_control_prod_001_latest.json")
    if not path:
        raise ValueError("batch_result is required")
    resolved = path.resolve()
    try:
        relative = resolved.relative_to((ROOT / "results").resolve())
    except ValueError as exc:
        raise ValueError("batch_result must be under results/") from exc
    if not relative.name.endswith(".json"):
        raise ValueError("batch_result must be a JSON file")
    return Path("results") / relative


def validated_lipsync_timeline_path(value: str | None) -> Path:
    path = workspace_path(value or "")
    if not path:
        raise ValueError("lipsync_timeline is required")
    resolved = path.resolve()
    try:
        relative = resolved.relative_to((ROOT / "outputs" / "lipsync").resolve())
    except ValueError as exc:
        raise ValueError("lipsync_timeline must be under outputs/lipsync/") from exc
    if not relative.name.endswith(".json"):
        raise ValueError("lipsync_timeline must be a JSON file")
    return Path("outputs/lipsync") / relative


def build_promote_batch_command(payload: dict) -> list[str]:
    batch_result = validated_results_path(str(payload.get("batch_result") or ""))
    texture_size = int(payload.get("texture_size") or 768)
    if texture_size < 128 or texture_size > 4096:
        raise ValueError("texture_size must be between 128 and 4096")
    command = [
        "python3",
        "scripts/promote_batch_assets.py",
        batch_result.as_posix(),
        "--texture-size",
        str(texture_size),
    ]
    if payload.get("skip_godot_export"):
        command.append("--skip-godot-export")
    if payload.get("force_godot_export"):
        command.append("--force-godot-export")
    return command


def csv_values(payload: dict, key: str, default: str) -> str:
    values = normalize_list(payload.get(key))
    return ",".join(values) if values else default


def validated_cache_lines(payload: dict) -> list[dict]:
    lines = payload.get("cache_lines") or []
    if not isinstance(lines, list):
        raise ValueError("cache_lines must be a list")
    validated = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        key = str(line.get("audio_cache_key") or "").strip()
        timeline_value = str(line.get("lipsync_timeline") or line.get("timeline") or "").strip()
        text = str(line.get("text") or "").strip()
        if not key or not timeline_value:
            continue
        timeline = validated_lipsync_timeline_path(timeline_value)
        validated.append(
            {
                "text": text,
                "audio_cache_key": key,
                "lipsync_timeline": timeline.as_posix(),
            }
        )
    return validated


def best_lipsync_cache_lines(entries: list[dict], *, limit: int = 4) -> list[dict]:
    selected = []
    for entry in entries:
        key = str(entry.get("audio_cache_key") or "").strip()
        timeline_value = str(entry.get("lipsync_timeline") or entry.get("timeline") or "").strip()
        text = str(entry.get("text") or "").strip()
        grade = str(entry.get("quality_grade") or entry.get("quality", {}).get("grade") or "").upper()
        missing = entry.get("missing_active_visemes")
        if not key or not timeline_value or not text:
            continue
        if grade != "A":
            continue
        if isinstance(missing, list) and missing:
            continue
        if entry.get("audio_exists") is False:
            continue
        selected.append(
            {
                "text": text,
                "audio_cache_key": key,
                "lipsync_timeline": timeline_value,
            }
        )
        if len(selected) >= limit:
            break
    return selected


def auto_cache_line_count(payload: dict) -> int:
    try:
        return max(1, min(16, int(payload.get("cache_line_count") or 4)))
    except (TypeError, ValueError):
        return 4


def cached_lipsync_batch_limit(payload: dict) -> int:
    chunked = normalize_bool(payload.get("chunked_cached_lipsync") or payload.get("chunked"))
    fast_publish = normalize_bool(payload.get("skip_combined_refresh"))
    return max_chunked_matrix_jobs() if chunked or fast_publish else max_batch_jobs()


def build_cached_lipsync_batch_command(payload: dict) -> list[str]:
    batch_id = slug(str(payload.get("batch_id") or payload.get("id_prefix") or "web-control")) or "web-control"
    count = int(payload.get("count") or 2)
    limit = cached_lipsync_batch_limit(payload)
    if count < 1 or count > limit:
        raise ValueError(f"count must be between 1 and {limit}")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    audio_cache_key = str(payload.get("audio_cache_key") or "").strip()
    if not audio_cache_key:
        raise ValueError("audio_cache_key is required")
    timeline = validated_lipsync_timeline_path(str(payload.get("lipsync_timeline") or ""))
    texture_size = int(payload.get("texture_size") or 768)
    if texture_size < 128 or texture_size > 4096:
        raise ValueError("texture_size must be between 128 and 4096")
    render_profile = str(payload.get("render_profile") or "control_lipsync")
    if render_profile not in {"fast_lipsync", "rough_lipsync", "thumbnail_lipsync", "control_lipsync"}:
        raise ValueError("unsupported render_profile")
    godot_url = godot_control_url()
    validation_urls = os.environ.get("GODOT_VALIDATION_URLS", "").strip()
    command = [
        "python3",
        "scripts/run_cached_lipsync_batch.py",
        "--batch-id",
        batch_id,
        "--count",
        str(count),
        "--accessories",
        csv_values(payload, "accessories", "aviator,pirate,necklace"),
        "--bases",
        csv_values(payload, "bases", "female,male"),
        "--animations",
        csv_values(payload, "animations", "talk_idle,present_explain,confident_point"),
        "--text",
        text,
        "--audio-cache-key",
        audio_cache_key,
        "--lipsync-timeline",
        timeline.as_posix(),
        "--render-profile",
        render_profile,
        "--texture-size",
        str(texture_size),
        "--godot-url",
        godot_url,
    ]
    if validation_urls:
        command.extend(["--validation-urls", validation_urls])
    if payload.get("start_index"):
        command.extend(["--start-index", str(int(payload["start_index"]))])
    if payload.get("promote_after", True):
        command.append("--promote-after")
    if normalize_bool(payload.get("skip_combined_refresh")):
        command.append("--skip-combined-refresh")
        command.extend(["--gallery-detail-mode", "compact"])
    if normalize_bool(payload.get("skip_godot_export")):
        command.append("--skip-godot-export")
    cache_lines = validated_cache_lines(payload)
    if not cache_lines and normalize_bool(payload.get("auto_cache_lines")):
        cache_lines = best_lipsync_cache_lines(lipsync_cache_entries(), limit=auto_cache_line_count(payload))
    if cache_lines:
        command.extend(["--cache-lines-json", json.dumps(cache_lines, separators=(",", ":"))])
    return command


def build_phrasebank_thumbnail_batch_command(payload: dict) -> list[str]:
    count = int(payload.get("count") or 16)
    limit = max_chunked_matrix_jobs()
    if count < 1 or count > limit:
        raise ValueError(f"count must be between 1 and {limit}")
    phrase_bank = ROOT / str(payload.get("phrase_bank") or DEFAULT_PHRASE_BANK)
    cache_lines = load_phrasebank_cache_lines(phrase_bank)
    first = cache_lines[0]
    command_payload = {
        **payload,
        "accessories": str(payload.get("accessories") or PHRASEBANK_THUMBNAIL_ACCESSORIES).split(","),
        "animations": str(payload.get("animations") or PHRASEBANK_THUMBNAIL_ANIMATIONS).split(","),
        "bases": str(payload.get("bases") or PHRASEBANK_THUMBNAIL_BASES).split(","),
        "cache_lines": cache_lines,
        "count": count,
        "render_profile": str(payload.get("render_profile") or PHRASEBANK_THUMBNAIL_RENDER_PROFILE),
        "skip_combined_refresh": not normalize_bool(payload.get("publish_combined")),
        "texture_size": int(payload.get("texture_size") or 768),
        "optimization_profile": str(payload.get("optimization_profile") or "auto"),
        "godot_url": godot_control_url(),
        "promote_after": normalize_bool(payload.get("promote_after")),
    }
    command_payload.setdefault("text", first["text"])
    command_payload.setdefault("audio_cache_key", first["audio_cache_key"])
    command_payload.setdefault("lipsync_timeline", first["lipsync_timeline"])
    return build_cached_lipsync_batch_command(command_payload)


def build_phrasebank_thumbnail_batch_pipeline(payload: dict) -> dict:
    count = int(payload.get("count") or 16)
    limit = max_chunked_matrix_jobs()
    if count < 1 or count > limit:
        raise ValueError(f"count must be between 1 and {limit}")
    phrase_bank = ROOT / str(payload.get("phrase_bank") or DEFAULT_PHRASE_BANK)
    cache_lines = load_phrasebank_cache_lines(phrase_bank)
    pipeline_payload = {
        **payload,
        "accessories": str(payload.get("accessories") or PHRASEBANK_THUMBNAIL_ACCESSORIES).split(","),
        "animations": str(payload.get("animations") or PHRASEBANK_THUMBNAIL_ANIMATIONS).split(","),
        "bases": str(payload.get("bases") or PHRASEBANK_THUMBNAIL_BASES).split(","),
        "cache_lines": cache_lines,
        "chunked_cached_lipsync": count > max_batch_jobs() or normalize_bool(payload.get("chunked")),
        "render_profile": str(payload.get("render_profile") or PHRASEBANK_THUMBNAIL_RENDER_PROFILE),
        "skip_combined_refresh": not normalize_bool(payload.get("publish_combined")),
        "texture_size": int(payload.get("texture_size") or 768),
        "optimization_profile": str(payload.get("optimization_profile") or "auto"),
        "defer_godot_export": normalize_bool(payload.get("defer_godot_export")),
        "godot_url": godot_control_url(),
    }
    first = cache_lines[0]
    pipeline_payload.setdefault("text", first["text"])
    pipeline_payload.setdefault("audio_cache_key", first["audio_cache_key"])
    pipeline_payload.setdefault("lipsync_timeline", first["lipsync_timeline"])
    pipeline = build_cached_lipsync_batch_pipeline(pipeline_payload)
    if normalize_bool(payload.get("render_cache_ready")):
        pipeline["chunk_workers"] = cached_lipsync_chunk_workers()
        pipeline["worker_policy"] = "cache-ready"
    else:
        pipeline["chunk_workers"] = render_chunk_workers()
        pipeline["worker_policy"] = "render-capped"
    return pipeline


def rotate_cache_lines(cache_lines: list[dict], offset: int) -> list[dict]:
    if not cache_lines:
        return []
    shift = offset % len(cache_lines)
    return cache_lines[shift:] + cache_lines[:shift]


def batch_result_path_for_batch_id(batch_id: str) -> Path:
    batch_slug = slug(batch_id) or "web-control"
    return ROOT / "results" / f"batch_person_factory_{batch_slug.replace('-', '_')}_latest.json"


def cached_lipsync_run_report_path_for_batch_id(batch_id: str) -> Path:
    batch_slug = slug(batch_id) or "web-control"
    return ROOT / "results" / f"run_cached_lipsync_batch_{batch_slug.replace('-', '_')}.json"


def cached_lipsync_pipeline_timing(started_at: float, child_batch_ids: list[str], chunk_workers: int) -> dict:
    wall_elapsed = round(time.monotonic() - started_at, 3)
    child_reports = []
    for batch_id in child_batch_ids:
        report = read_json_if_exists(cached_lipsync_run_report_path_for_batch_id(batch_id))
        if not report:
            continue
        child_reports.append(
            {
                "batch_id": batch_id,
                "status": report.get("status"),
                "elapsed_seconds": float(report.get("elapsed_seconds") or 0),
                "publish_combined": bool(report.get("publish_combined", True)),
                "slowest_stage": report.get("stage_summary", {}).get("slowest_stage"),
            }
        )
    child_elapsed = round(sum(item["elapsed_seconds"] for item in child_reports), 3)
    return {
        "wall_elapsed_seconds": wall_elapsed,
        "child_elapsed_seconds": child_elapsed,
        "child_report_count": len(child_reports),
        "chunk_workers": chunk_workers,
        "parallel_efficiency": round(child_elapsed / wall_elapsed, 3) if wall_elapsed > 0 else 0,
        "child_reports": child_reports,
    }


def cached_lipsync_estimate_accuracy(pipeline: dict, pipeline_timing: dict) -> dict:
    estimate = pipeline.get("estimate_snapshot", {}) if isinstance(pipeline.get("estimate_snapshot", {}), dict) else {}
    estimated_wall = estimate.get("estimated_wall_seconds")
    actual_wall = pipeline_timing.get("wall_elapsed_seconds")
    if estimated_wall is None or actual_wall is None:
        return {}
    estimated = float(estimated_wall)
    actual = float(actual_wall)
    if estimated <= 0:
        return {}
    error = round(actual - estimated, 3)
    ratio = round(actual / estimated, 3)
    absolute_error = round(abs(error), 3)
    return {
        "estimated_wall_seconds": round(estimated, 3),
        "actual_wall_seconds": round(actual, 3),
        "error_seconds": error,
        "absolute_error_seconds": absolute_error,
        "actual_to_estimate_ratio": ratio,
        "estimate_status": "fast" if ratio < 0.8 else "slow" if ratio > 1.2 else "close",
    }


def phrasebank_pipeline_estimate_snapshot(payload: dict, pipeline: dict, worker_count: int) -> dict:
    try:
        estimated_wall = float(payload.get("estimated_wall_seconds") or 0)
    except (TypeError, ValueError):
        estimated_wall = 0.0
    chunk_count = max(1, int(pipeline.get("chunk_count") or 1))
    chunks = [
        {
            "batch_id": job["batch_id"],
            "count": job["count"],
            "start_index": job["start_index"],
            "estimated_seconds": round(estimated_wall / chunk_count, 3) if estimated_wall > 0 else None,
        }
        for job in pipeline["jobs"]
    ]
    return {
        "estimated_wall_seconds": round(estimated_wall, 3) if estimated_wall > 0 else None,
        "estimated_serial_seconds": None,
        "estimated_parallel_efficiency": None,
        "chunk_workers": worker_count,
        "chunk_size": pipeline["chunk_size"],
        "chunks": chunks,
        "confidence": "queue-reference" if estimated_wall > 0 else "unknown",
        "warnings": [] if estimated_wall > 0 else ["missing-queue-estimate"],
    }


def recent_cached_lipsync_run_reports(limit: int = 30) -> list[dict]:
    reports = []
    paths = sorted(
        (ROOT / "results").glob("run_cached_lipsync_batch_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths:
        report = read_json_if_exists(path)
        elapsed = report.get("elapsed_seconds")
        if not elapsed:
            continue
        checked_count = int(report.get("validation", {}).get("checked_count") or report.get("count") or 0)
        if checked_count <= 0:
            continue
        matrix_report = {}
        matrix_report_value = report.get("paths", {}).get("matrix_report")
        if matrix_report_value:
            matrix_report = read_json_if_exists(ROOT / matrix_report_value)
        render_dedupe = matrix_report.get("render_dedupe", {})
        reports.append(
            {
                "batch_id": report.get("batch_id") or path.stem.removeprefix("run_cached_lipsync_batch_"),
                "elapsed_seconds": float(elapsed),
                "checked_count": checked_count,
                "publish_combined": report.get("publish_combined"),
                "slowest_stage": report.get("stage_summary", {}).get("slowest_stage"),
                "render_dedupe_enabled": bool(render_dedupe.get("materialized_duplicate_count", 0)),
            }
        )
        if len(reports) >= limit:
            break
    return reports


def estimate_chunk_wall_seconds(chunks: list[dict], worker_count: int) -> float:
    workers = max(1, min(worker_count, max(1, len(chunks))))
    lanes = [0.0 for _ in range(workers)]
    for chunk in sorted(chunks, key=lambda item: item["estimated_seconds"], reverse=True):
        lane_index = lanes.index(min(lanes))
        lanes[lane_index] += float(chunk["estimated_seconds"])
    return round(max(lanes) if lanes else 0.0, 1)


def balanced_chunk_size(total_count: int, max_size: int) -> int:
    chunk_count = max(1, math.ceil(total_count / max(1, max_size)))
    return max(1, math.ceil(total_count / chunk_count))


def scaled_deduped_timing_sample(count: int, reports: list[dict]) -> dict | None:
    candidates = [
        report
        for report in reports
        if int(report.get("checked_count") or 0) > 0 and float(report.get("elapsed_seconds") or 0) > 0
    ]
    if not candidates:
        return None
    smaller_or_equal = [report for report in candidates if int(report["checked_count"]) <= count]
    if smaller_or_equal:
        sample = max(smaller_or_equal, key=lambda report: int(report["checked_count"]))
    else:
        sample = min(candidates, key=lambda report: abs(int(report["checked_count"]) - count))
    sample_count = int(sample["checked_count"])
    sample_elapsed = float(sample["elapsed_seconds"])
    scale = count / max(1, sample_count)
    if count < sample_count:
        scale = max(0.6, scale)
    return {
        "estimated_seconds": sample_elapsed * scale,
        "source_sample_count": sample_count,
        "source_batch_id": sample.get("batch_id"),
    }


def estimate_cached_lipsync_batch(payload: dict) -> dict:
    pipeline = build_cached_lipsync_batch_pipeline(payload)
    reports = recent_cached_lipsync_run_reports()
    deduped_reports = [report for report in reports if report.get("render_dedupe_enabled")]
    timing_reports = deduped_reports or reports
    timing_model = "render-deduped" if deduped_reports else "all-samples"
    per_count: dict[int, list[float]] = {}
    per_asset = []
    for report in timing_reports:
        count = int(report["checked_count"])
        elapsed = float(report["elapsed_seconds"])
        per_count.setdefault(count, []).append(elapsed)
        per_asset.append(elapsed / max(1, count))
    fallback_per_asset = sum(per_asset) / len(per_asset) if per_asset else 13.0
    fallback_overhead = 0.0 if per_asset else 1.0

    chunks = []
    warnings = set()
    for job in pipeline["jobs"]:
        count = int(job.get("count") or 1)
        samples = per_count.get(count, [])
        scaled_sample = None if samples or not deduped_reports else scaled_deduped_timing_sample(count, deduped_reports)
        if samples:
            estimated = sum(samples) / len(samples)
            confidence = "sampled"
        elif scaled_sample:
            estimated = float(scaled_sample["estimated_seconds"])
            confidence = "scaled-deduped-sample"
            warnings.add("deduped-count-scaled")
        else:
            estimated = fallback_per_asset * count + fallback_overhead
            confidence = "extrapolated"
            warnings.add("chunk-count-extrapolated")
        chunk = {
            "batch_id": job.get("batch_id"),
            "count": count,
            "estimated_seconds": round(estimated, 1),
            "sample_count": len(samples),
            "confidence": confidence,
        }
        if scaled_sample:
            chunk["source_sample_count"] = scaled_sample["source_sample_count"]
            chunk["source_batch_id"] = scaled_sample["source_batch_id"]
        chunks.append(chunk)
    worker_count = min(cached_lipsync_chunk_workers(), max(1, len(chunks))) if chunks else 1
    serial = round(sum(chunk["estimated_seconds"] for chunk in chunks), 1)
    wall = estimate_chunk_wall_seconds(chunks, worker_count)
    worker_options = [
        {
            "workers": workers,
            "estimated_wall_seconds": estimate_chunk_wall_seconds(chunks, workers),
        }
        for workers in range(1, min(4, max(1, len(chunks))) + 1)
    ]
    recommendations = []
    if pipeline["chunk_count"] > 1 and worker_count == 1:
        recommended_workers = min(2, pipeline["chunk_count"])
        recommended_wall = estimate_chunk_wall_seconds(chunks, recommended_workers)
        recommendations.append(
            {
                "type": "enable-parallel-chunks",
                "label": f"Enable {recommended_workers} cached lip-sync chunk workers for this batch.",
                "estimated_wall_seconds": recommended_wall,
                "estimated_saved_seconds": round(max(0.0, wall - recommended_wall), 1),
                "command": (
                    f"WEBAPP_MAX_CONCURRENT_JOBS={recommended_workers} "
                    f"PERSON_FACTORY_CHUNK_WORKERS={recommended_workers} "
                    "docker compose --profile webapp up -d --build webapp"
                ),
            }
        )
    return {
        "status": "ok",
        "batch_id": pipeline["batch_id"],
        "count": pipeline["count"],
        "chunked": pipeline["chunked"],
        "chunk_count": pipeline["chunk_count"],
        "chunk_size": pipeline["chunk_size"],
        "chunk_workers": worker_count,
        "sample_count": len(timing_reports),
        "timing_model": timing_model,
        "confidence": "extrapolated" if warnings else "sampled",
        "warnings": sorted(warnings),
        "recommendations": recommendations,
        "worker_options": worker_options,
        "estimated_serial_seconds": serial,
        "estimated_wall_seconds": wall,
        "estimated_parallel_efficiency": round(serial / wall, 2) if wall > 0 else 0,
        "chunks": chunks,
    }


def godot_lipsync_validation_path_for_batch_id(batch_id: str) -> Path:
    batch_slug = slug(batch_id) or "web-control"
    return ROOT / "results" / f"godot_lipsync_validation_{batch_slug.replace('-', '_')}_latest.json"


def batch_gallery_path_for_batch_id(batch_id: str) -> Path:
    batch_slug = slug(batch_id) or "web-control"
    return OUTPUT_DIR / f"person_factory_{batch_slug}.html"


def inferred_cached_lipsync_parent_gallery(job: dict) -> dict:
    pipeline = job.get("request", {}).get("pipeline", {})
    if not isinstance(pipeline, dict) or pipeline.get("type") != "cached-lipsync-batch":
        return {}
    job_id = str(job.get("id", ""))
    marker = "-cached-lipsync-pipeline-"
    if marker not in job_id:
        return {}
    batch_id = job_id.split(marker, 1)[0]
    gallery = batch_gallery_path_for_batch_id(batch_id)
    result = batch_result_path_for_batch_id(batch_id)
    validation = godot_lipsync_validation_path_for_batch_id(batch_id)
    if not gallery.exists() or not result.exists():
        return {}
    return {
        "status": "ok",
        "batch_id": batch_id,
        "gallery": str(gallery.relative_to(ROOT)),
        "batch_result": str(result.relative_to(ROOT)),
        "validation_result": str(validation.relative_to(ROOT)) if validation.exists() else "",
    }


def build_cached_lipsync_parent_gallery(
    base_batch_id: str,
    child_batch_ids: list[str],
    pipeline_timing: dict | None = None,
    estimate_accuracy: dict | None = None,
    export_godot: bool = False,
    godot_url: str | None = None,
) -> dict:
    batch_id = slug(base_batch_id) or "web-control"
    batch_paths = [batch_result_path_for_batch_id(child_id) for child_id in child_batch_ids]
    missing_batches = [str(path.relative_to(ROOT)) for path in batch_paths if not path.exists()]
    if missing_batches:
        return {
            "status": "error",
            "error": "missing child batch result",
            "missing_batches": missing_batches,
        }

    validation_reports = [
        read_json_if_exists(godot_lipsync_validation_path_for_batch_id(child_id))
        for child_id in child_batch_ids
    ]
    validation = merge_godot_lipsync_validations(validation_reports)
    combined = combine_batch_results(batch_paths, godot_lipsync_validation=validation)
    combined["manifest"] = f"chunked-cached-lipsync:{batch_id}"
    combined["batch_id"] = batch_id
    combined["chunked_parent"] = {
        "chunk_count": len(child_batch_ids),
        "child_batch_ids": child_batch_ids,
    }
    if pipeline_timing:
        combined["pipeline_timing"] = pipeline_timing
        combined["chunked_parent"]["pipeline_timing"] = pipeline_timing
    if estimate_accuracy:
        combined["estimate_accuracy"] = estimate_accuracy
        combined["chunked_parent"]["estimate_accuracy"] = estimate_accuracy

    parent_result = batch_result_path_for_batch_id(batch_id)
    parent_validation = godot_lipsync_validation_path_for_batch_id(batch_id)
    parent_gallery = batch_gallery_path_for_batch_id(batch_id)
    parent_result.parent.mkdir(parents=True, exist_ok=True)
    parent_validation.parent.mkdir(parents=True, exist_ok=True)
    parent_gallery.parent.mkdir(parents=True, exist_ok=True)
    parent_result.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    parent_validation.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    parent_gallery.write_text(build_gallery(combined, parent_gallery), encoding="utf-8")
    godot_export = {}
    if export_godot:
        resolved_godot_url = (godot_url or godot_control_url()).rstrip("/")
        batch_result_workspace = f"/workspace/{parent_result.relative_to(ROOT).as_posix()}"
        asset_ids = []
        for job in combined.get("jobs", []):
            if not isinstance(job, dict):
                continue
            asset_id = str(job.get("id", "")).strip()
            if asset_id and asset_id not in asset_ids:
                asset_ids.append(asset_id)
        reload_result = post_json(f"{resolved_godot_url}/reload-assets", {"batch_result": batch_result_workspace})
        export_result = post_json(
            f"{resolved_godot_url}/export-all-game-assets",
            {"skip_existing": True, "asset_ids": asset_ids},
        )
        godot_export = {
            "status": "ok" if reload_result.get("status") == "ok" and export_result.get("status") == "ok" else "review",
            "reload": reload_result,
            "export": export_result,
        }
    return {
        "status": "ok",
        "batch_id": batch_id,
        "job_count": len(combined.get("jobs", [])),
        "child_batch_ids": child_batch_ids,
        "batch_result": str(parent_result.relative_to(ROOT)),
        "gallery": str(parent_gallery.relative_to(ROOT)),
        "validation_result": str(parent_validation.relative_to(ROOT)),
        "validation": validation,
        "godot_export": godot_export,
    }


def build_cached_lipsync_batch_pipeline(payload: dict) -> dict:
    count = int(payload.get("count") or 2)
    chunked = normalize_bool(payload.get("chunked_cached_lipsync") or payload.get("chunked"))
    limit = cached_lipsync_batch_limit(payload)
    if count < 1 or count > limit:
        raise ValueError(f"count must be between 1 and {limit}")
    max_chunk_size = max_batch_jobs()
    chunk_size = balanced_chunk_size(count, max_chunk_size) if chunked else count
    base_batch_id = slug(str(payload.get("batch_id") or payload.get("id_prefix") or "web-control")) or "web-control"
    cache_lines = validated_cache_lines(payload)
    jobs = []
    for index, start in enumerate(range(1, count + 1, chunk_size), start=1):
        chunk_count = min(chunk_size, count - start + 1)
        chunk_batch_id = f"{base_batch_id}-chunk-{index:03d}" if chunked else base_batch_id
        chunk_payload = {
            **payload,
            "batch_id": chunk_batch_id,
            "count": chunk_count,
            "start_index": start,
        }
        if chunked:
            chunk_payload["skip_combined_refresh"] = True
            if normalize_bool(payload.get("defer_godot_export")):
                chunk_payload["skip_godot_export"] = True
        if cache_lines:
            chunk_payload["cache_lines"] = rotate_cache_lines(cache_lines, start - 1)
        command = build_cached_lipsync_batch_command(chunk_payload)
        jobs.append(
            {
                "id": f"{chunk_batch_id}-cached-lipsync",
                "batch_id": chunk_batch_id,
                "count": chunk_count,
                "start_index": start,
                "request": {
                    "id": f"{chunk_batch_id}-cached-lipsync",
                    "name": "Cached Lip-Sync Batch Chunk" if chunked else "Cached Lip-Sync Batch",
                    "text": f"{chunk_count} promoted controllable people for {chunk_batch_id}",
                    "batch_id": chunk_batch_id,
                    "pipeline": {"type": "cached-lipsync-batch-chunk", "promote_after": "--promote-after" in command},
                },
                "command": command,
            }
        )
        if not chunked:
            break
    return {
        "status": "ok",
        "batch_id": base_batch_id,
        "chunked": chunked,
        "count": count,
        "chunk_size": chunk_size,
        "chunk_count": len(jobs),
        "publish_combined": not normalize_bool(payload.get("skip_combined_refresh")),
        "jobs": jobs,
    }


def publish_pipeline_outputs(validation_id_prefix: str = "") -> dict:
    result = {"gallery": build_combined_gallery_result()}
    try:
        result["godot"] = sync_godot_assets()
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        result["godot"] = {"status": "review", "error": str(exc)}
    if result["godot"].get("status") == "ok":
        try:
            result["godot_lipsync_validation"] = validate_godot_lipsync_outputs(validation_id_prefix)
            result["gallery_after_validation"] = build_combined_gallery_result()
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            result["godot_lipsync_validation"] = {"returncode": 1, "status": "review", "error": str(exc)}
    validation = result.get("godot_lipsync_validation", {})
    validation_report = validation.get("report", {}) if isinstance(validation, dict) else {}
    gallery_ok = result["gallery"]["returncode"] == 0
    final_gallery_ok = result.get("gallery_after_validation", result["gallery"]).get("returncode") == 0
    godot_ok = result["godot"].get("status") == "ok"
    validation_ok = not validation or (
        validation.get("returncode") == 0 and validation_report.get("status", "ok") == "ok"
    )
    result["status"] = "ok" if gallery_ok and final_gallery_ok and godot_ok and validation_ok else "review"
    return result


def run_job(job_id: str, command: list[str]) -> None:
    with JOB_SEMAPHORE:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{job_id}.log"
        JOB_STORE.update_job(job_id, status="running")
        with log_path.open("w", encoding="utf-8") as log:
            log.write("$ " + " ".join(command) + "\n")
            log.flush()
            completed = subprocess.run(command, cwd=ROOT, text=True, stdout=log, stderr=subprocess.STDOUT)
        status = "ok" if completed.returncode == 0 else "error"
        JOB_STORE.update_job(job_id, status=status, returncode=completed.returncode)
        command_text = " ".join(command)
        command_handles_combined = "scripts/run_cached_lipsync_batch.py" in command_text
        if status == "ok" and "--skip-combined-refresh" not in command and not command_handles_combined:
            subprocess.run(build_refresh_combined_gallery_command(), cwd=ROOT, check=False)


def run_matrix_warm_render_pipeline(pipeline_id: str, pipeline: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{pipeline_id}.log"
    child_job_ids: list[str] = []
    warm_job_ids: list[str] = []
    render_job_ids: list[str] = []
    render_item_ids: list[str] = [job["request"]["id"] for job in pipeline.get("render_jobs", [])]

    def write_log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(message.rstrip() + "\n")

    def run_child_jobs(stage: str, job_specs: list[dict]) -> list[str]:
        if not job_specs:
            write_log(f"{stage}: no jobs needed")
            return []
        ids = []
        write_log(f"{stage}: planned {len(job_specs)} jobs")
        for job_spec in job_specs:
            job = JOB_STORE.create_job(job_spec["request"], job_spec["command"])
            ids.append(job["id"])
            child_job_ids.append(job["id"])
            write_log(f"{stage}: running {job['id']}")
            run_job(job["id"], job["command"])
            finished = JOB_STORE.get_job(job["id"])
            if finished.get("status") != "ok":
                raise RuntimeError(f"{stage} failed: {job['id']}")
        write_log(f"{stage}: completed {len(ids)} jobs")
        return ids

    try:
        JOB_STORE.update_job(pipeline_id, status="running")
        write_log("$ pipeline matrix-warm-render")
        write_log(
            "plan: "
            f"{pipeline['warm_job_count']} warm jobs, "
            f"{pipeline['skipped_group_count']} warm groups skipped, "
            f"{pipeline['render_job_count']} render jobs"
        )
        warm_job_ids = run_child_jobs("warm-cache", pipeline["warm_jobs"])
        batch_jobs = pipeline.get("render_batch_jobs") or ([pipeline["render_batch_job"]] if pipeline.get("render_batch_job") else [])
        if batch_jobs:
            for batch_job in batch_jobs:
                requests_path = ROOT / batch_job["requests_json"]
                requests_path.parent.mkdir(parents=True, exist_ok=True)
                requests_path.write_text(
                    json.dumps(batch_job["requests"], indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                write_log(f"render-batch: wrote {len(batch_job['requests'])} requests to {batch_job['requests_json']}")
            render_job_ids = run_child_jobs("render-batch", batch_jobs)
        elif pipeline.get("render_batch_job"):
            batch_job = pipeline["render_batch_job"]
            requests_path = ROOT / batch_job["requests_json"]
            requests_path.parent.mkdir(parents=True, exist_ok=True)
            requests_path.write_text(json.dumps(batch_job["requests"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
            write_log(f"render-batch: wrote {len(batch_job['requests'])} requests to {batch_job['requests_json']}")
            render_job_ids = run_child_jobs("render-batch", [batch_job])
        else:
            render_job_ids = run_child_jobs("render-matrix", pipeline["render_jobs"])
        validation_id_prefix = pipeline.get("validation_id_prefix", "")
        publish_result = (
            publish_pipeline_outputs(validation_id_prefix)
            if validation_id_prefix
            else publish_pipeline_outputs()
        )
        JOB_STORE.update_job(
            pipeline_id,
            status="ok",
            returncode=0,
            child_job_ids=child_job_ids,
            warm_job_ids=warm_job_ids,
            render_job_ids=render_job_ids,
            render_item_ids=render_item_ids,
            publish_result=publish_result,
        )
        write_log(f"publish: {publish_result['status']}")
        write_log("pipeline: ok")
    except Exception as exc:  # noqa: BLE001 - worker should report any pipeline failure to the UI.
        write_log(f"pipeline: error: {exc}")
        JOB_STORE.update_job(
            pipeline_id,
            status="error",
            returncode=1,
            error=str(exc),
            child_job_ids=child_job_ids,
            warm_job_ids=warm_job_ids,
            render_job_ids=render_job_ids,
            render_item_ids=render_item_ids,
        )


def run_cached_lipsync_batch_pipeline(pipeline_id: str, pipeline: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{pipeline_id}.log"
    started_at = time.monotonic()
    child_job_ids: list[str] = []
    log_lock = threading.Lock()

    def write_log(message: str) -> None:
        with log_lock:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(message.rstrip() + "\n")

    def run_chunk(job: dict) -> None:
        write_log(f"chunk: running {job['id']}")
        run_job(job["id"], job["command"])
        finished = JOB_STORE.get_job(job["id"])
        if finished.get("status") != "ok":
            raise RuntimeError(f"cached lip-sync chunk failed: {job['id']}")
        write_log(f"chunk: ok {job['id']}")

    try:
        JOB_STORE.update_job(pipeline_id, status="running")
        write_log("$ pipeline cached-lipsync-batch")
        job_specs = pipeline.get("jobs", [])
        jobs = JOB_STORE.create_jobs([(job_spec["request"], job_spec["command"]) for job_spec in job_specs])
        child_job_ids.extend(job["id"] for job in jobs)
        worker_count = cached_lipsync_pipeline_worker_count(pipeline, jobs)
        write_log(f"chunks: planned {len(jobs)} jobs with {worker_count} worker(s)")
        chunks_ready_at = time.monotonic()
        chunk_started_at = time.monotonic()
        if worker_count == 1:
            for job in jobs:
                run_chunk(job)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(run_chunk, job) for job in jobs]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
        chunk_wall_elapsed = round(time.monotonic() - chunk_started_at, 3)
        parent_gallery = {}
        parent_gallery_seconds = 0.0
        child_batch_ids = [
            str(job_spec.get("batch_id", "")).strip()
            for job_spec in pipeline.get("jobs", [])
            if str(job_spec.get("batch_id", "")).strip()
        ]
        timing_summary_started_at = time.monotonic()
        pipeline_timing = cached_lipsync_pipeline_timing(started_at, child_batch_ids, worker_count)
        timing_summary_seconds = round(time.monotonic() - timing_summary_started_at, 3)
        pre_chunk_overhead_seconds = round(max(0.0, chunks_ready_at - started_at), 3)
        pipeline_timing["chunk_wall_elapsed_seconds"] = chunk_wall_elapsed
        pipeline_timing["pre_chunk_overhead_seconds"] = pre_chunk_overhead_seconds
        pipeline_timing["timing_summary_seconds"] = timing_summary_seconds
        pipeline_timing["orchestration_overhead_seconds"] = round(
            max(0.0, float(pipeline_timing.get("wall_elapsed_seconds", 0.0)) - chunk_wall_elapsed),
            3,
        )
        estimate_accuracy = cached_lipsync_estimate_accuracy(pipeline, pipeline_timing)
        if pipeline.get("batch_id") and child_batch_ids:
            parent_gallery_started = time.monotonic()
            parent_gallery = build_cached_lipsync_parent_gallery(
                pipeline.get("batch_id", "web-control"),
                child_batch_ids,
                pipeline_timing=pipeline_timing,
                estimate_accuracy=estimate_accuracy,
                export_godot=True,
            )
            parent_gallery_seconds = round(time.monotonic() - parent_gallery_started, 3)
            if parent_gallery.get("status") != "ok":
                raise RuntimeError(f"cached lip-sync parent gallery failed: {parent_gallery.get('error', 'unknown')}")
            if pipeline.get("publish_combined"):
                subprocess.run(build_refresh_combined_gallery_command(), cwd=ROOT, check=False)
        JOB_STORE.update_job(
            pipeline_id,
            status="ok",
            returncode=0,
            child_job_ids=child_job_ids,
            chunk_count=len(child_job_ids),
            chunk_workers=worker_count,
            pipeline_timing=pipeline_timing,
            parent_gallery_seconds=parent_gallery_seconds,
            estimate_accuracy=estimate_accuracy,
            parent_gallery=parent_gallery,
        )
        if parent_gallery:
            write_log(f"parent-gallery: {parent_gallery['gallery']}")
        write_log(
            "timing: "
            f"wall={pipeline_timing['wall_elapsed_seconds']}s "
            f"chunk-wall={pipeline_timing['chunk_wall_elapsed_seconds']}s "
            f"child={pipeline_timing['child_elapsed_seconds']}s "
            f"parent-gallery={parent_gallery_seconds}s"
        )
        write_log("pipeline: ok")
    except Exception as exc:  # noqa: BLE001 - worker should report any pipeline failure to the UI.
        write_log(f"pipeline: error: {exc}")
        JOB_STORE.update_job(
            pipeline_id,
            status="error",
            returncode=1,
            error=str(exc),
            child_job_ids=child_job_ids,
        )


class PersonFactoryHandler(BaseHTTPRequestHandler):
    server_version = "PersonFactoryWebapp/1.0"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        godot_get_routes = {
            "/api/godot/health": "/health",
            "/api/godot/assets": "/assets",
            "/api/godot/face-profile": "/face-profile",
            "/api/godot/lipsync-status": "/lipsync-status",
        }
        if parsed.path in godot_get_routes:
            try:
                json_response(self, 200, proxy_godot_get(godot_get_routes[parsed.path]))
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                json_response(self, 502, {"status": "error", "error": str(exc)})
            return
        if parsed.path == "/api/jobs":
            source_jobs, compact, include_summary, include_logs = limited_jobs_for_response(parse_qs(parsed.query))
            jobs = [
                compact_job_for_list(job, include_summary=include_summary, include_logs=include_logs)
                if compact
                else job_with_log(job)
                for job in source_jobs
            ]
            json_response(
                self,
                200,
                {"jobs": jobs, "stats": JOB_STORE.stats(max_concurrent=JOB_MAX_CONCURRENT)},
            )
            return
        if parsed.path == "/api/options":
            json_response(self, 200, catalog_options())
            return
        if parsed.path == "/api/storage":
            json_response(self, 200, audit_storage(root=ROOT))
            return
        if parsed.path == "/api/galleries":
            params = parse_qs(parsed.query)
            try:
                limit = int(params.get("limit", ["12"])[0])
            except ValueError:
                limit = 12
            json_response(self, 200, recent_batch_galleries(limit=limit))
            return
        if parsed.path == "/api/characters":
            json_response(self, 200, character_catalog_page(parse_qs(parsed.query)))
            return
        if parsed.path == "/api/lipsync-cache":
            json_response(self, 200, lipsync_cache_response())
            return
        if parsed.path == "/api/placement/assets":
            qualities = set(accessory_quality_filter())
            json_response(self, 200, placement_assets(ROOT / "config/poly_pizza_assets.json", include_qualities=qualities))
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            try:
                json_response(self, 200, {"job": job_with_log(JOB_STORE.get_job(job_id))})
            except KeyError:
                json_response(self, 404, {"error": "unknown job"})
            return
        if parsed.path in {"/", "/factory.html"}:
            static_response(self, WEBAPP_DIR / "factory.html")
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        godot_proxy_routes = {
            "/api/godot/load": "/load",
            "/api/godot/lipsync": "/lipsync",
            "/api/godot/camera": "/camera",
            "/api/godot/expression-preset": "/expression-preset",
            "/api/godot/viseme": "/viseme",
            "/api/godot/animation": "/animation",
        }
        if parsed.path not in {
            "/api/jobs",
            "/api/batch-jobs",
            "/api/matrix-jobs",
            "/api/matrix-plan",
            "/api/cached-lipsync-estimate",
            "/api/refresh-combined-gallery",
            "/api/matrix-cache-warm",
            "/api/matrix-warm-render",
            "/api/promote-batch",
            "/api/cached-lipsync-batch",
            "/api/phrasebank-thumbnail-batch",
            "/api/placement/plan",
            "/api/placement/suggest",
            "/api/godot/sync",
            *godot_proxy_routes.keys(),
        }:
            json_response(self, 404, {"error": "not found"})
            return
        if parsed.path == "/api/godot/sync":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                json_response(self, 200, sync_godot_assets(batch_result=payload.get("batch_result")))
            except json.JSONDecodeError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                json_response(self, 502, {"status": "error", "error": str(exc)})
            return
        if parsed.path in godot_proxy_routes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                json_response(self, 200, proxy_godot_post(godot_proxy_routes[parsed.path], payload))
            except json.JSONDecodeError as exc:
                json_response(self, 400, {"error": str(exc)})
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                json_response(self, 502, {"status": "error", "error": str(exc)})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if parsed.path == "/api/placement/plan":
                json_response(
                    self,
                    200,
                    placement_plan(
                        str(payload.get("asset_key") or payload.get("asset") or ""),
                        profile=str(payload.get("profile") or "rough"),
                        config_path=ROOT / "config/poly_pizza_assets.json",
                    ),
                )
                return
            if parsed.path == "/api/placement/suggest":
                json_response(self, 200, placement_suggestion(payload, config_path=ROOT / "config/poly_pizza_assets.json"))
                return
            validate_catalog_choices(payload)
            if parsed.path == "/api/matrix-plan":
                json_response(self, 200, matrix_cache_preflight_plan(payload, root=ROOT))
                return
            if parsed.path == "/api/cached-lipsync-estimate":
                json_response(self, 200, estimate_cached_lipsync_batch(payload))
                return
            if parsed.path == "/api/refresh-combined-gallery":
                job_id = generated_job_id("refresh-combined-gallery")
                request = {
                    "id": job_id,
                    "name": "Refresh Global Gallery",
                    "text": "Rebuild the global Person Factory gallery and contact sheet",
                    "pipeline": {"type": "refresh-combined-gallery"},
                }
                jobs = [JOB_STORE.create_job(request, build_refresh_combined_gallery_command())]
                json_response(self, 202, {"job": jobs[0]})
                for job in jobs:
                    thread = threading.Thread(target=run_job, args=(job["id"], job["command"]), daemon=True)
                    thread.start()
                return
            if parsed.path == "/api/matrix-cache-warm":
                warm = build_matrix_cache_warm_jobs(payload, root=ROOT)
                if warm["dry_run"]:
                    json_response(self, 200, warm)
                    return
                jobs = JOB_STORE.create_jobs(
                    [(warm_job["request"], warm_job["command"]) for warm_job in warm["warm_jobs"]]
                )
                for job in jobs:
                    thread = threading.Thread(target=run_job, args=(job["id"], job["command"]), daemon=True)
                    thread.start()
                json_response(self, 202, {**warm, "jobs": jobs})
                return
            if parsed.path == "/api/matrix-warm-render":
                pipeline = build_matrix_warm_render_pipeline(payload, root=ROOT)
                if pipeline["dry_run"]:
                    json_response(self, 200, pipeline)
                    return
                prefix = slug(str(payload.get("id_prefix") or "web-matrix")) or "web-matrix"
                pipeline_id = generated_job_id(f"{prefix}-pipeline")
                pipeline_request = {
                    "id": pipeline_id,
                    "name": "Warm + Render Matrix",
                    "text": (
                        f"{pipeline['warm_job_count']} cache warm jobs, "
                        f"{pipeline['render_job_count']} matrix render jobs"
                    ),
                    "pipeline": {
                        "type": "matrix-warm-render",
                        "stage_order": pipeline["stage_order"],
                        "warm_job_count": pipeline["warm_job_count"],
                        "render_job_count": pipeline["render_job_count"],
                        "planned_child_job_count": pipeline["planned_child_job_count"],
                    },
                }
                pipeline_job = JOB_STORE.create_job(pipeline_request, ["pipeline", "matrix-warm-render"])
                thread = threading.Thread(
                    target=run_matrix_warm_render_pipeline,
                    args=(pipeline_job["id"], pipeline),
                    daemon=True,
                )
                thread.start()
                json_response(self, 202, {**pipeline, "pipeline_job": pipeline_job})
                return
            if parsed.path == "/api/promote-batch":
                command = build_promote_batch_command(payload)
                batch_result = command[2]
                job_id = generated_job_id("promote-batch")
                request = {
                    "id": job_id,
                    "name": "Promote Batch",
                    "text": f"Standard optimize {batch_result}",
                    "batch_result": batch_result,
                    "pipeline": {"type": "promote-batch"},
                }
                jobs = [JOB_STORE.create_job(request, command)]
            elif parsed.path == "/api/cached-lipsync-batch":
                pipeline = build_cached_lipsync_batch_pipeline(payload)
                if pipeline["chunked"]:
                    estimate_snapshot = estimate_cached_lipsync_batch(payload)
                    pipeline["estimate_snapshot"] = {
                        "estimated_wall_seconds": estimate_snapshot["estimated_wall_seconds"],
                        "estimated_serial_seconds": estimate_snapshot["estimated_serial_seconds"],
                        "estimated_parallel_efficiency": estimate_snapshot["estimated_parallel_efficiency"],
                        "chunk_workers": estimate_snapshot["chunk_workers"],
                        "chunk_size": estimate_snapshot["chunk_size"],
                        "chunks": estimate_snapshot["chunks"],
                        "confidence": estimate_snapshot["confidence"],
                        "warnings": estimate_snapshot["warnings"],
                    }
                    prefix = slug(str(payload.get("batch_id") or payload.get("id_prefix") or "web-control")) or "web-control"
                    pipeline_id = generated_job_id(f"{prefix}-cached-lipsync-pipeline")
                    pipeline_request = {
                        "id": pipeline_id,
                        "name": "Chunked Cached Lip-Sync Batch",
                        "text": f"{pipeline['count']} promoted controllable people in {pipeline['chunk_count']} chunks",
                        "pipeline": {
                            "type": "cached-lipsync-batch",
                            "chunked": True,
                            "chunk_count": pipeline["chunk_count"],
                            "estimated_wall_seconds": pipeline["estimate_snapshot"]["estimated_wall_seconds"],
                            "chunk_workers": pipeline["estimate_snapshot"]["chunk_workers"],
                        },
                    }
                    pipeline_job = JOB_STORE.create_job(pipeline_request, ["pipeline", "cached-lipsync-batch"])
                    thread = threading.Thread(
                        target=run_cached_lipsync_batch_pipeline,
                        args=(pipeline_job["id"], pipeline),
                        daemon=True,
                    )
                    thread.start()
                    json_response(self, 202, {**pipeline, "pipeline_job": pipeline_job})
                    return
                job_spec = pipeline["jobs"][0]
                jobs = [JOB_STORE.create_job(job_spec["request"], job_spec["command"])]
            elif parsed.path == "/api/phrasebank-thumbnail-batch":
                batch_id = slug(str(payload.get("batch_id") or payload.get("id_prefix") or "web-thumb")) or "web-thumb"
                count = int(payload.get("count") or 16)
                if normalize_bool(payload.get("chunked")):
                    pipeline = build_phrasebank_thumbnail_batch_pipeline(payload)
                    worker_count = cached_lipsync_pipeline_worker_count(pipeline, pipeline["jobs"])
                    pipeline["estimate_snapshot"] = phrasebank_pipeline_estimate_snapshot(payload, pipeline, worker_count)
                    pipeline_id = generated_job_id(f"{batch_id}-phrasebank-thumbnail-pipeline")
                    pipeline_request = {
                        "id": pipeline_id,
                        "name": "Chunked Phrase-Bank Thumbnail Batch",
                        "text": f"{pipeline['count']} phrase-bank thumbnail people in {pipeline['chunk_count']} chunks",
                        "batch_id": batch_id,
                        "pipeline": {
                            "type": "phrasebank-thumbnail-batch",
                            "chunked": True,
                            "chunk_count": pipeline["chunk_count"],
                            "estimated_wall_seconds": pipeline["estimate_snapshot"]["estimated_wall_seconds"],
                            "chunk_workers": pipeline["estimate_snapshot"]["chunk_workers"],
                        },
                    }
                    pipeline_job = JOB_STORE.create_job(pipeline_request, ["pipeline", "phrasebank-thumbnail-batch"])
                    thread = threading.Thread(
                        target=run_cached_lipsync_batch_pipeline,
                        args=(pipeline_job["id"], pipeline),
                        daemon=True,
                    )
                    thread.start()
                    json_response(self, 202, {**pipeline, "pipeline_job": pipeline_job})
                    return
                command = build_phrasebank_thumbnail_batch_command(payload)
                request = {
                    "id": generated_job_id(f"{batch_id}-phrasebank-thumbnail"),
                    "name": "Phrase-Bank Thumbnail Batch",
                    "text": f"{count} phrase-bank thumbnail people",
                    "batch_id": batch_id,
                    "pipeline": {"type": "phrasebank-thumbnail-batch"},
                }
                jobs = [JOB_STORE.create_job(request, command)]
            elif parsed.path == "/api/batch-jobs":
                requests = normalize_batch_job_requests(payload)
                requests_and_commands = [(request, build_text_person_command(request)) for request in requests]
                jobs = JOB_STORE.create_jobs(requests_and_commands)
            elif parsed.path == "/api/matrix-jobs":
                requests = normalize_matrix_job_requests(payload)
                requests_and_commands = [(request, build_text_person_command(request)) for request in requests]
                jobs = JOB_STORE.create_jobs(requests_and_commands)
            else:
                request = normalize_job_request(payload)
                command = build_text_person_command(request)
                jobs = [JOB_STORE.create_job(request, command)]
        except (json.JSONDecodeError, ValueError) as exc:
            json_response(self, 400, {"error": str(exc)})
            return
        for job in jobs:
            thread = threading.Thread(target=run_job, args=(job["id"], job["command"]), daemon=True)
            thread.start()
        payload_key = "jobs" if parsed.path in {"/api/batch-jobs", "/api/matrix-jobs"} else "job"
        json_response(self, 202, {payload_key: jobs if payload_key == "jobs" else jobs[0]})

    def serve_static(self, raw_path: str) -> None:
        path = unquote(raw_path).lstrip("/")
        if path.startswith("webapp/"):
            candidate = WEBAPP_DIR / path.removeprefix("webapp/")
        else:
            candidate = OUTPUT_DIR / (path or "index.html")
        try:
            candidate.resolve().relative_to(ROOT.resolve())
        except ValueError:
            self.send_error(403)
            return
        static_response(self, candidate)

    def log_message(self, format: str, *args) -> None:
        print("%s - %s" % (self.address_string(), format % args))


def main() -> None:
    prepare_static_links()
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), PersonFactoryHandler)
    print(f"Person Factory webapp serving http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
