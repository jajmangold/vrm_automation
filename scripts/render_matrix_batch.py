from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_person_now import build_single_person_manifest
from scripts.create_talking_person import ROOT, workspace_path
from scripts.create_talking_person_from_text import repo_arg
from scripts.make_person_manifest import load_accessories
from scripts.render_profiles import render_defaults


def load_requests(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("requests", [])
    if not isinstance(data, list) or not data:
        raise ValueError("requests JSON must contain a non-empty request list")
    return [dict(item) for item in data]


def render_dedupe_key(request: dict[str, Any]) -> str:
    ignored = {"id", "name", "display_name", "notes", "text", "audio_cache_key"}
    comparable = {key: value for key, value in request.items() if key not in ignored}
    render_profile = str(request.get("render_profile", "auto"))
    try:
        comparable["render_profile_defaults"] = render_defaults(
            render_profile,
            has_lipsync=bool(request.get("lipsync_timeline") or request.get("lipsync_timeline_json")),
        )
    except ValueError:
        pass
    return json.dumps(comparable, sort_keys=True, separators=(",", ":"))


def render_cache_key(request: dict[str, Any]) -> str:
    return hashlib.sha256(render_dedupe_key(request).encode("utf-8")).hexdigest()[:24]


def cache_paths_for_request(request: dict[str, Any], *, root: Path = ROOT) -> dict[str, Path]:
    key = render_cache_key(request)
    return {
        "key": key,
        "glb": root / "outputs/render_cache" / f"{key}.glb",
        "report": root / "results/render_cache" / f"{key}_animation.json",
        "job": root / "results/render_cache" / f"{key}_job.json",
    }


def dedupe_requests(requests: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    unique = []
    first_by_key = {}
    aliases = {}
    for request in requests:
        request_id = str(request["id"])
        key = render_dedupe_key(request)
        source_id = first_by_key.get(key)
        if source_id:
            aliases[request_id] = source_id
            continue
        first_by_key[key] = request_id
        unique.append(request)
    return unique, aliases


def replace_string_values(value: Any, source: str, target: str) -> Any:
    if isinstance(value, str):
        return value.replace(source, target)
    if isinstance(value, list):
        return [replace_string_values(item, source, target) for item in value]
    if isinstance(value, dict):
        return {key: replace_string_values(item, source, target) for key, item in value.items()}
    return value


def root_path(path_text: str, root: Path = ROOT) -> Path:
    if path_text.startswith("/workspace/"):
        return root / path_text.removeprefix("/workspace/")
    return root / path_text if not Path(path_text).is_absolute() else Path(path_text)


def link_or_copy_file(source_path: Path, target_path: Path) -> str:
    if target_path.exists():
        target_path.unlink()
    try:
        os.link(source_path, target_path)
        return "linked"
    except OSError:
        shutil.copy2(source_path, target_path)
        return "copied"


def link_or_copy_tree(source_path: Path, target_path: Path) -> dict[str, Any]:
    if target_path.exists():
        shutil.rmtree(target_path)
    linked_count = 0
    copied_count = 0
    for path in source_path.rglob("*"):
        relative = path.relative_to(source_path)
        destination = target_path / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        status = link_or_copy_file(path, destination)
        if status == "linked":
            linked_count += 1
        else:
            copied_count += 1
    if copied_count == 0:
        status = "linked-dir"
    elif linked_count:
        status = "partially-linked-dir"
    else:
        status = "copied-dir"
    return {"status": status, "linked_files": linked_count, "copied_files": copied_count}


def copy_output_path(source_text: str, target_text: str, *, root: Path = ROOT) -> dict[str, Any]:
    source_path = root_path(source_text, root)
    target_path = root_path(target_text, root)
    if not source_path.exists():
        return {"status": "missing-source", "source": str(source_path), "target": str(target_path)}
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        result = link_or_copy_tree(source_path, target_path)
        return {**result, "source": str(source_path), "target": str(target_path)}
    else:
        status = link_or_copy_file(source_path, target_path)
        return {"status": status, "source": str(source_path), "target": str(target_path)}


def materialize_duplicate_outputs(source_job: dict[str, Any], duplicate_job: dict[str, Any], *, root: Path = ROOT) -> None:
    source_env = source_job.get("environment", {})
    duplicate_env = duplicate_job.get("environment", {})
    for key in ("OUTPUT_GLB", "OUTPUT_BLEND", "OUTPUT_VRM", "RENDER_DIR"):
        source_value = source_env.get(key)
        duplicate_value = duplicate_env.get(key)
        if source_value and duplicate_value:
            copy_output_path(str(source_value), str(duplicate_value), root=root)
    source_report = source_env.get("ANIMATION_REPORT_JSON")
    duplicate_report = duplicate_env.get("ANIMATION_REPORT_JSON")
    if source_report and duplicate_report:
        source_path = root_path(str(source_report), root)
        target_path = root_path(str(duplicate_report), root)
        if source_path.exists():
            report = json.loads(source_path.read_text(encoding="utf-8"))
            report = replace_string_values(report, str(source_job["id"]), str(duplicate_job["id"]))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def store_render_cache(request: dict[str, Any], job: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    paths = cache_paths_for_request(request, root=root)
    env = job.get("environment", {})
    source_glb = env.get("OUTPUT_GLB")
    source_report = env.get("ANIMATION_REPORT_JSON")
    if not source_glb or not source_report:
        return {"status": "skipped", "reason": "missing-output-paths", "key": paths["key"]}
    source_glb_path = root_path(str(source_glb), root)
    source_report_path = root_path(str(source_report), root)
    if not source_glb_path.exists() or not source_report_path.exists():
        return {"status": "skipped", "reason": "missing-output-files", "key": paths["key"]}
    paths["glb"].parent.mkdir(parents=True, exist_ok=True)
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    paths["job"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_glb_path, paths["glb"])
    shutil.copy2(source_report_path, paths["report"])
    job["render_cache"] = {"status": "stored", "key": paths["key"]}
    cache_job = copy.deepcopy(job)
    cache_job["render_cache"] = {"status": "source", "key": paths["key"]}
    paths["job"].write_text(json.dumps(cache_job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "stored", "key": paths["key"], "job_id": job.get("id")}


def materialize_cached_request(request: dict[str, Any], paths: dict[str, Path], *, root: Path = ROOT) -> dict[str, Any] | None:
    if not paths["glb"].exists() or not paths["report"].exists() or not paths["job"].exists():
        return None
    cached_job = json.loads(paths["job"].read_text(encoding="utf-8"))
    cached_id = str(cached_job["id"])
    request_id = str(request["id"])
    job = replace_string_values(cached_job, cached_id, request_id)
    job["id"] = request_id
    metadata = dict(job.get("metadata", {}))
    if request.get("name"):
        metadata["display_name"] = str(request["name"])
    job["metadata"] = metadata
    env = job.get("environment", {})
    source_env = cached_job.get("environment", {})
    source_env = source_env if isinstance(source_env, dict) else {}
    target_glb = env.get("OUTPUT_GLB")
    target_render_dir = env.get("RENDER_DIR")
    target_report = env.get("ANIMATION_REPORT_JSON")
    if target_glb:
        copy_output_path(str(paths["glb"]), str(target_glb), root=root)
    if source_env.get("RENDER_DIR") and target_render_dir:
        copy_output_path(str(source_env["RENDER_DIR"]), str(target_render_dir), root=root)
    if target_report:
        report = json.loads(paths["report"].read_text(encoding="utf-8"))
        report = replace_string_values(report, cached_id, request_id)
        target_report_path = root_path(str(target_report), root)
        target_report_path.parent.mkdir(parents=True, exist_ok=True)
        target_report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    job["render_cache"] = {"status": "hit", "key": paths["key"], "source_job_id": cached_id}
    return job


def duplicate_job_from_source(
    source_job: dict[str, Any],
    request: dict[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    duplicate_id = str(request["id"])
    source_id = str(source_job["id"])
    job = replace_string_values(copy.deepcopy(source_job), source_id, duplicate_id)
    job["id"] = duplicate_id
    metadata = dict(job.get("metadata", {}))
    if request.get("name"):
        metadata["display_name"] = str(request["name"])
    job["metadata"] = metadata
    job["render_dedup"] = {
        "status": "materialized-copy",
        "source_job_id": source_id,
    }
    materialize_duplicate_outputs(source_job, job, root=root)
    return job


def expand_deduped_batch_result(
    result_path: Path,
    requests: list[dict[str, Any]],
    aliases: dict[str, str],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    batch = json.loads(result_path.read_text(encoding="utf-8"))
    jobs_by_id = {str(job.get("id")): job for job in batch.get("jobs", [])}
    expanded_jobs = []
    materialized_count = 0
    for request in requests:
        request_id = str(request["id"])
        source_id = aliases.get(request_id)
        if not source_id:
            expanded_jobs.append(jobs_by_id[request_id])
            continue
        expanded_jobs.append(duplicate_job_from_source(jobs_by_id[source_id], request, root=root))
        materialized_count += 1
    batch["jobs"] = expanded_jobs
    batch["render_dedupe"] = {
        "status": "enabled",
        "requested_job_count": len(requests),
        "source_job_count": len(jobs_by_id),
        "materialized_duplicate_count": materialized_count,
        "aliases": aliases,
    }
    result_path.write_text(json.dumps(batch, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return batch


def combined_manifest_from_requests(
    requests: list[dict[str, Any]],
    *,
    accessories: list[dict[str, Any]],
    root: Path = ROOT,
) -> dict[str, Any]:
    jobs = []
    defaults: dict[str, Any] = {}
    for index, request in enumerate(requests):
        lipsync_timeline = request.get("lipsync_timeline_json") or request.get("lipsync_timeline") or ""
        manifest = build_single_person_manifest(
            person_id=str(request["id"]),
            display_name=str(request.get("name") or request["id"]),
            base_key=str(request.get("base", "female")),
            accessory_query=str(request.get("accessory", "necklace")),
            animation_preset=str(request.get("animation", "talk_idle")),
            lipsync_timeline_json=workspace_path(lipsync_timeline, root=root) if lipsync_timeline else "",
            render_profile=str(request.get("render_profile", "auto")),
            accessories=accessories,
        )
        if index == 0:
            defaults.update(manifest.get("defaults", {}))
        jobs.extend(manifest.get("jobs", []))
    defaults["cache_base_scenes"] = "1"
    return {"defaults": defaults, "jobs": jobs}


def run_checked(command: list[str]) -> dict[str, Any]:
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


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_optimization_profile(selected: str, requests: list[dict[str, Any]]) -> str:
    if selected != "auto":
        return selected
    profiles = {str(request.get("render_profile", "auto")) for request in requests}
    if profiles and profiles <= {"rough_lipsync", "thumbnail_lipsync", "control_lipsync"}:
        return "rough_preview"
    return "standard"


def build_finalize_command(
    result_path: Path,
    gallery_path: Path,
    summary_path: Path,
    *,
    texture_size: int,
    optimization_profile: str,
    export_godot: bool,
    godot_url: str = "http://127.0.0.1:8790",
    build_review_assets: bool = True,
) -> list[str]:
    command = [
        "python3",
        "scripts/finalize_batch.py",
        repo_arg(result_path),
        repo_arg(gallery_path),
        "--summary-json",
        repo_arg(summary_path),
        "--texture-size",
        str(texture_size),
        "--optimization-profile",
        optimization_profile,
    ]
    if not build_review_assets:
        command.extend(["--skip-gallery", "--skip-contact-sheet"])
    if export_godot:
        command.extend(["--export-godot", "--godot-url", godot_url])
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a warmed matrix batch through one Blender manifest run.")
    parser.add_argument("--requests-json", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--gallery", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--asset-config", default="config/poly_pizza_assets.json")
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--optimization-profile", choices=["auto", "standard", "rough_preview"], default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-godot-export", action="store_true")
    parser.add_argument(
        "--skip-finalize-review-assets",
        action="store_true",
        help="Skip finalize gallery/contact outputs when another stage will build review assets.",
    )
    parser.add_argument("--godot-url", default="http://127.0.0.1:8790")
    parser.add_argument("--report-json", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requests_path = ROOT / args.requests_json
    manifest_path = ROOT / args.manifest
    result_path = ROOT / args.result
    gallery_path = ROOT / args.gallery
    summary_path = ROOT / args.summary_json
    report_path = ROOT / (args.report_json or f"results/render_matrix_batch_{args.batch_id}.json")

    requests = load_requests(requests_path)
    unique_requests, render_aliases = dedupe_requests(requests)
    cached_jobs: dict[str, dict[str, Any]] = {}
    render_requests = []
    for request in unique_requests:
        cached_job = materialize_cached_request(request, cache_paths_for_request(request))
        if cached_job:
            cached_jobs[str(request["id"])] = cached_job
        else:
            render_requests.append(request)
    optimization_profile = resolve_optimization_profile(args.optimization_profile, requests)
    accessories = load_accessories(ROOT / args.asset_config)
    manifest = (
        combined_manifest_from_requests(render_requests, accessories=accessories)
        if render_requests
        else {"defaults": {"cache_base_scenes": "1"}, "jobs": []}
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = {
        "status": "dry-run" if args.dry_run else "running",
        "batch_id": args.batch_id,
        "request_count": len(requests),
        "unique_request_count": len(unique_requests),
        "render_request_count": len(render_requests),
        "render_dedupe": {
            "status": "enabled",
            "materialized_duplicate_count": len(render_aliases),
            "source_request_count": len(unique_requests),
            "aliases": render_aliases,
        },
        "render_cache": {
            "status": "enabled",
            "hit_count": len(cached_jobs),
            "miss_count": len(render_requests),
            "keys": {str(request["id"]): cache_paths_for_request(request)["key"] for request in unique_requests},
        },
        "manifest": repo_arg(manifest_path),
        "result": repo_arg(result_path),
        "gallery": repo_arg(gallery_path),
        "summary_json": repo_arg(summary_path),
        "optimization_profile": optimization_profile,
        "job_ids": [request["id"] for request in requests],
        "stages": [],
    }
    write_report(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.dry_run:
        return

    started = time.monotonic()
    if render_requests:
        blender_stage = run_checked(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "blender-vrm",
                "blender",
                "--background",
                "--python",
                "scripts/install_addons.py",
                "--python",
                "scripts/run_manifest_in_blender.py",
                "--",
                repo_arg(manifest_path),
                repo_arg(result_path),
            ]
        )
    else:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps({"status": "ok", "manifest": repo_arg(manifest_path), "jobs": []}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        blender_stage = {
            "command": [],
            "elapsed_seconds": 0.0,
            "returncode": 0,
            "status": "ok",
            "cache_status": "all-hit",
        }
    report["stages"].append({"name": "blender_manifest", **blender_stage})
    batch = json.loads(result_path.read_text(encoding="utf-8"))
    rendered_jobs_by_id = {str(job.get("id")): job for job in batch.get("jobs", [])}
    cache_stores = []
    for request in render_requests:
        rendered_job = rendered_jobs_by_id.get(str(request["id"]))
        if rendered_job:
            cache_stores.append(store_render_cache(request, rendered_job))
    if cached_jobs:
        jobs_by_id = {**rendered_jobs_by_id, **cached_jobs}
        batch["jobs"] = [jobs_by_id[str(request["id"])] for request in unique_requests]
        batch["render_cache"] = {
            "status": "enabled",
            "hit_count": len(cached_jobs),
            "miss_count": len(render_requests),
            "stored_count": sum(1 for item in cache_stores if item.get("status") == "stored"),
            "stores": cache_stores,
        }
        result_path.write_text(json.dumps(batch, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        batch["render_cache"] = {
            "status": "enabled",
            "hit_count": 0,
            "miss_count": len(render_requests),
            "stored_count": sum(1 for item in cache_stores if item.get("status") == "stored"),
            "stores": cache_stores,
        }
        result_path.write_text(json.dumps(batch, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["render_cache"].update(batch["render_cache"])
    if render_aliases:
        expand_deduped_batch_result(result_path, requests, render_aliases)
        report["render_dedupe"]["status"] = "materialized"
    write_report(report_path, report)
    finalize = build_finalize_command(
        result_path,
        gallery_path,
        summary_path,
        texture_size=args.texture_size,
        optimization_profile=optimization_profile,
        export_godot=not args.skip_godot_export,
        godot_url=args.godot_url,
        build_review_assets=not args.skip_finalize_review_assets,
    )
    finalize_stage = run_checked(finalize)
    report["stages"].append({"name": "finalize", **finalize_stage})
    report["status"] = "ok"
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if summary_path.exists():
        report["finalize_summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
    write_report(report_path, report)


if __name__ == "__main__":
    main()
