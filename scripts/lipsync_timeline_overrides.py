from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERRIDES_PATH = ROOT / "config/lipsync_timeline_overrides.json"


def canonical_lipsync_path(value: str | Path | None, *, root: Path = ROOT) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("/workspace/"):
        return text
    path = Path(text)
    if path.is_absolute():
        try:
            return f"/workspace/{path.relative_to(root).as_posix()}"
        except ValueError:
            return text
    return f"/workspace/{path.as_posix()}"


def _override_key(value: str | Path | None) -> str:
    return canonical_lipsync_path(value)


def load_lipsync_timeline_overrides(path: str | Path = DEFAULT_OVERRIDES_PATH) -> dict[str, dict[str, str]]:
    override_path = Path(path)
    if not override_path.exists():
        return {}
    data = json.loads(override_path.read_text(encoding="utf-8"))
    items = data.get("overrides", []) if isinstance(data, dict) else []
    overrides: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = canonical_lipsync_path(item.get("from"))
        target = canonical_lipsync_path(item.get("to"))
        if not source or not target:
            continue
        overrides[source] = {
            "from": source,
            "to": target,
            "reason": str(item.get("reason", "")).strip(),
        }
    return overrides


def apply_lipsync_timeline_override(
    value: str | Path | None,
    overrides: dict[str, dict[str, str]] | None,
) -> dict[str, Any]:
    original = canonical_lipsync_path(value)
    override = (overrides or {}).get(original)
    if not override:
        return {"changed": False, "path": original, "source": original, "reason": ""}
    return {
        "changed": True,
        "path": override["to"],
        "source": override["from"],
        "reason": override.get("reason", ""),
    }


def _timeline_candidates(job: dict[str, Any]) -> list[str]:
    environment = job.get("environment", {}) if isinstance(job.get("environment", {}), dict) else {}
    request = job.get("request", {}) if isinstance(job.get("request", {}), dict) else {}
    values = [
        job.get("lipsync_timeline_override"),
        job.get("lipsync_timeline_json"),
        job.get("lipsync_timeline"),
        request.get("lipsync_timeline_json"),
        request.get("lipsync_timeline"),
        environment.get("LIPSYNC_TIMELINE_JSON"),
    ]
    return [canonical_lipsync_path(value) for value in values if canonical_lipsync_path(value)]


def _timeline_tag_stem(value: str) -> str:
    name = Path(value).name
    if name.endswith(".face.json"):
        name = name.removesuffix(".face.json")
    for suffix in ("_rhubarb", "_stt_fast"):
        if name.endswith(suffix):
            name = name.removesuffix(suffix)
    return name.replace("_", "-")


def apply_job_lipsync_overrides(
    job: dict[str, Any],
    overrides: dict[str, dict[str, str]] | None,
) -> dict[str, Any]:
    if not overrides:
        return job
    for candidate in _timeline_candidates(job):
        result = apply_lipsync_timeline_override(candidate, overrides)
        if not result["changed"]:
            continue
        updated = dict(job)
        environment = dict(updated.get("environment", {}))
        metadata = dict(updated.get("metadata", {}))
        tags = list(metadata.get("tags", []))
        updated["lipsync_timeline_override"] = result["path"]
        updated["lipsync_timeline_override_source"] = result["source"]
        updated["lipsync_timeline_override_reason"] = result["reason"]
        updated["lipsync_timeline_json"] = result["path"]
        environment["LIPSYNC_TIMELINE_JSON"] = result["path"]
        for tag in (
            "lipsync-override:audio-derived",
            f"lipsync-override-from:{_timeline_tag_stem(result['source'])}",
            f"lipsync-override-to:{_timeline_tag_stem(result['path'])}",
        ):
            if tag not in tags:
                tags.append(tag)
        metadata["tags"] = tags
        updated["environment"] = environment
        updated["metadata"] = metadata
        return updated
    return job
