from __future__ import annotations

import html
import json
import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.qa_scoring import score_job
from scripts.lipsync_quality import analyze_lipsync_timeline, lipsync_quality_tags, summarize_lipsync_validation


REQUIRED_LIP_SYNC_VISEMES = ("aa", "ee", "ih", "oh", "ou")


def workspace_path(path: str) -> Path:
    if path.startswith("/workspace/"):
        return ROOT / path.removeprefix("/workspace/")
    return Path(path)


def relative(path: Path, output_path: Path) -> str:
    resolved = path.resolve()
    output_dir = output_path.parent.resolve()
    try:
        return resolved.relative_to(output_dir).as_posix()
    except ValueError:
        pass

    for source_root, alias in (
        (ROOT / "outputs" / "batch", ""),
        (ROOT / "outputs" / "batch_optimized", "batch_optimized"),
        (ROOT / "outputs" / "musetalk", "musetalk"),
        (ROOT / "outputs" / "lipsync", "lipsync"),
        (ROOT / "results", "results"),
    ):
        try:
            mapped = resolved.relative_to(source_root.resolve()).as_posix()
        except ValueError:
            continue
        return f"{alias}/{mapped}" if alias else mapped

    return resolved.as_posix()


def read_report(env: dict) -> dict:
    report_path = workspace_path(env["ANIMATION_REPORT_JSON"])
    if not report_path.exists():
        return {"status": "missing-report", "path": str(report_path)}
    return json.loads(report_path.read_text(encoding="utf-8"))


def read_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def cache_key_from_timeline(value: str) -> str:
    if not value or "/cache/" not in value:
        return ""
    name = Path(value).name
    if name.endswith(".face.json"):
        return name.removesuffix(".face.json")
    return Path(name).stem


def hit_label(value) -> str:
    if value is True:
        return "hit"
    if value is False:
        return "miss"
    return "unknown"


def talking_person_cache_info(job: dict, lipsync_timeline_value: str) -> dict:
    job_id = str(job.get("id", ""))
    prepare_report = read_json_if_exists(ROOT / "results" / "talking_person" / f"{job_id}.prepare.json")
    text_report = read_json_if_exists(ROOT / "results" / "talking_person" / f"{job_id}.text.json")
    prepare_cache = prepare_report.get("cache", {}) if isinstance(prepare_report.get("cache", {}), dict) else {}
    text_cache_paths = text_report.get("cache_paths", {}) if isinstance(text_report.get("cache_paths", {}), dict) else {}
    audio_cache_key = (
        text_report.get("audio_cache_key")
        or prepare_cache.get("audio_cache_key")
        or cache_key_from_timeline(lipsync_timeline_value)
        or cache_key_from_timeline(text_cache_paths.get("lipsync_timeline", ""))
    )
    if not audio_cache_key:
        return {}
    reused_lipsync = prepare_cache.get("reused_lipsync", prepare_report.get("reused_lipsync"))
    cache_paths = dict(text_cache_paths)
    if prepare_cache.get("lipsync_timeline"):
        cache_paths.setdefault("lipsync_timeline", prepare_cache["lipsync_timeline"])
    elif lipsync_timeline_value:
        cache_paths.setdefault("lipsync_timeline", lipsync_timeline_value)
    return {
        "audio_cache_key": str(audio_cache_key),
        "reused_audio": text_report.get("reused_audio"),
        "reused_lipsync": reused_lipsync,
        "audio_cache": hit_label(text_report.get("reused_audio")),
        "lipsync_cache": hit_label(reused_lipsync),
        "paths": cache_paths,
    }


def lipsync_timeline_summary(
    timeline_path: Path | None,
    lipsync_report: dict,
    expression_report: dict,
    timeline_cache: dict[str, dict] | None = None,
) -> dict:
    cache_key = str(timeline_path.resolve()) if timeline_path else ""
    cached = timeline_cache.get(cache_key) if timeline_cache is not None and cache_key else None
    if cached is None:
        timeline = read_json_if_exists(timeline_path) if timeline_path else {}
        quality = analyze_lipsync_timeline(timeline)
        cues = timeline.get("cues", []) if isinstance(timeline.get("cues", []), list) else []
        visemes = []
        for cue in cues:
            if not isinstance(cue, dict):
                continue
            viseme = str(cue.get("viseme", "")).strip()
            if viseme and viseme not in visemes:
                visemes.append(viseme)
        cached = {
            "cue_count": len(cues),
            "duration": timeline.get("duration", 0.0),
            "expression_count": len(timeline.get("expressions", []))
            if isinstance(timeline.get("expressions", []), list)
            else 0,
            "quality": quality,
            "visemes": visemes,
        }
        if timeline_cache is not None and cache_key:
            timeline_cache[cache_key] = cached
    quality = cached.get("quality", {})
    visemes = []
    for viseme in cached.get("visemes", []):
        text = str(viseme).strip()
        if text and text not in visemes:
            visemes.append(text)
    keyed_visemes = sorted(
        {
            *[str(value) for value in lipsync_report.get("keyed_visemes", [])],
            *[str(value) for value in expression_report.get("keyed_visemes", [])],
        }
    )
    missing_visemes = sorted(
        {
            *[str(value) for value in lipsync_report.get("missing_visemes", [])],
            *[str(value) for value in expression_report.get("missing_visemes", [])],
        }
    )
    cue_count = int(cached.get("cue_count", 0) or 0) or int(lipsync_report.get("cue_count", 0) or 0)
    duration = cached.get("duration", lipsync_report.get("duration", 0.0) or 0.0)
    expression_count = int(cached.get("expression_count", 0) or 0)
    return {
        "cue_count": cue_count,
        "duration": round(float(duration or 0.0), 3),
        "visemes": visemes,
        "keyed_visemes": keyed_visemes,
        "missing_visemes": missing_visemes,
        "expression_count": expression_count,
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


def lipsync_summary_label(summary: dict, fallback_status: str) -> str:
    cue_count = int(summary.get("cue_count", 0) or 0)
    duration = float(summary.get("duration", 0.0) or 0.0)
    if cue_count:
        return f"{cue_count} cues / {duration:g}s"
    return fallback_status


def ordered_visemes(values) -> list[str]:
    seen = {str(value).strip() for value in values if str(value).strip()}
    ordered = [viseme for viseme in REQUIRED_LIP_SYNC_VISEMES if viseme in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered


def lip_sync_readiness(
    *,
    has_game_asset: bool,
    has_timeline: bool,
    lipsync_summary: dict,
    report: dict,
) -> dict:
    reasons = []
    if not has_game_asset:
        reasons.append("missing-game-asset")
    if not has_timeline:
        reasons.append("missing-timeline")
    if int(lipsync_summary.get("cue_count", 0) or 0) <= 0:
        reasons.append("empty-timeline")

    face_profile = report.get("face_profile", {}) if isinstance(report.get("face_profile", {}), dict) else {}
    quality = face_profile.get("quality", {}) if isinstance(face_profile.get("quality", {}), dict) else {}
    viseme_profile = face_profile.get("visemes", {}) if isinstance(face_profile.get("visemes", {}), dict) else {}

    if viseme_profile:
        supported_visemes = ordered_visemes(viseme_profile.keys())
        missing_visemes = ordered_visemes(
            quality.get("missing_visemes", set(REQUIRED_LIP_SYNC_VISEMES) - set(supported_visemes))
        )
    elif int(quality.get("viseme_count", 0) or 0) >= len(REQUIRED_LIP_SYNC_VISEMES) and not quality.get("missing_visemes"):
        supported_visemes = list(REQUIRED_LIP_SYNC_VISEMES)
        missing_visemes = []
    else:
        supported_visemes = ordered_visemes(lipsync_summary.get("keyed_visemes", []))
        missing_visemes = ordered_visemes(
            lipsync_summary.get("missing_visemes", set(REQUIRED_LIP_SYNC_VISEMES) - set(supported_visemes))
        )
        if has_game_asset:
            reasons.append("missing-face-profile")

    if missing_visemes:
        reasons.append("missing-visemes")

    status = "ready" if not reasons else "review"
    return {
        "status": status,
        "label": "Lip-ready" if status == "ready" else "Needs lip fix",
        "required_visemes": list(REQUIRED_LIP_SYNC_VISEMES),
        "supported_visemes": supported_visemes,
        "missing_visemes": missing_visemes,
        "reasons": sorted(set(reasons)),
    }


def compact_json(value: object) -> str:
    return html.escape(json.dumps(value, indent=2, sort_keys=True))


def godot_lipsync_validation_index(report: dict | None) -> dict[str, dict]:
    if not isinstance(report, dict):
        return {}
    index = {}
    for item in report.get("checked", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        if item_id:
            index[item_id] = item
    return index


def godot_lipsync_label(validation: dict) -> str:
    if not validation:
        return "unchecked"
    status = str(validation.get("status", "review"))
    cue_count = int(validation.get("cue_count", 0) or 0)
    if cue_count:
        return f"{status} · {cue_count} cues"
    return status


def compact_godot_lipsync_validation(validation: dict | None) -> dict:
    if not isinstance(validation, dict) or not validation:
        return {}
    quality = validation.get("lipsync_quality", {})
    playback = validation.get("playback_status", {})
    compact = {
        "id": validation.get("id"),
        "status": validation.get("status", "review"),
        "issues": validation.get("issues", []),
        "cue_count": validation.get("cue_count", 0),
        "timeline": validation.get("timeline", ""),
        "timeline_visemes": validation.get("timeline_visemes", []),
        "missing_visemes": validation.get("missing_visemes", []),
        "missing_timeline_visemes": validation.get("missing_timeline_visemes", []),
        "source_event_count": validation.get("source_event_count", 0),
        "source_phoneme_count": validation.get("source_phoneme_count", 0),
    }
    if isinstance(quality, dict) and quality:
        compact["lipsync_quality"] = {
            "status": quality.get("status"),
            "grade": quality.get("grade"),
            "score": quality.get("score"),
            "duration": quality.get("duration"),
            "cue_count": quality.get("cue_count"),
            "expression_count": quality.get("expression_count"),
            "active_visemes": quality.get("active_visemes", []),
            "missing_expected_active_visemes": quality.get("missing_expected_active_visemes", []),
            "visemes": quality.get("visemes", []),
            "source_mode": quality.get("source_mode"),
            "source_input_mode": quality.get("source_input_mode"),
            "source_text": quality.get("source_text"),
            "warnings": quality.get("warnings", []),
            "issues": quality.get("issues", []),
        }
    if isinstance(playback, dict) and playback:
        compact["playback"] = {
            "status": playback.get("status"),
            "active_viseme": playback.get("active_viseme"),
            "active_expression_preset": playback.get("active_expression_preset"),
            "cue_index": playback.get("cue_index"),
            "cue_count": playback.get("cue_count"),
            "duration": playback.get("duration"),
        }
    return compact


def compact_lipsync_summary(summary: dict) -> dict:
    if not isinstance(summary, dict):
        return {}
    quality = summary.get("quality", {})
    compact = {
        "cue_count": summary.get("cue_count", 0),
        "duration": summary.get("duration", 0.0),
        "visemes": summary.get("visemes", []),
        "keyed_visemes": summary.get("keyed_visemes", []),
        "missing_visemes": summary.get("missing_visemes", []),
        "expression_count": summary.get("expression_count", 0),
        "source_mode": summary.get("source_mode", "unknown"),
        "source_event_count": summary.get("source_event_count", 0),
        "source_phoneme_count": summary.get("source_phoneme_count", 0),
        "source_input_mode": summary.get("source_input_mode", ""),
        "source_text": summary.get("source_text", ""),
        "source_schema": summary.get("source_schema", ""),
        "source_path": summary.get("source_path", ""),
        "source_unique_phonemes": summary.get("source_unique_phonemes", []),
    }
    if isinstance(quality, dict) and quality:
        compact["quality"] = {
            "status": quality.get("status"),
            "grade": quality.get("grade"),
            "score": quality.get("score"),
            "duration": quality.get("duration"),
            "cue_count": quality.get("cue_count"),
            "cue_density_per_second": quality.get("cue_density_per_second"),
            "active_visemes": quality.get("active_visemes", []),
            "missing_expected_active_visemes": quality.get("missing_expected_active_visemes", []),
            "source_mode": quality.get("source_mode"),
            "source_input_mode": quality.get("source_input_mode"),
            "source_text": quality.get("source_text"),
            "warnings": quality.get("warnings", []),
        }
    return compact


def job_view_model(
    job: dict,
    output_path: Path,
    godot_validation_index: dict[str, dict] | None = None,
    timeline_cache: dict[str, dict] | None = None,
) -> dict:
    env = job.get("environment", {})
    report = read_report(env) if env else {}
    metadata = job.get("metadata", {})
    outfit = report.get("external_outfit", {})
    classification = outfit.get("classification", {})
    fit_check = outfit.get("fit_check", {})
    category = classification.get("category") or env.get("OUTFIT_CATEGORY") or "none"
    animation = report.get("animation") or env.get("ANIMATION_PRESET") or "unknown"
    status = job.get("status") or report.get("status") or "unknown"
    fit_status = fit_check.get("status", "unknown")
    warnings = fit_check.get("warnings", [])
    lipsync = report.get("lipsync_animation", {})
    expression = report.get("expression_animation", {})
    face_quality = report.get("face_profile", {}).get("quality", {})
    optimization = report.get("asset_optimization", {})
    qa = job.get("qa") or score_job(job, report, ROOT)
    review_tags = qa.get("review_tags", [])
    godot_validation = compact_godot_lipsync_validation((godot_validation_index or {}).get(job.get("id", "")))
    tag_values = {
        status,
        f"animation:{animation}",
        f"category:{category}",
        f"fit:{fit_status}",
        f"qa:{qa['qa_grade']}",
        f"priority:{qa['review_priority']}",
        *(f"flag:{flag}" for flag in qa.get("qa_flags", [])),
        *review_tags,
        *metadata.get("tags", []),
    }
    if lipsync.get("enabled"):
        tag_values.add("lipsync:enabled")
        if face_quality.get("grade"):
            tag_values.add(f"face:{face_quality['grade']}")
    if expression.get("preset"):
        tag_values.add(f"face-preset:{str(expression['preset']).replace('_', '-')}")
    if expression.get("keyed_visemes"):
        tag_values.add("facial-visemes")
    if optimization.get("status") == "ok":
        tag_values.add("glb:optimized")
        optimization_profile = str(optimization.get("profile", "") or "")
        if optimization_profile:
            tag_values.add(f"glb-profile:{optimization_profile}")
        optimization_size = optimization_summary(optimization)
        if optimization_size["saved_pct"]:
            tag_values.add(f"glb-saved:{optimization_size['saved_pct']}pct")
    render_paths = [workspace_path(path) for path in report.get("pose_renders", [])]
    preferred_review_frame = qa.get("preferred_review_frame", "")
    renders = [
        {
            "path": relative(path, output_path),
            "name": path.name,
            "angle": render_angle(path.name),
        }
        for path in render_paths
        if path.exists()
    ]
    renders.sort(key=lambda item: render_sort_key(item["name"], preferred_review_frame))
    original_glb_value = report.get("output_glb") or env.get("OUTPUT_GLB", "")
    optimized_glb_value = report.get("optimized_glb", "")
    output_glb_value = optimized_glb_value or original_glb_value
    output_glb = workspace_path(output_glb_value) if output_glb_value else None
    original_glb = workspace_path(original_glb_value) if original_glb_value else None
    optimized_glb = workspace_path(optimized_glb_value) if optimized_glb_value else None
    report_path = workspace_path(env.get("ANIMATION_REPORT_JSON", ""))
    output_vrm = workspace_path(env.get("OUTPUT_VRM", "")) if env.get("OUTPUT_VRM") else None
    talking_video = report.get("talking_video") or job.get("talking_video") or ""
    talking_video_path = workspace_path(talking_video) if talking_video else None
    talking_video_backend = str(report.get("talking_video_backend") or job.get("talking_video_backend") or "").strip()
    if talking_video and not talking_video_backend and "musetalk" in str(talking_video).lower():
        talking_video_backend = "musetalk"
    talking_video_quality = str(report.get("talking_video_quality") or job.get("talking_video_quality") or "").strip()
    if talking_video and not talking_video_quality:
        talking_video_quality = "preview" if talking_video_backend == "musetalk" else "available"
    if talking_video:
        tag_values.add("talking-video:available")
        if talking_video_backend:
            tag_values.add(f"talking-video-backend:{talking_video_backend}")
        if talking_video_quality:
            tag_values.add(f"talking-video-quality:{talking_video_quality}")
    lipsync_timeline_value = (
        job.get("lipsync_timeline_override")
        or lipsync.get("timeline")
        or env.get("LIPSYNC_TIMELINE_JSON", "")
        or job.get("lipsync_timeline_json", "")
    )
    cache = talking_person_cache_info(job, lipsync_timeline_value)
    if cache:
        tag_values.add("cache:line")
        tag_values.add(f"cache-key:{cache['audio_cache_key']}")
        tag_values.add(f"audio-cache:{cache['audio_cache']}")
        tag_values.add(f"lipsync-cache:{cache['lipsync_cache']}")
    lipsync_timeline_path = workspace_path(lipsync_timeline_value) if lipsync_timeline_value else None
    lipsync_summary = compact_lipsync_summary(
        lipsync_timeline_summary(lipsync_timeline_path, lipsync, expression, timeline_cache)
    )
    if lipsync.get("enabled"):
        tag_values.update(lipsync_quality_tags(lipsync_summary.get("quality", {})))
        if lipsync_summary.get("cue_count"):
            tag_values.add(f"lipsync-cues:{lipsync_summary['cue_count']}")
        if lipsync_summary.get("source_event_count"):
            tag_values.add(f"lipsync-source-events:{lipsync_summary['source_event_count']}")
        if lipsync_summary.get("source_phoneme_count"):
            tag_values.add(f"lipsync-phonemes:{lipsync_summary['source_phoneme_count']}")
        for viseme in lipsync_summary.get("visemes", []):
            tag_values.add(f"viseme:{viseme}")
        for viseme in lipsync_summary.get("keyed_visemes", []):
            tag_values.add(f"keyed-viseme:{viseme}")
        for viseme in lipsync_summary.get("missing_visemes", []):
            tag_values.add(f"missing-viseme:{viseme}")
    lip_readiness = lip_sync_readiness(
        has_game_asset=bool(output_glb_value),
        has_timeline=bool(lipsync_timeline_value),
        lipsync_summary=lipsync_summary,
        report=report,
    )
    tag_values.add("lip-ready" if lip_readiness["status"] == "ready" else "needs-lip-fix")
    tag_values.add(f"lipsync-readiness:{lip_readiness['status']}")
    if godot_validation:
        godot_status = str(godot_validation.get("status", "review"))
        tag_values.add(f"godot-lipsync:{godot_status}")
        tag_values.add("godot-lipsync-ok" if godot_status == "ok" else "godot-lipsync-review")
        for issue in godot_validation.get("issues", []):
            tag_values.add(f"godot-lipsync-issue:{issue}")
    render_mode = "control-only" if str(env.get("RENDER_POSE_STILLS", "1")) != "1" else "visual"
    if render_mode == "control-only":
        tag_values.add("control-only")
        tag_values.add("control-ready")
        tag_values.add("renderless-preview")
    tags = sorted(tag_values)
    return {
        "id": job.get("id", "unknown"),
        "display_name": metadata.get("display_name") or job.get("id", "unknown").replace("-", " ").title(),
        "persona": metadata.get("persona") or "",
        "notes": metadata.get("notes") or "",
        "status": status,
        "animation": animation,
        "category": category,
        "fit_status": fit_status,
        "warnings": warnings,
        "tags": tags,
        "renders": renders,
        "render_mode": render_mode,
        "glb": relative(output_glb, output_path)
        if output_glb and (output_glb.exists() or output_glb_value)
        else "",
        "original_glb": relative(original_glb, output_path)
        if original_glb and original_glb_value and original_glb != output_glb
        else "",
        "optimized_glb": relative(optimized_glb, output_path) if optimized_glb and optimized_glb_value else "",
        "vrm": relative(output_vrm, output_path) if output_vrm and output_vrm.exists() else "",
        "talking_video": relative(talking_video_path, output_path) if talking_video_path else "",
        "talking_video_backend": talking_video_backend,
        "talking_video_quality": talking_video_quality,
        "lipsync_timeline": relative(lipsync_timeline_path, output_path) if lipsync_timeline_path else "",
        "lipsync_timeline_api": lipsync_timeline_value,
        "report": relative(report_path, output_path) if report_path.exists() else "",
        "elapsed_seconds": job.get("elapsed_seconds"),
        "timings": report.get("timings", {}),
        "exports": report.get("exports", {}),
        "frames": report.get("frames", []),
        "expression": expression,
        "lipsync": lipsync,
        "lipsync_summary": lipsync_summary,
        "lip_sync_readiness": lip_readiness,
        "godot_lipsync_validation": godot_validation,
        "cache": cache,
        "face_quality": face_quality,
        "asset_optimization": optimization,
        "fit_metrics": fit_check.get("metrics", {}),
        "review_tags": review_tags,
        "review_notes": qa.get("review_notes", []),
        "preferred_review_frame": preferred_review_frame,
        **qa,
    }


def render_sort_key(name: str, preferred_review_frame: str) -> tuple[int, str]:
    if preferred_review_frame and name == preferred_review_frame:
        return (0, name)
    if "portrait" in name:
        return (1, name)
    return (2, name)


def render_angle(name: str) -> str:
    if "portrait" in name:
        return "portrait"
    if "side" in name:
        return "side"
    if "back" in name:
        return "back"
    return "front"


def tag_button(tag: str) -> str:
    return f'<button type="button" class="chip" data-filter="{html.escape(tag)}">{html.escape(tag)}</button>'


def label_value(value: str) -> str:
    normalized = str(value).lower()
    if normalized == "musetalk":
        return "MuseTalk"
    if normalized in {"available", "preview"}:
        return normalized
    return str(value).replace("_", " ").replace("-", " ").title()


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def optimization_summary(optimization: dict) -> dict:
    if not isinstance(optimization, dict) or not optimization:
        return {
            "status": "none",
            "profile": "",
            "label": "not optimized",
            "saved_pct": 0,
            "size_ratio": "",
        }
    status = str(optimization.get("status", "review"))
    profile = str(optimization.get("profile", "") or "")
    source_bytes = int(optimization.get("source_bytes", 0) or 0)
    optimized_bytes = int(optimization.get("optimized_bytes", 0) or 0)
    ratio_value = optimization.get("size_ratio")
    if ratio_value is None and source_bytes:
        ratio_value = optimized_bytes / source_bytes
    size_ratio = round(float(ratio_value), 4) if ratio_value is not None else ""
    saved_pct = max(0, round((1 - float(size_ratio)) * 100)) if size_ratio != "" else 0
    label = (
        f"optimized · {saved_pct}% saved · {format_bytes(optimized_bytes)}"
        if status == "ok"
        else f"{status} · {format_bytes(optimized_bytes) if optimized_bytes else 'n/a'}"
    )
    return {
        "status": status,
        "profile": profile,
        "label": label,
        "saved_pct": saved_pct,
        "size_ratio": size_ratio,
    }


def phoneme_strip(model: dict) -> str:
    summary = model["lipsync_summary"]
    phonemes = [str(value) for value in summary.get("source_unique_phonemes", []) if str(value).strip()]
    if not phonemes and not int(summary.get("source_phoneme_count", 0) or 0):
        return ""
    phoneme_count = int(summary.get("source_phoneme_count", 0) or len(phonemes))
    phoneme_text = ", ".join(phonemes) if phonemes else "none"
    source_parts = [
        str(summary.get("source_mode", "unknown") or "unknown"),
        str(summary.get("source_input_mode", "") or ""),
    ]
    source_text = " / ".join(part for part in source_parts if part)
    return f"""
      <div class="phoneme-strip">
        <div><b>Phonemes</b><span>{html.escape(str(phoneme_count))} · {html.escape(phoneme_text)}</span></div>
        <div><b>Source</b><span>{html.escape(source_text)}</span></div>
      </div>
    """


def renderless_preview(model: dict) -> str:
    if model["renders"]:
        return ""
    if model.get("render_mode") != "control-only":
        return ""
    detail_items = [
        ("Mode", "Control-ready"),
        ("Preview", "No Blender PNG"),
        ("GLB", "available" if model["glb"] or model["optimized_glb"] else "missing"),
        ("Lip sync", godot_lipsync_label(model["godot_lipsync_validation"])),
    ]
    details = "\n".join(
        f"<div><b>{html.escape(label)}</b><span>{html.escape(value)}</span></div>"
        for label, value in detail_items
    )
    return f"""
        <div class="renderless-preview">
          {details}
        </div>
        """


def qa_detail_payload(model: dict) -> dict:
    return {
        "qa_score": model["qa_score"],
        "qa_grade": model["qa_grade"],
        "review_priority": model["review_priority"],
        "qa_flags": model["qa_flags"],
        "review_tags": model["review_tags"],
        "review_notes": model["review_notes"],
        "preferred_review_frame": model["preferred_review_frame"],
        "expected_render_count": model["expected_render_count"],
        "actual_render_count": model["actual_render_count"],
        "timings": model["timings"],
        "exports": model["exports"],
        "frames": model["frames"],
        "expression": model["expression"],
        "lipsync": model["lipsync"],
        "lipsync_summary": model["lipsync_summary"],
        "lip_sync_readiness": model["lip_sync_readiness"],
        "godot_lipsync_validation": model["godot_lipsync_validation"],
        "lipsync_timeline": model["lipsync_timeline_api"],
        "cache": model["cache"],
        "face_quality": model["face_quality"],
        "asset_optimization": model["asset_optimization"],
        "fit_metrics": model["fit_metrics"],
    }


def compact_qa_detail_payload(model: dict) -> dict:
    payload = qa_detail_payload(model)
    return {
        "qa_score": payload["qa_score"],
        "qa_grade": payload["qa_grade"],
        "review_priority": payload["review_priority"],
        "qa_flags": payload["qa_flags"],
        "review_notes": payload["review_notes"],
        "preferred_review_frame": payload["preferred_review_frame"],
        "actual_render_count": payload["actual_render_count"],
        "lipsync_summary": payload["lipsync_summary"],
        "lip_sync_readiness": payload["lip_sync_readiness"],
        "godot_lipsync_validation": payload["godot_lipsync_validation"],
        "lipsync_timeline": payload["lipsync_timeline"],
        "asset_optimization": payload["asset_optimization"],
    }


def render_card(model: dict, *, detail_mode: str = "full") -> str:
    tag_markup = " ".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in model["tags"])
    images = "\n".join(
        f"""
        <a class="thumb {html.escape(image['angle'])}" href="{html.escape(image['path'])}">
          <img src="{html.escape(image['path'])}" alt="{html.escape(model['display_name'])} {html.escape(image['name'])}" loading="lazy">
          <span>{html.escape(image['name'])}</span>
        </a>
        """
        for image in model["renders"]
    )
    if not images:
        images = renderless_preview(model)
    video_title = "Rendered preview" if model["talking_video_quality"] == "preview" else "Talking video"
    video_detail = " / ".join(
        label_value(value)
        for value in (model["talking_video_backend"], model["talking_video_quality"])
        if value
    )
    talking_video = (
        f"""
        <div class="talking-video">
          <b>{html.escape(video_title)}</b>
          <span>{html.escape(video_detail)}</span>
          <video src="{html.escape(model['talking_video'])}" controls preload="metadata"></video>
        </div>
        """
        if model["talking_video"]
        else ""
    )
    warnings = (
        "<span class=\"ok\">no warnings</span>"
        if not model["warnings"]
        else ", ".join(html.escape(warning) for warning in model["warnings"])
    )
    lipsync_status = "on" if model["lipsync"].get("enabled") else "off"
    optimization = optimization_summary(model["asset_optimization"])
    readiness = model["lip_sync_readiness"]
    lipsync_quality = model["lipsync_summary"].get("quality", {})
    has_lipsync_timeline = bool(model["lipsync_timeline_api"] or model["lipsync_timeline"])
    display_quality = lipsync_quality if has_lipsync_timeline or model["lipsync"].get("enabled") else {}
    lipsync_label = f"{readiness['label']} · {lipsync_summary_label(model['lipsync_summary'], lipsync_status)}"
    quality_label = (
        f"{display_quality.get('status', 'unknown')} / {display_quality.get('grade', 'n/a')}"
        if display_quality
        else "off"
    )
    lipsync_visemes = ", ".join(model["lipsync_summary"].get("visemes", [])) or "none"
    phoneme_markup = phoneme_strip(model)
    phoneme_values = " ".join(str(value) for value in model["lipsync_summary"].get("source_unique_phonemes", []))
    readiness_detail = readiness["label"]
    if readiness["reasons"]:
        readiness_detail = f"{readiness_detail}: {', '.join(readiness['reasons'])}"
    cache_status = "none"
    if model["cache"]:
        cache_status = f"{model['cache']['audio_cache']}/{model['cache']['lipsync_cache']}"
    godot_lipsync = model["godot_lipsync_validation"]
    godot_lipsync_status = str(godot_lipsync.get("status", "")) if godot_lipsync else ""
    godot_lipsync_detail = godot_lipsync_label(godot_lipsync)
    links = []
    if model["optimized_glb"]:
        links.append(f'<a href="{html.escape(model["optimized_glb"])}">Optimized GLB</a>')
    elif model["glb"]:
        links.append(f'<a href="{html.escape(model["glb"])}">GLB</a>')
    if model["original_glb"]:
        links.append(f'<a href="{html.escape(model["original_glb"])}">Original GLB</a>')
    if model["vrm"]:
        links.append(f'<a href="{html.escape(model["vrm"])}">VRM</a>')
    if model["talking_video"]:
        links.append(f'<a href="{html.escape(model["talking_video"])}">{html.escape(video_title)}</a>')
    if model["lipsync_timeline"]:
        links.append(f'<a href="{html.escape(model["lipsync_timeline"])}">Timeline JSON</a>')
    if model["report"]:
        links.append(f'<a href="{html.escape(model["report"])}">JSON</a>')
    link_markup = " ".join(links)
    detail_markup = qa_json_markup(model, detail_mode)
    search_blob = " ".join(
        [
            model["id"],
            model["display_name"],
            model["persona"],
            model["notes"],
            model["animation"],
            model["category"],
            " ".join(model["tags"]),
            " ".join(model["qa_flags"]),
            " ".join(model["review_notes"]),
            lipsync_visemes,
            str(model["lipsync_summary"].get("source_mode", "")),
            " ".join(model["lipsync_summary"].get("source_unique_phonemes", [])),
            godot_lipsync_detail,
        ]
    ).lower()
    flag_markup = (
        "<span class=\"ok\">no QA flags</span>"
        if not model["qa_flags"]
        else " ".join(f'<span class="tag warn">{html.escape(flag)}</span>' for flag in model["qa_flags"])
    )
    return f"""
    <article class="card" data-character-id="{html.escape(model['id'])}" data-animation="{html.escape(model['animation'])}" data-lipsync-timeline="{html.escape(model['lipsync_timeline_api'])}" data-lipsync-cues="{html.escape(str(model['lipsync_summary'].get('cue_count', 0)))}" data-lipsync-duration="{html.escape(str(model['lipsync_summary'].get('duration', 0.0)))}" data-lipsync-visemes="{html.escape(' '.join(model['lipsync_summary'].get('visemes', [])))}" data-lipsync-source="{html.escape(str(model['lipsync_summary'].get('source_mode', 'unknown')))}" data-lipsync-source-events="{html.escape(str(model['lipsync_summary'].get('source_event_count', 0)))}" data-lipsync-phonemes="{html.escape(phoneme_values)}" data-lipsync-readiness="{html.escape(readiness['status'])}" data-lipsync-quality="{html.escape(str(display_quality.get('status', 'off')))}" data-godot-lipsync-validation="{html.escape(godot_lipsync_status)}" data-glb-optimized="{html.escape(optimization['status'])}" data-glb-profile="{html.escape(optimization['profile'])}" data-glb-size-ratio="{html.escape(str(optimization['size_ratio']))}" data-glb-saved-pct="{html.escape(str(optimization['saved_pct']))}" data-review-priority="{html.escape(model['review_priority'])}" data-renders="{html.escape(str(len(model['renders'])))}" data-render-mode="{html.escape(model['render_mode'])}" data-tags="{html.escape(' '.join(model['tags']))}" data-search="{html.escape(search_blob)}">
      <div class="card-top">
        <div>
          <h2>{html.escape(model["display_name"])}</h2>
          <p>{html.escape(model["persona"])}</p>
        </div>
        <div class="score {html.escape(model["status"])}">QA {html.escape(model["qa_grade"])} · {html.escape(str(model["qa_score"]))}</div>
      </div>
      <div class="meta-grid">
        <div><b>Animation</b><span>{html.escape(model["animation"])}</span></div>
        <div><b>Accessory</b><span>{html.escape(model["category"])}</span></div>
        <div><b>Lip sync</b><span>{html.escape(lipsync_label)}</span></div>
        <div><b>Lip quality</b><span>{html.escape(quality_label)}</span></div>
        <div><b>Godot lip</b><span>{html.escape(godot_lipsync_detail)}</span></div>
        <div><b>GLB</b><span>{html.escape(optimization['label'])}</span></div>
        <div><b>Video</b><span>{html.escape(video_detail or "none")}</span></div>
        <div><b>Cache</b><span>{html.escape(cache_status)}</span></div>
        <div><b>Priority</b><span>{html.escape(model["review_priority"])}</span></div>
        <div><b>Time</b><span>{html.escape(str(model["elapsed_seconds"] or "n/a"))}s</span></div>
      </div>
      {phoneme_markup}
      <div class="godot-actions">
        <button type="button" data-action="load">Load</button>
        <button type="button" data-action="play">Play</button>
        <button type="button" data-action="talk">Talk</button>
        <button type="button" data-action="smile">Smile</button>
        <button type="button" data-action="export">Export</button>
        <button type="button" data-action="copy">Copy API</button>
      </div>
      <div class="renders">{images}</div>
      {talking_video}
      <div class="tags">{tag_markup}</div>
      <details>
        <summary>QA details</summary>
        <div class="qa">
          <p><b>Warnings:</b> {warnings}</p>
          <p><b>QA flags:</b> {flag_markup}</p>
          <p><b>Review notes:</b> {html.escape("; ".join(model["review_notes"]) or "none")}</p>
          <p><b>Lip-sync readiness:</b> {html.escape(readiness_detail)}</p>
          <p><b>Lip-sync quality:</b> {html.escape(quality_label)}</p>
          <p><b>Godot lip-sync validation:</b> {html.escape(godot_lipsync_detail)}</p>
          <p><b>Visemes:</b> {html.escape(lipsync_visemes)}</p>
          <p><b>Outputs:</b> {link_markup}</p>
          <p><b>Notes:</b> {html.escape(model["notes"])}</p>
          {detail_markup}
        </div>
      </details>
    </article>
    """


def qa_json_markup(model: dict, detail_mode: str) -> str:
    if detail_mode == "compact":
        return """
          <p class="compact-note">Full debug JSON is available from the linked report and validation files.</p>
        """
    return f"<pre>{compact_json(qa_detail_payload(model))}</pre>"


def build_gallery(batch_result: dict, output_path: Path, *, detail_mode: str = "full") -> str:
    if detail_mode not in {"full", "compact"}:
        raise ValueError("detail_mode must be 'full' or 'compact'")
    validation_index = godot_lipsync_validation_index(batch_result.get("godot_lipsync_validation", {}))
    lipsync_summary = batch_result.get("godot_lipsync_summary") or summarize_lipsync_validation(
        batch_result.get("godot_lipsync_validation", {})
    )
    timeline_cache: dict[str, dict] = {}
    models = [
        job_view_model(job, output_path, validation_index, timeline_cache)
        for job in batch_result.get("jobs", [])
    ]
    all_tags = sorted({tag for model in models for tag in model["tags"]})
    cards = "\n".join(render_card(model, detail_mode=detail_mode) for model in models)
    chips = "\n".join(tag_button(tag) for tag in all_tags)
    ok_count = sum(1 for model in models if model["status"] == "ok")
    review_count = sum(1 for model in models if model["review_priority"] != "ship")
    ship_count = sum(1 for model in models if model["review_priority"] == "ship")
    elapsed = batch_result.get("elapsed_seconds", "n/a")
    manifest = batch_result.get("manifest", "")
    lip_ok = int(lipsync_summary.get("ok_count", 0) or 0)
    lip_review = int(lipsync_summary.get("review_count", 0) or 0)
    lip_grades = ", ".join(
        f"{grade}:{count}" for grade, count in lipsync_summary.get("grade_counts", {}).items()
    ) or "n/a"
    lip_missing = ", ".join(
        f"{viseme}:{count}" for viseme, count in lipsync_summary.get("missing_active_viseme_counts", {}).items()
    ) or "none"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Person Factory Review</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #15171a;
      --panel: #202328;
      --panel-2: #292d33;
      --line: #3c424b;
      --text: #f4f0e8;
      --muted: #aaa7a0;
      --accent: #74d2c1;
      --accent-2: #f2bd62;
      --bad: #ff7d7d;
      --ok: #88d07b;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    header {{ position: sticky; top: 0; z-index: 4; background: rgba(21, 23, 26, 0.96); border-bottom: 1px solid var(--line); backdrop-filter: blur(12px); }}
    .bar {{ display: grid; grid-template-columns: minmax(240px, 1fr) auto; gap: 18px; align-items: end; max-width: 1500px; margin: 0 auto; padding: 18px 22px; }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    .sub {{ margin-top: 5px; color: var(--muted); font-size: 13px; }}
    .stats {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }}
    .stat {{ min-width: 86px; padding: 9px 12px; border: 1px solid var(--line); background: var(--panel); border-radius: 6px; }}
    .stat b {{ display: block; font-size: 18px; }}
    .stat span {{ color: var(--muted); font-size: 11px; text-transform: uppercase; }}
    .lip-batch-summary {{ max-width: 1500px; margin: 0 auto; padding: 0 22px 14px; display: flex; gap: 8px; flex-wrap: wrap; }}
    .lip-batch-summary span {{ border: 1px solid var(--line); background: #171a1e; border-radius: 5px; padding: 6px 8px; color: var(--muted); font-size: 12px; }}
    .controls {{ max-width: 1500px; margin: 0 auto; padding: 0 22px 16px; display: grid; gap: 12px; }}
    .search-row {{ display: grid; grid-template-columns: minmax(220px, 1fr) auto auto; gap: 10px; }}
    input {{ width: 100%; border: 1px solid var(--line); background: #111316; color: var(--text); border-radius: 6px; padding: 11px 12px; font-size: 14px; }}
    button, .chip {{ border: 1px solid var(--line); background: var(--panel-2); color: var(--text); border-radius: 6px; padding: 9px 11px; font-size: 13px; cursor: pointer; }}
    button:hover, .chip:hover {{ border-color: var(--accent); }}
    .chip.active {{ background: var(--accent); color: #081512; border-color: var(--accent); }}
    .chips {{ display: flex; gap: 7px; flex-wrap: wrap; max-height: 96px; overflow: auto; padding-bottom: 2px; }}
    .pager {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; color: var(--muted); font-size: 13px; }}
    .pager select {{ width: auto; border: 1px solid var(--line); background: #111316; color: var(--text); border-radius: 6px; padding: 9px 10px; }}
    .pager button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    main {{ max-width: 1500px; margin: 0 auto; padding: 20px 22px 34px; display: grid; grid-template-columns: repeat(auto-fit, minmax(390px, 1fr)); gap: 18px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.22); }}
    .card.hidden {{ display: none; }}
    .card-top {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: start; padding: 15px 15px 10px; }}
    h2 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
    .card p {{ margin: 5px 0 0; color: var(--muted); font-size: 13px; }}
    .score {{ border: 1px solid var(--line); border-radius: 5px; padding: 5px 8px; font-size: 12px; text-transform: uppercase; }}
    .score.ok {{ color: var(--ok); border-color: rgba(136,208,123,0.6); }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(104px, 1fr)); gap: 1px; background: var(--line); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .meta-grid div {{ min-width: 0; background: #1b1e22; padding: 9px; }}
    .meta-grid b {{ display: block; color: var(--muted); font-size: 10px; text-transform: uppercase; margin-bottom: 4px; }}
    .meta-grid span {{ display: block; overflow-wrap: break-word; font-size: 12px; }}
    .phoneme-strip {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1px; background: var(--line); border-bottom: 1px solid var(--line); }}
    .phoneme-strip div {{ min-width: 0; background: #16191d; padding: 9px 10px; }}
    .phoneme-strip b {{ display: block; color: var(--accent-2); font-size: 10px; text-transform: uppercase; margin-bottom: 4px; }}
    .phoneme-strip span {{ display: block; overflow-wrap: break-word; font-size: 12px; }}
    .godot-actions {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 1px; border-bottom: 1px solid var(--line); background: var(--line); }}
    .godot-actions button {{ border: 0; border-radius: 0; background: #20252b; min-height: 34px; padding: 8px 6px; }}
    .godot-actions button:hover {{ background: #27343a; }}
    .renders {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: #101114; }}
    .thumb {{ position: relative; min-height: 220px; background: #101114; color: var(--muted); text-decoration: none; }}
    .thumb img {{ width: 100%; height: 100%; aspect-ratio: 2 / 3; object-fit: cover; display: block; }}
    .thumb span {{ position: absolute; left: 8px; bottom: 8px; padding: 4px 6px; background: rgba(0,0,0,0.64); border-radius: 4px; font-size: 11px; }}
    .renderless-preview {{ grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; min-height: 118px; background: var(--line); border-top: 1px solid var(--line); }}
    .renderless-preview div {{ min-width: 0; background: #15191e; padding: 14px 12px; }}
    .renderless-preview b {{ display: block; color: var(--accent-2); font-size: 10px; text-transform: uppercase; margin-bottom: 7px; }}
    .renderless-preview span {{ display: block; color: var(--text); font-size: 13px; overflow-wrap: break-word; }}
    .talking-video {{ border-top: 1px solid var(--line); padding: 12px 14px; background: #181b1f; }}
    .talking-video b {{ display: block; margin-bottom: 8px; font-size: 12px; color: var(--muted); text-transform: uppercase; }}
    .talking-video span {{ display: block; margin: -4px 0 8px; color: var(--accent-2); font-size: 12px; }}
    .talking-video video {{ display: block; width: 100%; max-height: 360px; background: #050607; border: 1px solid var(--line); border-radius: 6px; }}
    .tags {{ display: flex; gap: 6px; flex-wrap: wrap; padding: 12px 14px; }}
    .tag {{ display: inline-flex; padding: 4px 7px; border-radius: 4px; border: 1px solid #4b525c; color: #d7d3cb; font-size: 11px; }}
    details {{ border-top: 1px solid var(--line); }}
    summary {{ cursor: pointer; padding: 11px 14px; color: var(--accent); }}
    .qa {{ padding: 0 14px 14px; color: #d7d3cb; font-size: 13px; }}
    .qa a {{ color: var(--accent-2); margin-right: 10px; }}
    .ok {{ color: var(--ok); }}
    pre {{ white-space: pre-wrap; overflow: auto; background: #111316; border: 1px solid var(--line); border-radius: 6px; padding: 10px; font-size: 11px; }}
    .empty {{ display: none; max-width: 1500px; margin: 20px auto; padding: 18px 22px; color: var(--muted); }}
    .empty.visible {{ display: block; }}
    @media (max-width: 780px) {{
      .bar, .search-row {{ grid-template-columns: 1fr; }}
      .stats {{ justify-content: start; }}
      main {{ grid-template-columns: 1fr; padding: 14px; }}
      .meta-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .phoneme-strip {{ grid-template-columns: 1fr; }}
      .godot-actions {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>Person Factory Review</h1>
        <div class="sub">{html.escape(manifest)} · runner {html.escape(str(batch_result.get("runner", "standard")))} · elapsed {html.escape(str(elapsed))}s</div>
      </div>
      <div class="stats">
        <div class="stat"><b id="visibleCount">{len(models)}</b><span>visible</span></div>
        <div class="stat"><b>{len(models)}</b><span>people</span></div>
        <div class="stat"><b>{ok_count}</b><span>ok jobs</span></div>
        <div class="stat"><b>{ship_count}</b><span>ship</span></div>
        <div class="stat"><b>{review_count}</b><span>review</span></div>
        <div class="stat"><b>{lip_ok}</b><span>lip ok</span></div>
        <div class="stat"><b>{lip_review}</b><span>lip review</span></div>
      </div>
    </div>
    <div class="lip-batch-summary">
      <span>Visemes: {html.escape(', '.join(lipsync_summary.get('active_visemes', [])) or 'none')}</span>
      <span>Grades: {html.escape(lip_grades)}</span>
      <span>Missing active: {html.escape(lip_missing)}</span>
      <span>Cues: {html.escape(str(lipsync_summary.get('cue_count_min', 0)))}-{html.escape(str(lipsync_summary.get('cue_count_max', 0)))}</span>
      <span>Expressions: {html.escape(str(lipsync_summary.get('expression_count_min', 0)))}-{html.escape(str(lipsync_summary.get('expression_count_max', 0)))}</span>
    </div>
    <div class="controls">
      <div class="search-row">
        <input id="search" type="search" placeholder="Search names, personas, tags, animations, accessories">
        <button id="clearFilters" type="button">Clear filters</button>
        <button id="showReview" type="button">Needs review</button>
      </div>
      <div class="chips" id="chips">{chips}</div>
      <div class="pager">
        <button id="prevPage" type="button">Previous</button>
        <span id="pageInfo">Page 1</span>
        <button id="nextPage" type="button">Next</button>
        <label for="pageSize">Cards per page</label>
        <select id="pageSize">
          <option value="24">24</option>
          <option value="48" selected>48</option>
          <option value="96">96</option>
          <option value="99999">All</option>
        </select>
      </div>
      <div class="sub" id="apiStatus">Godot API: idle</div>
    </div>
  </header>
  <div class="empty" id="empty">No people match the current filters.</div>
  <main id="grid">{cards}</main>
  <script>
    const cards = Array.from(document.querySelectorAll('.card'));
    const chips = Array.from(document.querySelectorAll('.chip'));
    const search = document.getElementById('search');
    const visibleCount = document.getElementById('visibleCount');
    const empty = document.getElementById('empty');
    const apiStatus = document.getElementById('apiStatus');
    const prevPage = document.getElementById('prevPage');
    const nextPage = document.getElementById('nextPage');
    const pageInfo = document.getElementById('pageInfo');
    const pageSize = document.getElementById('pageSize');
    const activeTags = new Set();
    let reviewOnly = false;
    let currentPage = 1;
    const godotBase = 'http://127.0.0.1:8790';

    function setApiStatus(text) {{
      apiStatus.textContent = `Godot API: ${{text}}`;
    }}

    async function godotPost(path, payload) {{
      const response = await fetch(`${{godotBase}}${{path}}`, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload || {{}})
      }});
      const data = await response.json();
      if (data.status && data.status !== 'ok') throw new Error(data.error || data.status);
      return data;
    }}

    function commandFor(card, action) {{
      const id = card.dataset.characterId;
      const animation = `${{card.dataset.animation}}_Armature`;
      const timeline = card.dataset.lipsyncTimeline;
      if (action === 'load') return `curl -X POST ${{godotBase}}/load -H 'Content-Type: application/json' -d '{{"id":"${{id}}"}}'`;
      if (action === 'play') return `curl -X POST ${{godotBase}}/animation -H 'Content-Type: application/json' -d '{{"name":"${{animation}}","time":1.0}}'`;
      if (action === 'talk') return timeline ? `curl -X POST ${{godotBase}}/load -H 'Content-Type: application/json' -d '{{"id":"${{id}}"}}' && curl -X POST ${{godotBase}}/lipsync -H 'Content-Type: application/json' -d '{{"path":"${{timeline}}"}}'` : `curl -X POST ${{godotBase}}/speak -H 'Content-Type: application/json' -d '{{"text":"hello","value":1.0}}'`;
      if (action === 'smile') return `curl -X POST ${{godotBase}}/expression -H 'Content-Type: application/json' -d '{{"joy":0.7,"close":0.0}}'`;
      return `curl -X POST ${{godotBase}}/export-game-asset -H 'Content-Type: application/json' -d '{{"id":"${{id}}"}}'`;
    }}

    function applyFilters(options = {{}}) {{
      if (!options.keepPage) currentPage = 1;
      const query = search.value.trim().toLowerCase();
      const matches = [];
      cards.forEach((card) => {{
        const tags = card.dataset.tags.split(' ');
        const tagMatch = Array.from(activeTags).every((tag) => tags.includes(tag));
        const searchMatch = !query || card.dataset.search.includes(query);
        const priorityMatch = !reviewOnly || card.dataset.reviewPriority !== 'ship';
        const show = tagMatch && searchMatch && priorityMatch;
        if (show) matches.push(card);
      }});
      const perPage = Number.parseInt(pageSize.value, 10) || 48;
      const pageCount = Math.max(1, Math.ceil(matches.length / perPage));
      currentPage = Math.min(Math.max(1, currentPage), pageCount);
      const start = (currentPage - 1) * perPage;
      const shown = new Set(matches.slice(start, start + perPage));
      cards.forEach((card) => card.classList.toggle('hidden', !shown.has(card)));
      visibleCount.textContent = matches.length;
      pageInfo.textContent = matches.length ? `Page ${{currentPage}} / ${{pageCount}} · showing ${{shown.size}} of ${{matches.length}}` : 'No matches';
      prevPage.disabled = currentPage <= 1;
      nextPage.disabled = currentPage >= pageCount;
      empty.classList.toggle('visible', matches.length === 0);
    }}

    chips.forEach((chip) => chip.addEventListener('click', () => {{
      const tag = chip.dataset.filter;
      if (activeTags.has(tag)) activeTags.delete(tag);
      else activeTags.add(tag);
      chip.classList.toggle('active', activeTags.has(tag));
      applyFilters();
    }}));
    search.addEventListener('input', applyFilters);
    pageSize.addEventListener('change', () => applyFilters());
    prevPage.addEventListener('click', () => {{
      currentPage -= 1;
      applyFilters({{keepPage: true}});
    }});
    nextPage.addEventListener('click', () => {{
      currentPage += 1;
      applyFilters({{keepPage: true}});
    }});
    document.getElementById('clearFilters').addEventListener('click', () => {{
      activeTags.clear();
      reviewOnly = false;
      chips.forEach((chip) => chip.classList.remove('active'));
      search.value = '';
      applyFilters();
    }});
    document.getElementById('showReview').addEventListener('click', () => {{
      reviewOnly = !reviewOnly;
      document.getElementById('showReview').classList.toggle('active', reviewOnly);
      applyFilters();
    }});
    document.addEventListener('click', async (event) => {{
      const button = event.target.closest('.godot-actions button');
      if (!button) return;
      const card = button.closest('.card');
      const id = card.dataset.characterId;
      const animation = `${{card.dataset.animation}}_Armature`;
      const timeline = card.dataset.lipsyncTimeline;
      const action = button.dataset.action;
      try {{
        if (action === 'copy') {{
          await navigator.clipboard.writeText(commandFor(card, 'load') + '\\n' + commandFor(card, 'play') + '\\n' + commandFor(card, 'talk') + '\\n' + commandFor(card, 'smile') + '\\n' + commandFor(card, 'export'));
          setApiStatus(`copied commands for ${{id}}`);
        }} else if (action === 'load') {{
          await godotPost('/load', {{id}});
          setApiStatus(`loaded ${{id}}`);
        }} else if (action === 'play') {{
          await godotPost('/load', {{id}});
          await godotPost('/animation', {{name: animation, time: 1.0}});
          setApiStatus(`playing ${{animation}}`);
        }} else if (action === 'talk') {{
          await godotPost('/load', {{id}});
          if (timeline) {{
            const data = await godotPost('/lipsync', {{path: timeline}});
            setApiStatus(`talking ${{id}} (${{data.cue_count || 0}} cues)`);
          }} else {{
            await godotPost('/speak', {{text: 'hello', value: 1.0}});
            setApiStatus(`fallback speak for ${{id}}`);
          }}
        }} else if (action === 'smile') {{
          await godotPost('/load', {{id}});
          await godotPost('/expression', {{joy: 0.7, close: 0.0}});
          setApiStatus(`expression applied to ${{id}}`);
        }} else if (action === 'export') {{
          await godotPost('/export-game-asset', {{id}});
          setApiStatus(`exported ${{id}}`);
        }}
      }} catch (error) {{
        setApiStatus(`error: ${{error.message}}`);
      }}
    }});
    applyFilters();
  </script>
</body>
</html>
"""


def load_batch_result(batch_path: Path, godot_lipsync_validation_path: Path | None = None) -> dict:
    batch_result = json.loads(batch_path.read_text(encoding="utf-8"))
    if godot_lipsync_validation_path:
        batch_result["godot_lipsync_validation"] = json.loads(
            godot_lipsync_validation_path.read_text(encoding="utf-8")
        )
    if batch_result.get("godot_lipsync_validation") and not batch_result.get("godot_lipsync_summary"):
        batch_result["godot_lipsync_summary"] = summarize_lipsync_validation(
            batch_result.get("godot_lipsync_validation", {})
        )
    return batch_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a review gallery for one person-factory batch.")
    parser.add_argument("batch_result", nargs="?", default="results/batch_person_factory_latest.json")
    parser.add_argument("output", nargs="?", default="outputs/batch/person_factory_gallery.html")
    parser.add_argument("--godot-lipsync-validation")
    parser.add_argument("--detail-mode", choices=["full", "compact"], default="full")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_path = Path(args.batch_result)
    output_path = Path(args.output)
    batch_result = load_batch_result(
        batch_path,
        Path(args.godot_lipsync_validation) if args.godot_lipsync_validation else None,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_gallery(batch_result, output_path, detail_mode=args.detail_mode), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
