from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_ACTIVE_VISEMES = ("aa", "ee", "ih", "oh", "ou")
AUDIO_DERIVED_SOURCE_MODES = {"rhubarb", "phoneme-events", "phoneme_events", "musetalk", "audio2face", "arkit"}


def workspace_path(value: str | Path | None, root: Path = ROOT) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("/workspace/"):
        return root / text.removeprefix("/workspace/")
    return Path(text)


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _int_or_zero(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _ordered_strings(values: Any) -> list[str]:
    output = []
    if not isinstance(values, list):
        return output
    for value in values:
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return output


def _source_metadata(timeline: dict[str, Any], cues: list[Any]) -> dict[str, Any]:
    source = timeline.get("source", {})
    source = source if isinstance(source, dict) else {}

    cue_phonemes = [
        str(cue.get("source_phoneme", "")).strip()
        for cue in cues
        if isinstance(cue, dict) and str(cue.get("source_phoneme", "")).strip()
    ]
    source_phonemes = _ordered_strings(source.get("unique_phonemes"))
    if not source_phonemes:
        source_phonemes = _ordered_strings(cue_phonemes)

    source_counts = source.get("phoneme_counts", {})
    phoneme_counts = {}
    if isinstance(source_counts, dict):
        phoneme_counts = {
            str(key): _int_or_zero(value)
            for key, value in source_counts.items()
            if str(key).strip()
        }
    if not phoneme_counts and cue_phonemes:
        phoneme_counts = {phoneme: cue_phonemes.count(phoneme) for phoneme in source_phonemes}

    event_count = _int_or_zero(source.get("event_count"))
    phoneme_count = _int_or_zero(source.get("phoneme_count"))
    if event_count == 0:
        event_count = len(cue_phonemes)
    if phoneme_count == 0:
        phoneme_count = sum(phoneme_counts.values()) if phoneme_counts else event_count

    return {
        "source_event_count": event_count,
        "source_phoneme_count": phoneme_count,
        "source_input_mode": str(source.get("input_mode", "") or ""),
        "source_text": str(source.get("text", "") or ""),
        "source_schema": str(source.get("source_schema", "") or ""),
        "source_path": str(source.get("source_path", "") or ""),
        "source_unique_phonemes": source_phonemes,
        "source_phoneme_counts": phoneme_counts,
    }


def _ordered_visemes(values: set[str] | list[str]) -> list[str]:
    seen = {str(value).strip() for value in values if str(value).strip()}
    ordered = [viseme for viseme in EXPECTED_ACTIVE_VISEMES if viseme in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered


def _source_mode(timeline: dict[str, Any]) -> str:
    source = timeline.get("source", {})
    if not isinstance(source, dict):
        return "unknown"
    return str(source.get("mode") or "unknown").strip() or "unknown"


def _alignment(source_mode: str) -> str:
    normalized = source_mode.lower().replace("_", "-")
    if normalized in AUDIO_DERIVED_SOURCE_MODES:
        return "audio-derived"
    if normalized in {"text", "stt-text"}:
        return "text-estimate"
    return "unknown"


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def analyze_lipsync_timeline(
    timeline: dict[str, Any] | None,
    *,
    expected_active_visemes: tuple[str, ...] = EXPECTED_ACTIVE_VISEMES,
) -> dict[str, Any]:
    timeline = timeline if isinstance(timeline, dict) else {}
    cues = timeline.get("cues", [])
    cues = cues if isinstance(cues, list) else []
    expressions = timeline.get("expressions", [])
    expressions = expressions if isinstance(expressions, list) else []
    source_mode = _source_mode(timeline)
    alignment = _alignment(source_mode)
    source_metadata = _source_metadata(timeline, cues)

    issues: set[str] = set()
    warnings: set[str] = set()
    viseme_counts: dict[str, int] = {}
    active_visemes: set[str] = set()
    invalid_cue_count = 0
    non_positive_duration_count = 0
    overlap_count = 0
    out_of_bounds_count = 0
    max_gap = 0.0
    timeline_end = 0.0
    previous_end = 0.0

    declared_duration = _float_or_none(timeline.get("duration"))
    if declared_duration is None:
        declared_duration = 0.0
        warnings.add("missing-duration")
    elif declared_duration <= 0 and cues:
        issues.add("invalid-duration")

    for cue in cues:
        if not isinstance(cue, dict):
            invalid_cue_count += 1
            continue
        start = _float_or_none(cue.get("time", 0.0))
        duration = _float_or_none(cue.get("duration", 0.0))
        viseme = str(cue.get("viseme", "")).strip()
        if start is None or duration is None or start < 0:
            invalid_cue_count += 1
            continue
        if duration <= 0:
            non_positive_duration_count += 1
        if start < previous_end - 0.001:
            overlap_count += 1
        elif start > previous_end:
            max_gap = max(max_gap, start - previous_end)
        end = max(start + max(duration, 0.0), start)
        previous_end = max(previous_end, end)
        timeline_end = max(timeline_end, end)
        if declared_duration > 0 and end > declared_duration + 0.05:
            out_of_bounds_count += 1
        if viseme:
            viseme_counts[viseme] = viseme_counts.get(viseme, 0) + 1
            if viseme != "rest":
                active_visemes.add(viseme)

    duration = max(float(declared_duration or 0.0), timeline_end)
    cue_count = len(cues)
    active_viseme_list = _ordered_visemes(active_visemes)
    missing_expected = [
        viseme
        for viseme in expected_active_visemes
        if viseme not in active_visemes
    ]

    if cue_count == 0:
        issues.add("empty-timeline")
    if invalid_cue_count:
        issues.add("invalid-cue")
    if non_positive_duration_count:
        issues.add("non-positive-cue-duration")
    if overlap_count:
        issues.add("overlapping-cues")
    if out_of_bounds_count:
        issues.add("cue-outside-duration")
    if duration <= 0:
        issues.add("invalid-duration")

    cue_density = round(cue_count / duration, 3) if duration > 0 else 0.0
    if cue_count and duration > 0:
        if cue_density < 2.0:
            issues.add("low-cue-density")
        elif cue_density > 22.0:
            warnings.add("high-cue-density")
    if max_gap > 0.35:
        issues.add("long-silent-gap")
    for viseme in missing_expected:
        warnings.add(f"missing-active-viseme:{viseme}")
    if duration >= 1.0 and len(active_visemes) < 2:
        warnings.add("low-active-viseme-variety")
    if not expressions:
        warnings.add("no-expression-overlays")
    if alignment == "text-estimate":
        warnings.add("text-estimate-source")
    elif alignment == "unknown":
        warnings.add("unknown-lipsync-source")

    score = 100
    score -= 18 * len(issues)
    score -= min(20, 4 * len(warnings))
    score -= min(10, overlap_count * 3)
    score -= min(10, invalid_cue_count * 3)
    score = max(0, min(100, score))

    status = "review" if issues else "ok"
    return {
        "status": status,
        "grade": _grade(score),
        "score": score,
        "issues": sorted(issues),
        "warnings": sorted(warnings),
        "source_mode": source_mode,
        "alignment": alignment,
        **source_metadata,
        "duration": round(duration, 3),
        "declared_duration": round(float(declared_duration or 0.0), 3),
        "cue_count": cue_count,
        "expression_count": len(expressions),
        "visemes": list(viseme_counts),
        "viseme_counts": viseme_counts,
        "active_visemes": active_viseme_list,
        "missing_expected_active_visemes": missing_expected,
        "cue_density_per_second": cue_density,
        "max_gap_seconds": round(max_gap, 3),
        "overlap_count": overlap_count,
        "invalid_cue_count": invalid_cue_count,
        "non_positive_duration_count": non_positive_duration_count,
        "out_of_bounds_count": out_of_bounds_count,
    }


def read_lipsync_timeline_path(path: str | Path | None, *, root: Path = ROOT) -> dict[str, Any]:
    resolved = workspace_path(path, root=root)
    if not resolved or not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def analyze_lipsync_timeline_path(path: str | Path | None, *, root: Path = ROOT) -> dict[str, Any]:
    timeline = read_lipsync_timeline_path(path, root=root)
    quality = analyze_lipsync_timeline(timeline)
    quality["path"] = str(path or "")
    if not timeline:
        quality["status"] = "review"
        quality["grade"] = "D"
        quality["score"] = 0
        quality["issues"] = sorted({*quality.get("issues", []), "missing-timeline"})
    return quality


def summarize_lipsync_validation(report: dict[str, Any] | None) -> dict[str, Any]:
    report = report if isinstance(report, dict) else {}
    checked = [item for item in report.get("checked", []) if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    grade_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    missing_active_counts: dict[str, int] = {}
    active_visemes: set[str] = set()
    cue_counts: list[int] = []
    durations: list[float] = []
    expression_counts: list[int] = []

    for item in checked:
        status = str(item.get("status", "review") or "review")
        status_counts[status] = status_counts.get(status, 0) + 1
        for issue in item.get("issues", []):
            issue = str(issue).strip()
            if issue:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1

        quality = item.get("lipsync_quality", {})
        quality = quality if isinstance(quality, dict) else {}
        grade = str(quality.get("grade", "") or "")
        if grade:
            grade_counts[grade] = grade_counts.get(grade, 0) + 1
        source = str(quality.get("source_mode", "") or "")
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1
        for warning in quality.get("warnings", []):
            warning = str(warning).strip()
            if warning:
                warning_counts[warning] = warning_counts.get(warning, 0) + 1
        for issue in quality.get("issues", []):
            issue = str(issue).strip()
            if issue:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        for viseme in quality.get("active_visemes", []):
            viseme = str(viseme).strip()
            if viseme and viseme != "rest":
                active_visemes.add(viseme)
        for viseme in quality.get("missing_expected_active_visemes", []):
            viseme = str(viseme).strip()
            if viseme:
                missing_active_counts[viseme] = missing_active_counts.get(viseme, 0) + 1
        cue_counts.append(_int_or_zero(quality.get("cue_count") or item.get("cue_count")))
        duration = _float_or_none(quality.get("duration"))
        if duration is not None:
            durations.append(duration)
        expression_counts.append(_int_or_zero(quality.get("expression_count")))

    checked_count = len(checked)
    ok_count = status_counts.get("ok", 0)
    review_count = checked_count - ok_count
    return {
        "checked_count": checked_count,
        "ok_count": ok_count,
        "review_count": review_count,
        "quality_review_count": int(report.get("quality_review_count", 0) or 0),
        "status_counts": dict(sorted(status_counts.items())),
        "grade_counts": dict(sorted(grade_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "active_visemes": _ordered_visemes(active_visemes),
        "missing_active_viseme_counts": dict(sorted(missing_active_counts.items())),
        "cue_count_min": min(cue_counts) if cue_counts else 0,
        "cue_count_max": max(cue_counts) if cue_counts else 0,
        "duration_min": round(min(durations), 3) if durations else 0.0,
        "duration_max": round(max(durations), 3) if durations else 0.0,
        "expression_count_min": min(expression_counts) if expression_counts else 0,
        "expression_count_max": max(expression_counts) if expression_counts else 0,
    }


def lipsync_quality_tags(quality: dict[str, Any] | None) -> list[str]:
    quality = quality if isinstance(quality, dict) else {}
    tags = [
        f"lipsync-quality:{quality.get('status', 'review')}",
        f"lipsync-grade:{quality.get('grade', 'D')}",
        f"lipsync-source:{quality.get('source_mode', 'unknown')}",
        f"lipsync-alignment:{quality.get('alignment', 'unknown')}",
    ]
    if int(quality.get("source_event_count", 0) or 0) > 0:
        tags.append(f"lipsync-source-events:{quality['source_event_count']}")
    if int(quality.get("source_phoneme_count", 0) or 0) > 0:
        tags.append(f"lipsync-phonemes:{quality['source_phoneme_count']}")
    tags.extend(f"lipsync-issue:{issue}" for issue in quality.get("issues", []) if issue)
    tags.extend(f"lipsync-warning:{warning}" for warning in quality.get("warnings", []) if warning)
    return tags
