#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

EXPECTED_VISEMES = ("aa", "ee", "ih", "oh", "ou")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lipsync_quality import analyze_lipsync_timeline_path, summarize_lipsync_validation, workspace_path


class GodotHttpClient:
    def __init__(self, base_url: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_control_urls(value: str) -> list[str]:
    urls = [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
    return list(dict.fromkeys(urls))


def control_clients(client_or_clients) -> list[Any]:
    if isinstance(client_or_clients, (list, tuple)):
        return [client for client in client_or_clients if client is not None]
    return [client_or_clients]


def lip_ready_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = []
    for asset in assets:
        summary = asset.get("lipsync_summary", {})
        if not asset.get("id"):
            continue
        if not asset.get("glb"):
            continue
        if not asset.get("lipsync_timeline"):
            continue
        if int(summary.get("cue_count") or 0) <= 0:
            continue
        ready.append(asset)
    return ready


def batch_job_asset(job: dict[str, Any]) -> dict[str, Any]:
    env = job.get("environment", {})
    env = env if isinstance(env, dict) else {}
    timeline = (
        job.get("lipsync_timeline_override")
        or job.get("lipsync_timeline_json")
        or env.get("LIPSYNC_TIMELINE_JSON")
        or env.get("LIPSYNC_TIMELINE")
        or ""
    )
    glb = (
        job.get("optimized_glb")
        or job.get("output_glb")
        or env.get("OUTPUT_GLB")
        or ""
    )
    summary = job.get("lipsync_summary")
    summary = summary if isinstance(summary, dict) else {}
    if timeline and int(summary.get("cue_count") or 0) <= 0:
        quality = analyze_lipsync_timeline_path(str(timeline), root=ROOT)
        summary = {
            **quality,
            "quality": quality,
        }
    return {
        **job,
        "id": job.get("id", ""),
        "glb": glb,
        "lipsync_timeline": timeline,
        "lipsync_summary": summary,
    }


def batch_result_assets(batch_result_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(batch_result_path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", [])
    if not isinstance(jobs, list):
        return []
    return [batch_job_asset(job) for job in jobs if isinstance(job, dict)]


def missing_profile_visemes(profile: dict[str, Any], expected: tuple[str, ...] = EXPECTED_VISEMES) -> list[str]:
    visemes = profile.get("visemes", {})
    if not isinstance(visemes, dict):
        return list(expected)
    return [viseme for viseme in expected if viseme not in visemes]


def timeline_visemes(summary: dict[str, Any], quality: dict[str, Any]) -> list[str]:
    values = summary.get("visemes")
    if not values and isinstance(quality, dict):
        values = quality.get("visemes")
    if not isinstance(values, list):
        return []
    output = []
    for value in values:
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return output


def ordered_summary_strings(summary: dict[str, Any], key: str) -> list[str]:
    values = summary.get(key)
    if not isinstance(values, list):
        return []
    output = []
    for value in values:
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return output


def missing_timeline_visemes(profile: dict[str, Any], visemes: list[str]) -> list[str]:
    profile_visemes = profile.get("visemes", {})
    if not isinstance(profile_visemes, dict):
        return list(visemes)
    return [viseme for viseme in visemes if viseme != "rest" and viseme not in profile_visemes]


def start_playback_status(lipsync_result: dict[str, Any]) -> dict[str, Any]:
    playback = lipsync_result.get("playback", {})
    return playback if isinstance(playback, dict) else {}


def timeline_quality(timeline_path: str, summary: dict[str, Any]) -> dict[str, Any]:
    quality = summary.get("quality") if isinstance(summary, dict) else {}
    if isinstance(quality, dict) and quality.get("status"):
        return quality
    resolved = workspace_path(timeline_path, root=ROOT)
    if resolved and resolved.exists():
        return analyze_lipsync_timeline_path(timeline_path, root=ROOT)
    return {
        "status": "unknown",
        "grade": "n/a",
        "score": 0,
        "source_mode": "unknown",
        "alignment": "unknown",
        "issues": [],
        "warnings": ["quality-unavailable"],
        "path": timeline_path,
    }


def validate_asset(client, asset: dict[str, Any], wait_seconds: float = 0.1) -> dict[str, Any]:
    asset_id = str(asset.get("id", ""))
    timeline_path = str(asset.get("lipsync_timeline", ""))
    summary = asset.get("lipsync_summary", {}) if isinstance(asset.get("lipsync_summary", {}), dict) else {}
    expected_cues = int(summary.get("cue_count") or 0)
    quality = timeline_quality(timeline_path, summary)
    issues: list[str] = []

    load_result = client.post("/load", {"id": asset_id})
    if load_result.get("status") != "ok":
        issues.append("load-failed")

    profile = client.get("/face-profile")
    if profile.get("status") != "ok":
        issues.append("face-profile-failed")
    missing_visemes = missing_profile_visemes(profile)
    if missing_visemes:
        issues.append("missing-visemes")
    used_visemes = timeline_visemes(summary, quality)
    missing_used_visemes = missing_timeline_visemes(profile, used_visemes)
    if missing_used_visemes:
        issues.append("missing-timeline-visemes")

    lipsync_result = client.post("/lipsync", {"path": timeline_path})
    if lipsync_result.get("status") != "ok":
        issues.append("lipsync-start-failed")
    if int(lipsync_result.get("cue_count") or 0) != expected_cues:
        issues.append("cue-count-mismatch")

    if wait_seconds > 0:
        time.sleep(wait_seconds)
    playback_status = client.get("/lipsync-status")
    start_status = start_playback_status(lipsync_result)
    if playback_status.get("source") and playback_status.get("source") != timeline_path:
        issues.append("playback-source-mismatch")
    playback_cue_count = int(playback_status.get("cue_count") or 0)
    start_cue_count = int(start_status.get("cue_count") or 0)
    if playback_cue_count != expected_cues and start_cue_count != expected_cues:
        issues.append("playback-cue-count-mismatch")
    if playback_status.get("status") not in {"playing", "idle"} and start_status.get("status") not in {"playing", "idle"}:
        issues.append("playback-status-invalid")
    if quality.get("status") == "review":
        issues.append("lipsync-quality-review")

    return {
        "id": asset_id,
        "status": "ok" if not issues else "review",
        "issues": sorted(set(issues)),
        "timeline": timeline_path,
        "cue_count": expected_cues,
        "timeline_visemes": used_visemes,
        "timeline_source_phonemes": quality.get("source_unique_phonemes")
        or ordered_summary_strings(summary, "source_unique_phonemes"),
        "source_event_count": int(quality.get("source_event_count") or summary.get("source_event_count") or 0),
        "source_phoneme_count": int(quality.get("source_phoneme_count") or summary.get("source_phoneme_count") or 0),
        "load": load_result,
        "missing_visemes": missing_visemes,
        "missing_timeline_visemes": missing_used_visemes,
        "lipsync_quality": quality,
        "lipsync": lipsync_result,
        "playback_status": playback_status,
    }


def batch_validation_payload(asset: dict[str, Any], wait_seconds: float = 0.1) -> dict[str, Any]:
    summary = asset.get("lipsync_summary", {}) if isinstance(asset.get("lipsync_summary", {}), dict) else {}
    quality = timeline_quality(str(asset.get("lipsync_timeline", "")), summary)
    return {
        "id": str(asset.get("id", "")),
        "glb": str(asset.get("glb", "")),
        "timeline": str(asset.get("lipsync_timeline", "")),
        "expected_cues": int(summary.get("cue_count") or 0),
        "timeline_visemes": timeline_visemes(summary, quality),
        "wait_seconds": wait_seconds,
    }


def normalized_batch_validation_result(asset: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    summary = asset.get("lipsync_summary", {}) if isinstance(asset.get("lipsync_summary", {}), dict) else {}
    timeline_path = str(asset.get("lipsync_timeline", ""))
    expected_cues = int(summary.get("cue_count") or 0)
    quality = timeline_quality(timeline_path, summary)
    used_visemes = timeline_visemes(summary, quality)
    issues = [str(issue) for issue in result.get("issues", []) if str(issue)]
    if quality.get("status") == "review":
        issues.append("lipsync-quality-review")
    return {
        **result,
        "id": str(result.get("id") or asset.get("id", "")),
        "status": "ok" if not issues else "review",
        "issues": sorted(set(issues)),
        "timeline": str(result.get("timeline") or timeline_path),
        "cue_count": int(result.get("cue_count") or expected_cues),
        "timeline_visemes": used_visemes,
        "timeline_source_phonemes": quality.get("source_unique_phonemes")
        or ordered_summary_strings(summary, "source_unique_phonemes"),
        "source_event_count": int(quality.get("source_event_count") or summary.get("source_event_count") or 0),
        "source_phoneme_count": int(quality.get("source_phoneme_count") or summary.get("source_phoneme_count") or 0),
        "missing_visemes": result.get("missing_visemes", []),
        "missing_timeline_visemes": result.get("missing_timeline_visemes", []),
        "lipsync_quality": quality,
        "load": result.get("load", {}),
        "lipsync": result.get("lipsync", {}),
        "playback_status": result.get("playback_status", {}),
    }


def validate_asset_batch_endpoint(
    client,
    assets: list[dict[str, Any]],
    wait_seconds: float = 0.1,
) -> list[dict[str, Any]]:
    response = client.post(
        "/validate-lipsync-batch",
        {
            "assets": [batch_validation_payload(asset, wait_seconds=wait_seconds) for asset in assets],
            "wait_seconds": wait_seconds,
        },
    )
    if response.get("status") != "ok":
        raise RuntimeError(f"batch validation failed: {response}")
    raw_checked = response.get("checked", [])
    if not isinstance(raw_checked, list) or len(raw_checked) != len(assets):
        raise RuntimeError(f"batch validation returned {len(raw_checked) if isinstance(raw_checked, list) else 'invalid'} results")
    return [
        normalized_batch_validation_result(asset, result if isinstance(result, dict) else {})
        for asset, result in zip(assets, raw_checked)
    ]


def validation_dedupe_key(asset: dict[str, Any]) -> str:
    render_cache = asset.get("render_cache")
    render_cache = render_cache if isinstance(render_cache, dict) else {}
    render_dedup = asset.get("render_dedup")
    render_dedup = render_dedup if isinstance(render_dedup, dict) else {}
    summary = asset.get("lipsync_summary")
    summary = summary if isinstance(summary, dict) else {}
    cache_key = str(render_cache.get("key") or "").strip()
    source_job_id = str(render_dedup.get("source_job_id") or "").strip()
    render_key = cache_key or source_job_id
    if not render_key:
        return ""
    key_payload = {
        "render": render_key,
        "timeline": str(asset.get("lipsync_timeline") or ""),
        "cue_count": int(summary.get("cue_count") or 0),
        "visemes": timeline_visemes(summary, summary),
        "source_event_count": int(summary.get("source_event_count") or 0),
        "source_phoneme_count": int(summary.get("source_phoneme_count") or 0),
    }
    return json.dumps(key_payload, sort_keys=True, separators=(",", ":"))


def validation_cache_path(key: str, cache_dir: Path) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"{digest}.json"


def read_validation_cache(key: str, cache_dir: Path) -> dict[str, Any] | None:
    path = validation_cache_path(key, cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if payload.get("key") != key or not isinstance(payload.get("result"), dict):
        return None
    return payload["result"]


def write_validation_cache(key: str, result: dict[str, Any], cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "key": key,
        "stored_at": round(time.time(), 3),
        "result": result,
    }
    validation_cache_path(key, cache_dir).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def copy_validation_cache_result_for_asset(
    source_result: dict[str, Any],
    asset: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    copied = copy_validation_result_for_asset(source_result, asset, key)
    copied["validation_cache"] = {
        "status": "hit",
        "key": key,
    }
    copied["validation_dedup"]["status"] = "persistent-cache-hit"
    return copied


def copy_validation_result_for_asset(
    source_result: dict[str, Any],
    asset: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    copied = copy.deepcopy(source_result)
    source_asset_id = str(source_result.get("id", ""))
    target_asset_id = str(asset.get("id", ""))
    target_timeline = str(asset.get("lipsync_timeline") or copied.get("timeline") or "")
    summary = asset.get("lipsync_summary")
    summary = summary if isinstance(summary, dict) else {}
    copied["id"] = target_asset_id
    copied["timeline"] = target_timeline
    copied["cue_count"] = int(summary.get("cue_count") or copied.get("cue_count") or 0)
    copied["validation_dedup"] = {
        "status": "materialized-copy",
        "source_asset_id": source_asset_id,
        "key": key,
    }
    return copied


def validate_assets_deduped(
    client,
    assets: list[dict[str, Any]],
    wait_seconds: float = 0.1,
    dedupe: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return validate_assets(
        client,
        assets,
        wait_seconds=wait_seconds,
        dedupe=dedupe,
        use_batch_endpoint=False,
    )[:2]


def validate_assets(
    client,
    assets: list[dict[str, Any]],
    wait_seconds: float = 0.1,
    dedupe: bool = True,
    use_batch_endpoint: bool = True,
    validation_cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    clients = control_clients(client)
    if not clients:
        raise ValueError("at least one Godot control client is required")
    checked: list[dict[str, Any]] = []
    representatives: dict[str, dict[str, Any]] = {}
    representative_assets: list[dict[str, Any]] = []
    representative_keys: list[str] = []
    representative_positions: list[int] = []
    duplicate_positions: list[tuple[int, str, dict[str, Any]]] = []
    source_checked_count = 0
    duplicate_count = 0
    cache_hit_count = 0
    for asset in assets:
        key = validation_dedupe_key(asset) if dedupe else ""
        if key and key in representatives:
            duplicate_positions.append((len(checked), key, asset))
            checked.append({"__pending_duplicate__": True})
            duplicate_count += 1
            continue
        cached_result = read_validation_cache(key, validation_cache_dir) if key and validation_cache_dir else None
        if cached_result:
            result = copy_validation_cache_result_for_asset(cached_result, asset, key)
            representatives[key] = result
            checked.append(result)
            cache_hit_count += 1
            continue
        result = {"__pending__": True}
        if key:
            representatives[key] = result
        representative_assets.append(asset)
        representative_keys.append(key)
        representative_positions.append(len(checked))
        checked.append(result)
        source_checked_count += 1
    transport = {
        "mode": "per-asset",
        "batch_request_count": 0,
        "fallback": False,
        "control_client_count": len(clients),
    }
    representative_results: list[dict[str, Any]]
    if use_batch_endpoint and representative_assets:
        representative_results = [{} for _ in representative_assets]
        fallback_reasons = []
        for client_index, shard_client in enumerate(clients):
            shard = [
                (position, asset)
                for position, asset in enumerate(representative_assets)
                if position % len(clients) == client_index
            ]
            if not shard:
                continue
            shard_positions = [position for position, _asset in shard]
            shard_assets = [asset for _position, asset in shard]
            try:
                shard_results = validate_asset_batch_endpoint(
                    shard_client,
                    shard_assets,
                    wait_seconds=wait_seconds,
                )
                transport["batch_request_count"] += 1
            except Exception as exc:
                shard_results = [
                    validate_asset(shard_client, asset, wait_seconds=wait_seconds)
                    for asset in shard_assets
                ]
                transport["fallback"] = True
                fallback_reasons.append(str(exc))
            for position, result in zip(shard_positions, shard_results):
                representative_results[position] = result
        transport["mode"] = "batch-endpoint-pool" if len(clients) > 1 else "batch-endpoint"
        if fallback_reasons:
            transport["fallback_reason"] = "; ".join(fallback_reasons)
    else:
        representative_results = [
            validate_asset(clients[position % len(clients)], asset, wait_seconds=wait_seconds)
            for position, asset in enumerate(representative_assets)
        ]
    for position, key, result in zip(representative_positions, representative_keys, representative_results):
        if key:
            result["validation_dedup"] = {
                "status": "source",
                "key": key,
            }
            if validation_cache_dir:
                write_validation_cache(key, result, validation_cache_dir)
                result["validation_cache"] = {
                    "status": "stored",
                    "key": key,
                }
            representatives[key] = result
        checked[position] = result
    for position, key, asset in duplicate_positions:
        checked[position] = copy_validation_result_for_asset(representatives[key], asset, key)
    cache_miss_count = len(representative_assets)
    if cache_hit_count and not cache_miss_count:
        transport["mode"] = "persistent-cache"
    return checked, {
        "enabled": dedupe,
        "source_checked_count": source_checked_count,
        "materialized_duplicate_count": duplicate_count,
        "group_count": len(representatives),
    }, transport, {
        "enabled": bool(validation_cache_dir),
        "hit_count": cache_hit_count,
        "miss_count": cache_miss_count,
        "stored_count": cache_miss_count if validation_cache_dir else 0,
        "source_checked_count": cache_miss_count,
    }


def run_validation(
    client,
    max_assets: int = 5,
    wait_seconds: float = 0.1,
    id_prefix: str = "",
    batch_result: Path | None = None,
    dedupe: bool = True,
    use_batch_endpoint: bool = True,
    validation_cache_dir: Path | None = None,
) -> dict[str, Any]:
    clients = control_clients(client)
    if not clients:
        raise ValueError("at least one Godot control client is required")
    if batch_result:
        assets = batch_result_assets(batch_result)
    else:
        assets_payload = clients[0].get("/assets")
        assets = assets_payload.get("assets", [])
    candidates = lip_ready_assets(assets)
    if id_prefix:
        candidates = [
            asset
            for asset in candidates
            if str(asset.get("id", "")).startswith(id_prefix)
        ]
    checked, validation_dedupe, validation_transport, validation_cache = validate_assets(
        clients,
        candidates[:max_assets],
        wait_seconds=wait_seconds,
        dedupe=dedupe,
        use_batch_endpoint=use_batch_endpoint,
        validation_cache_dir=validation_cache_dir,
    )
    issues: list[str] = []
    if not candidates:
        issues.append("no-lip-ready-assets")
    if any(item["status"] != "ok" for item in checked):
        issues.append("asset-review")
    quality_review_count = sum(
        1
        for item in checked
        if item.get("lipsync_quality", {}).get("status") == "review"
    )
    report = {
        "status": "ok" if checked and not issues else "review",
        "candidate_count": len(candidates),
        "checked_count": len(checked),
        "quality_review_count": quality_review_count,
        "validation_dedupe": validation_dedupe,
        "validation_transport": validation_transport,
        "validation_cache": validation_cache,
        "issues": sorted(set(issues)),
        "checked": checked,
    }
    report["summary"] = summarize_lipsync_validation(report)
    for key in (
        "ok_count",
        "review_count",
        "status_counts",
        "grade_counts",
        "source_counts",
        "warning_counts",
        "issue_counts",
        "active_visemes",
        "missing_active_viseme_counts",
        "cue_count_min",
        "cue_count_max",
        "duration_min",
        "duration_max",
        "expression_count_min",
        "expression_count_max",
    ):
        report[key] = report["summary"].get(key)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Godot lip-sync playback against lip-ready assets.")
    parser.add_argument("--control-url", default="http://127.0.0.1:8790")
    parser.add_argument("--control-urls", default="", help="Comma-separated Godot control URLs for sharded validation.")
    parser.add_argument("--max-assets", type=int, default=5)
    parser.add_argument("--wait-seconds", type=float, default=0.1)
    parser.add_argument("--id-prefix", default="", help="Only validate lip-ready assets whose IDs start with this prefix.")
    parser.add_argument("--batch-result", help="Validate lip-ready assets from a local batch result instead of Godot /assets.")
    parser.add_argument("--disable-dedupe", action="store_true", help="Validate every matching asset even when cached renders are duplicate copies.")
    parser.add_argument("--disable-batch-endpoint", action="store_true", help="Use legacy per-asset Godot control calls.")
    parser.add_argument("--disable-validation-cache", action="store_true", help="Do not reuse persistent validation results.")
    parser.add_argument("--validation-cache-dir", default="results/godot_lipsync_validation_cache")
    parser.add_argument("--output", default="results/godot_lipsync_validation_latest.json")
    args = parser.parse_args()

    control_urls = parse_control_urls(args.control_urls) or parse_control_urls(args.control_url)
    report = run_validation(
        [GodotHttpClient(url) for url in control_urls],
        max_assets=args.max_assets,
        wait_seconds=args.wait_seconds,
        id_prefix=args.id_prefix,
        batch_result=Path(args.batch_result) if args.batch_result else None,
        dedupe=not args.disable_dedupe,
        use_batch_endpoint=not args.disable_batch_endpoint,
        validation_cache_dir=None if args.disable_validation_cache else Path(args.validation_cache_dir),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
