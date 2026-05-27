from __future__ import annotations

import json
from pathlib import Path


def build_character_catalog_payload(
    data: dict,
    *,
    source_path: Path,
    source_mtime: float,
    root: Path,
    summarize_job,
) -> dict:
    validations = data.get("godot_lipsync_validation", {})
    validation_by_id = {
        str(item.get("id")): item
        for item in validations.get("checked", [])
        if isinstance(item, dict) and item.get("id")
    } if isinstance(validations, dict) else {}
    characters = [
        summarize_job(job, validation_by_id)
        for job in data.get("jobs", [])
        if isinstance(job, dict)
    ]
    tag_counts: dict[str, int] = {}
    for character in characters:
        for tag in character["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return {
        "status": "ok",
        "source": str(source_path.relative_to(root)) if source_path.is_relative_to(root) else str(source_path),
        "updated_at": source_mtime,
        "summary": {
            "character_count": len(characters),
            "source_job_count": data.get("source_job_count", len(characters)),
            "filtered_job_count": data.get("filtered_job_count", 0),
            "deduped_job_count": data.get("deduped_job_count", 0),
            "lipsync": data.get("godot_lipsync_summary", {}),
            "top_tags": [
                {"tag": tag, "count": count}
                for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:40]
            ],
        },
        "characters": characters,
    }


def write_character_catalog_index_from_payload(
    data: dict,
    *,
    source_path: Path,
    output_path: Path,
    root: Path,
    summarize_job,
) -> dict:
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    source_mtime = source_path.stat().st_mtime
    payload = build_character_catalog_payload(
        data,
        source_path=source_path,
        source_mtime=source_mtime,
        root=root,
        summarize_job=summarize_job,
    )
    index = {
        "status": "ok",
        "source": str(source_path.relative_to(root)) if source_path.is_relative_to(root) else str(source_path),
        "source_mtime": source_mtime,
        "payload": payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    return index
