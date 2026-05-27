from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import threading
import time
from pathlib import Path


JOB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
TEXT_LIMIT = 500
DEFAULT_MAX_BATCH_JOBS = 24
DEFAULT_MAX_CHUNKED_MATRIX_JOBS = 768
DEFAULTS = {
    "base": "female",
    "accessory": "necklace",
    "animation": "talk_idle",
    "render_profile": "fast_lipsync",
    "normalizer": "local",
    "tts_service": "voice_design",
    "voice": "warm clear presenter voice",
    "seed": -1,
    "language": "English",
    "intensity": 0.9,
    "render": False,
    "dry_run": True,
    "reuse_audio": False,
    "reuse_lipsync": False,
    "skip_godot_export": True,
}


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:64]


def generated_job_id(prefix: str = "web") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[\n,]+", value)
    else:
        parts = list(value)
    return [str(part).strip() for part in parts if str(part).strip()]


def max_batch_jobs() -> int:
    try:
        value = int(os.environ.get("PERSON_FACTORY_MAX_BATCH_JOBS", DEFAULT_MAX_BATCH_JOBS))
    except ValueError:
        return DEFAULT_MAX_BATCH_JOBS
    return max(1, value)


def max_chunked_matrix_jobs() -> int:
    try:
        value = int(os.environ.get("PERSON_FACTORY_MAX_CHUNKED_MATRIX_JOBS", DEFAULT_MAX_CHUNKED_MATRIX_JOBS))
    except ValueError:
        return max(DEFAULT_MAX_CHUNKED_MATRIX_JOBS, max_batch_jobs())
    return max(max_batch_jobs(), value)


def matrix_chunked(payload: dict) -> bool:
    return normalize_bool(payload.get("chunked", False))


def matrix_request_limit(payload: dict) -> int:
    return max_chunked_matrix_jobs() if matrix_chunked(payload) else max_batch_jobs()


def matrix_request_chunks(requests: list[dict], chunk_size: int | None = None) -> list[list[dict]]:
    size = max(1, chunk_size or max_batch_jobs())
    return [requests[index : index + size] for index in range(0, len(requests), size)]


def line_cache_key(request: dict) -> str:
    payload = {
        "text": str(request.get("text", "")).strip(),
        "tts_service": str(request.get("tts_service", DEFAULTS["tts_service"])),
        "voice": str(request.get("voice", DEFAULTS["voice"])),
        "seed": int(request.get("seed", DEFAULTS["seed"])),
        "language": str(request.get("language", "English")),
        "intensity": str(request.get("intensity", "0.9")),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def cached_line_paths(cache_key: str) -> dict[str, str]:
    return {
        "audio_wav": f"outputs/speech/cache/{cache_key}.wav",
        "audio_manifest": f"results/musetalk/cache/{cache_key}_audio.json",
        "normalized_audio": f"outputs/speech/cache/{cache_key}_clean.wav",
        "rhubarb_json": f"results/rhubarb/cache/{cache_key}_clean.json",
        "lipsync_timeline": f"outputs/lipsync/cache/{cache_key}.face.json",
    }


def infer_audio_cache_key(request: dict) -> str:
    if request.get("audio_cache_key"):
        return str(request["audio_cache_key"])
    for key in ("audio_wav", "lipsync_timeline"):
        value = str(request.get(key, ""))
        if "/cache/" not in value:
            continue
        name = Path(value).name
        if name.endswith(".face.json"):
            return name.removesuffix(".face.json")
        stem = Path(name).stem
        if stem.endswith("_clean"):
            stem = stem.removesuffix("_clean")
        if stem.endswith("_audio"):
            stem = stem.removesuffix("_audio")
        if stem:
            return stem
    return ""


def path_exists(root: Path, relative_path: str) -> bool:
    path = Path(relative_path)
    if path.is_absolute():
        return path.exists()
    return (root / path).exists()


def cache_status(root: Path, paths: dict[str, str]) -> dict:
    audio_exists = path_exists(root, paths["audio_wav"])
    normalized_exists = path_exists(root, paths["normalized_audio"])
    rhubarb_exists = path_exists(root, paths["rhubarb_json"])
    lipsync_exists = path_exists(root, paths["lipsync_timeline"])
    return {
        "audio_exists": audio_exists,
        "normalized_audio_exists": normalized_exists,
        "rhubarb_exists": rhubarb_exists,
        "lipsync_exists": lipsync_exists,
        "audio_cache": "hit" if audio_exists else "miss",
        "lipsync_cache": "hit" if lipsync_exists else "miss",
        "alignment_cache": "hit" if normalized_exists and rhubarb_exists and lipsync_exists else "miss",
    }


def matrix_cache_preflight_plan(payload: dict, root: Path | None = None) -> dict:
    root = root or Path(".")
    requests = normalize_matrix_job_requests(payload)
    chunk_size = max_batch_jobs()
    chunk_count = len(matrix_request_chunks(requests, chunk_size)) if requests else 0
    cache_enabled = normalize_bool(payload.get("cache_line_audio", False))
    groups: dict[str, dict] = {}
    for request in requests:
        key = request.get("audio_cache_key") or line_cache_key(request)
        paths = cached_line_paths(key)
        group = groups.setdefault(
            key,
            {
                "audio_cache_key": key,
                "text": request["text"],
                "paths": paths,
                "job_ids": [],
                "bases": set(),
                "accessories": set(),
                "animations": set(),
            },
        )
        group["job_ids"].append(request["id"])
        group["bases"].add(request["base"])
        group["accessories"].add(request["accessory"])
        group["animations"].add(request["animation"])

    cache_groups = []
    estimated_tts_jobs = 0
    estimated_lipsync_jobs = 0
    for group in groups.values():
        status = cache_status(root, group["paths"])
        if not status["audio_exists"]:
            estimated_tts_jobs += 1
        if not status["lipsync_exists"]:
            estimated_lipsync_jobs += 1
        cache_groups.append(
            {
                "audio_cache_key": group["audio_cache_key"],
                "text": group["text"],
                "job_count": len(group["job_ids"]),
                "job_ids": group["job_ids"],
                "bases": sorted(group["bases"]),
                "accessories": sorted(group["accessories"]),
                "animations": sorted(group["animations"]),
                "paths": group["paths"],
                **status,
            }
        )
    cache_groups.sort(key=lambda item: item["audio_cache_key"])
    cache_reuse_jobs = max(0, len(requests) - len(cache_groups)) if cache_enabled else 0
    return {
        "status": "ok",
        "job_count": len(requests),
        "limit": matrix_request_limit(payload),
        "single_batch_limit": chunk_size,
        "chunked": matrix_chunked(payload),
        "chunk_size": chunk_size,
        "chunk_count": chunk_count,
        "cache_enabled": cache_enabled,
        "cache_group_count": len(cache_groups),
        "cache_reuse_jobs": cache_reuse_jobs,
        "estimated_tts_jobs": estimated_tts_jobs if cache_enabled else len(requests),
        "estimated_lipsync_jobs": estimated_lipsync_jobs if cache_enabled else len(requests),
        "cache_groups": cache_groups if cache_enabled else [],
        "jobs": [
            {
                "id": request["id"],
                "text": request["text"],
                "base": request["base"],
                "accessory": request["accessory"],
                "animation": request["animation"],
                "audio_cache_key": request.get("audio_cache_key", ""),
            }
            for request in requests
        ],
    }


def cache_warm_job_id(prefix: str, index: int, cache_key: str) -> str:
    base = slug(prefix) or "matrix"
    return slug(f"{base}-cache-warm-{index:03d}-{cache_key[:8]}")[:64]


def build_matrix_cache_warm_jobs(payload: dict, root: Path | None = None, dry_run: bool | None = None) -> dict:
    root = root or Path(".")
    plan = matrix_cache_preflight_plan({**payload, "cache_line_audio": True}, root=root)
    requests = normalize_matrix_job_requests({**payload, "cache_line_audio": True})
    first_by_key: dict[str, dict] = {}
    for request in requests:
        first_by_key.setdefault(request["audio_cache_key"], request)

    raw_prefix = str(payload.get("id_prefix") or generated_job_id("web-matrix"))
    warm_dry_run = normalize_bool(payload.get("dry_run", True)) if dry_run is None else bool(dry_run)
    warm_jobs = []
    skipped = []
    for index, group in enumerate(plan["cache_groups"], start=1):
        if group["audio_exists"] and group["lipsync_exists"]:
            skipped.append(group)
            continue
        source_request = dict(first_by_key[group["audio_cache_key"]])
        source_request.update(
            {
                "id": cache_warm_job_id(raw_prefix, index, group["audio_cache_key"]),
                "name": f"Cache Warm {index:03d} {group['audio_cache_key']}",
                "render": False,
                "dry_run": warm_dry_run,
                "skip_godot_export": True,
                "reuse_audio": True,
                "reuse_lipsync": True,
                **group["paths"],
                "audio_cache_key": group["audio_cache_key"],
            }
        )
        warm_jobs.append(
            {
                "id": source_request["id"],
                "audio_cache_key": group["audio_cache_key"],
                "request": source_request,
                "command": build_text_person_command(source_request),
                "cache_status": {
                    "audio_cache": group["audio_cache"],
                    "lipsync_cache": group["lipsync_cache"],
                    "alignment_cache": group["alignment_cache"],
                },
            }
        )
    return {
        "status": "ok",
        "dry_run": warm_dry_run,
        "plan": plan,
        "warm_job_count": len(warm_jobs),
        "skipped_group_count": len(skipped),
        "warm_jobs": warm_jobs,
        "skipped_groups": skipped,
    }


def matrix_batch_paths(batch_id: str) -> dict[str, str]:
    batch_slug = slug(batch_id) or "matrix"
    return {
        "requests_json": f"config/person_factory.{batch_slug}.requests.json",
        "manifest": f"config/person_factory.{batch_slug}.json",
        "result": f"results/batch_person_factory_{batch_slug.replace('-', '_')}_latest.json",
        "gallery": f"outputs/batch/person_factory_{batch_slug}.html",
        "summary_json": f"results/finalize_person_factory_{batch_slug.replace('-', '_')}_latest.json",
    }


def build_matrix_batch_render_job(
    payload: dict,
    render_requests: list[dict],
    dry_run: bool,
    texture_size: int = 1024,
) -> dict | None:
    if not render_requests:
        return None
    raw_prefix = str(payload.get("id_prefix") or generated_job_id("web-matrix"))
    batch_id = slug(raw_prefix) or "matrix"
    paths = matrix_batch_paths(batch_id)
    request = {
        "id": slug(f"{batch_id}-render-batch")[:64],
        "name": f"{batch_id.replace('-', ' ').title()} Render Batch",
        "text": f"Render {len(render_requests)} matrix items in one Blender batch.",
        "render": True,
        "dry_run": dry_run,
        "skip_godot_export": True,
    }
    command = [
        "python3",
        "scripts/render_matrix_batch.py",
        "--requests-json",
        paths["requests_json"],
        "--batch-id",
        batch_id,
        "--manifest",
        paths["manifest"],
        "--result",
        paths["result"],
        "--gallery",
        paths["gallery"],
        "--summary-json",
        paths["summary_json"],
        "--texture-size",
        str(texture_size),
        "--skip-godot-export",
    ]
    if dry_run:
        command.append("--dry-run")
    return {
        "id": request["id"],
        "request_count": len(render_requests),
        "request": request,
        "requests": render_requests,
        "requests_json": paths["requests_json"],
        "manifest": paths["manifest"],
        "result": paths["result"],
        "gallery": paths["gallery"],
        "summary_json": paths["summary_json"],
        "command": command,
    }


def build_matrix_batch_render_jobs(
    payload: dict,
    render_requests: list[dict],
    dry_run: bool,
    texture_size: int = 1024,
) -> list[dict]:
    if not render_requests:
        return []
    if not matrix_chunked(payload):
        job = build_matrix_batch_render_job(payload, render_requests, dry_run, texture_size=texture_size)
        return [job] if job else []

    raw_prefix = str(payload.get("id_prefix") or generated_job_id("web-matrix"))
    prefix = slug(raw_prefix) or "matrix"
    batch_jobs = []
    for index, chunk in enumerate(matrix_request_chunks(render_requests, max_batch_jobs()), start=1):
        chunk_payload = {**payload, "id_prefix": f"{prefix}-chunk-{index:03d}"}
        job = build_matrix_batch_render_job(chunk_payload, chunk, dry_run, texture_size=texture_size)
        if job:
            batch_jobs.append(job)
    return batch_jobs


def validation_id_prefix_for_requests(render_requests: list[dict]) -> str:
    if not render_requests:
        return ""
    first_id = str(render_requests[0].get("id", ""))
    stem, separator, suffix = first_id.rpartition("-")
    if separator and suffix.isdigit():
        return f"{stem}-"
    return first_id


def build_matrix_warm_render_pipeline(payload: dict, root: Path | None = None, dry_run: bool | None = None) -> dict:
    root = root or Path(".")
    pipeline_dry_run = normalize_bool(payload.get("dry_run", DEFAULTS["dry_run"])) if dry_run is None else bool(dry_run)
    batch_render = normalize_bool(payload.get("batch_render", True))
    pipeline_payload = {
        **payload,
        "cache_line_audio": True,
        "dry_run": pipeline_dry_run,
    }
    warm = build_matrix_cache_warm_jobs(pipeline_payload, root=root, dry_run=pipeline_dry_run)
    render_requests = normalize_matrix_job_requests(pipeline_payload)
    render_jobs = [
        {
            "id": request["id"],
            "audio_cache_key": request.get("audio_cache_key", ""),
            "request": request,
            "command": build_text_person_command(request),
        }
        for request in render_requests
    ]
    render_batch_jobs = build_matrix_batch_render_jobs(pipeline_payload, render_requests, pipeline_dry_run) if batch_render else []
    render_batch_job = render_batch_jobs[0] if len(render_batch_jobs) == 1 else None
    render_child_job_count = len(render_batch_jobs) if render_batch_jobs else len(render_jobs)
    return {
        "status": "ok",
        "dry_run": pipeline_dry_run,
        "stage_order": ["warm-cache", "render-batch" if render_batch_jobs else "render-matrix"],
        "plan": warm["plan"],
        "warm_job_count": warm["warm_job_count"],
        "skipped_group_count": warm["skipped_group_count"],
        "render_job_count": len(render_jobs),
        "render_child_job_count": render_child_job_count,
        "planned_child_job_count": warm["warm_job_count"] + render_child_job_count,
        "warm_jobs": warm["warm_jobs"],
        "skipped_groups": warm["skipped_groups"],
        "render_jobs": render_jobs,
        "render_batch_job": render_batch_job,
        "render_batch_jobs": render_batch_jobs,
        "validation_id_prefix": validation_id_prefix_for_requests(render_requests),
    }


def apply_line_cache(request: dict) -> dict:
    key = line_cache_key(request)
    request.update(cached_line_paths(key))
    request["audio_cache_key"] = key
    request["reuse_audio"] = True
    request["reuse_lipsync"] = True
    return request


def normalize_batch_items(lines_value) -> list[dict]:
    if isinstance(lines_value, str):
        return [{"text": line.strip()} for line in lines_value.splitlines() if line.strip()]
    return [dict(item) for item in list(lines_value or [])]


def normalize_job_request(payload: dict) -> dict:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise ValueError("text is required")
    if len(text) > TEXT_LIMIT:
        raise ValueError(f"text exceeds {TEXT_LIMIT} characters")

    raw_id = str(payload.get("id") or generated_job_id()).strip()
    job_id = raw_id if payload.get("id") else slug(raw_id)
    if not JOB_ID_PATTERN.match(job_id):
        raise ValueError("id must contain only lowercase letters, numbers, and hyphens")

    request = {**DEFAULTS, **payload}
    request["id"] = job_id
    request["text"] = text
    request["name"] = str(payload.get("name") or job_id.replace("-", " ").title()).strip()
    request["seed"] = int(payload.get("seed", DEFAULTS["seed"]))
    for key in ("render", "dry_run", "reuse_audio", "reuse_lipsync", "skip_godot_export"):
        request[key] = normalize_bool(payload.get(key, DEFAULTS[key]))
    return request


def normalize_batch_job_requests(payload: dict) -> list[dict]:
    items = normalize_batch_items(payload.get("lines", ""))
    if not items:
        raise ValueError("at least one batch line is required")
    limit = max_batch_jobs()
    if len(items) > limit:
        raise ValueError(f"batch expands to {len(items)} jobs; limit is {limit}")

    raw_prefix = str(payload.get("id_prefix") or generated_job_id("web-batch"))
    prefix = slug(raw_prefix)
    if not prefix:
        raise ValueError("id_prefix must contain letters or numbers")
    base_name = str(payload.get("name") or prefix.replace("-", " ").title()).strip()

    requests = []
    seen_ids = set()
    for index, item in enumerate(items, start=1):
        item_payload = dict(payload)
        item_payload.update(item)
        item_payload.pop("lines", None)
        item_payload.pop("id_prefix", None)
        item_payload["id"] = str(item_payload.get("id") or f"{prefix}-{index:03d}")
        item_payload["name"] = str(item_payload.get("name") or f"{base_name} {index:03d}")
        request = normalize_job_request(item_payload)
        if normalize_bool(payload.get("cache_line_audio", False)):
            request = apply_line_cache(request)
        if request["id"] in seen_ids:
            raise ValueError(f"duplicate job id in batch: {request['id']}")
        seen_ids.add(request["id"])
        requests.append(request)
    return requests


def normalize_matrix_job_requests(payload: dict) -> list[dict]:
    items = normalize_batch_items(payload.get("lines", ""))
    if not items:
        raise ValueError("at least one matrix line is required")

    bases = normalize_list(payload.get("bases")) or normalize_list(payload.get("base")) or [DEFAULTS["base"]]
    accessories = (
        normalize_list(payload.get("accessories")) or normalize_list(payload.get("accessory")) or [DEFAULTS["accessory"]]
    )
    animations = normalize_list(payload.get("animations")) or normalize_list(payload.get("animation")) or [
        DEFAULTS["animation"]
    ]
    total = len(items) * len(bases) * len(accessories) * len(animations)
    limit = matrix_request_limit(payload)
    if total > limit:
        raise ValueError(f"matrix expands to {total} jobs; limit is {limit}")

    raw_prefix = str(payload.get("id_prefix") or generated_job_id("web-matrix"))
    prefix = slug(raw_prefix)
    if not prefix:
        raise ValueError("id_prefix must contain letters or numbers")

    requests = []
    counter = 1
    for item in items:
        for base in bases:
            for accessory in accessories:
                for animation in animations:
                    item_payload = dict(payload)
                    item_payload.update(item)
                    for key in ("lines", "id_prefix", "bases", "accessories", "animations"):
                        item_payload.pop(key, None)
                    item_payload["id"] = f"{prefix}-{counter:03d}"
                    item_payload["base"] = base
                    item_payload["accessory"] = accessory
                    item_payload["animation"] = animation
                    label = f"{base} {accessory} {animation}".replace("_", " ").replace("-", " ")
                    item_payload["name"] = str(item_payload.get("name") or f"{prefix} {counter:03d} {label}").title()
                    request = normalize_job_request(item_payload)
                    if normalize_bool(payload.get("cache_line_audio", False)):
                        request = apply_line_cache(request)
                    requests.append(request)
                    counter += 1
    return requests


def build_text_person_command(request: dict) -> list[str]:
    command = [
        "python3",
        "scripts/create_talking_person_from_text.py",
        request["text"],
        "--id",
        request["id"],
        "--name",
        request["name"],
        "--base",
        request["base"],
        "--accessory",
        request["accessory"],
        "--animation",
        request["animation"],
        "--tts-service",
        request["tts_service"],
        "--voice",
        request["voice"],
        "--seed",
        str(request["seed"]),
        "--language",
        request["language"],
        "--intensity",
        str(request["intensity"]),
        "--render-profile",
        request["render_profile"],
        "--normalizer",
        request["normalizer"],
    ]
    if request["render"]:
        command.append("--render")
    if request["dry_run"]:
        command.append("--dry-run")
    if request.get("audio_wav"):
        command.extend(["--audio-wav", str(request["audio_wav"])])
    if request.get("audio_manifest"):
        command.extend(["--audio-manifest", str(request["audio_manifest"])])
    if request.get("normalized_audio"):
        command.extend(["--normalized-audio", str(request["normalized_audio"])])
    if request.get("rhubarb_json"):
        command.extend(["--rhubarb-json", str(request["rhubarb_json"])])
    if request.get("lipsync_timeline"):
        command.extend(["--lipsync-timeline", str(request["lipsync_timeline"])])
    audio_cache_key = infer_audio_cache_key(request)
    if audio_cache_key:
        command.extend(["--audio-cache-key", audio_cache_key])
    if request["reuse_audio"]:
        command.append("--reuse-audio")
    if request["reuse_lipsync"]:
        command.append("--reuse-lipsync")
    if request["skip_godot_export"]:
        command.append("--skip-godot-export")
    return command


def tail_lines(path: Path, count: int = 80) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._data_cache: dict | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        with self._lock:
            if self._data_cache is not None:
                return copy.deepcopy(self._data_cache)
            if not self.path.exists():
                self._data_cache = {"jobs": []}
            else:
                self._data_cache = json.loads(self.path.read_text(encoding="utf-8"))
            return copy.deepcopy(self._data_cache)

    def _write(self, data: dict) -> None:
        with self._lock:
            self._data_cache = copy.deepcopy(data)
            tmp_path = self.path.with_name(f".{self.path.name}.tmp")
            tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(self.path)

    def list_jobs(self) -> list[dict]:
        return self._read().get("jobs", [])

    def list_recent_jobs(self, limit: int) -> list[dict]:
        with self._lock:
            if self._data_cache is None:
                self._read()
            jobs = (self._data_cache or {}).get("jobs", [])
            if limit <= 0:
                return copy.deepcopy(jobs)
            return copy.deepcopy(jobs[-limit:])

    def stats(self, max_concurrent: int = 1) -> dict:
        counts = {
            "queued": 0,
            "running": 0,
            "ok": 0,
            "error": 0,
        }
        jobs = self.list_jobs()
        for job in jobs:
            status = job.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        running = counts.get("running", 0)
        return {
            "total": len(jobs),
            **counts,
            "pending": counts.get("queued", 0) + running,
            "max_concurrent": max_concurrent,
            "available_slots": max(0, max_concurrent - running),
        }

    def get_job(self, job_id: str) -> dict:
        for job in self.list_jobs():
            if job.get("id") == job_id:
                return job
        raise KeyError(job_id)

    def create_job(self, request: dict, command: list[str]) -> dict:
        return self.create_jobs([(request, command)])[0]

    def create_jobs(self, requests_and_commands: list[tuple[dict, list[str]]]) -> list[dict]:
        with self._lock:
            data = self._read()
            existing_ids = {job.get("id") for job in data.get("jobs", [])}
            incoming_ids = [request["id"] for request, _command in requests_and_commands]
            if len(set(incoming_ids)) != len(incoming_ids):
                raise ValueError("duplicate job id in batch")
            for job_id in incoming_ids:
                if job_id in existing_ids:
                    raise ValueError(f"job already exists: {job_id}")
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            jobs = []
            for request, command in requests_and_commands:
                job = {
                    "id": request["id"],
                    "request": request,
                    "command": command,
                    "status": "queued",
                    "returncode": None,
                    "created_at": now,
                    "updated_at": now,
                }
                jobs.append(job)
            data.setdefault("jobs", []).extend(jobs)
            self._write(data)
            return jobs

    def update_job(self, job_id: str, **updates) -> dict:
        with self._lock:
            data = self._read()
            for job in data.get("jobs", []):
                if job.get("id") == job_id:
                    job.update(updates)
                    job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    self._write(data)
                    return job
            raise KeyError(job_id)
