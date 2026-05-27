from __future__ import annotations

from pathlib import Path

from scripts.review_quality import assess_review_quality


def workspace_path(path: str, root: Path) -> Path:
    if path.startswith("/workspace/"):
        return root / path.removeprefix("/workspace/")
    return Path(path)


def grade_for_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def priority_for_grade(grade: str) -> str:
    return {
        "A": "ship",
        "B": "review",
        "C": "fix",
        "D": "reject",
    }[grade]


def is_benign_neck_chest_depth_warning(category: str, warnings: list[str], metrics: dict) -> bool:
    if category != "neck_chest":
        return False
    allowed_warnings = {
        "outfit-depth-large",
        "outfit-floating-forward",
        "outfit-buried-deep",
        "outfit-surface-penetration",
    }
    if not warnings or not set(warnings).issubset(allowed_warnings):
        return False
    width_ratio = float(metrics.get("width_ratio", 0) or 0)
    height_ratio = float(metrics.get("height_ratio", 0) or 0)
    vertical_center_ratio = float(metrics.get("vertical_center_ratio", 0) or 0)
    surface_gap_ratio = float(metrics.get("surface_gap_ratio", 0) or 0)
    buried_depth_ratio = float(metrics.get("buried_depth_ratio", 0) or 0)
    surface_penetration_ratio = float(metrics.get("surface_penetration_ratio", 0) or 0)
    return (
        0.025 <= width_ratio <= 0.45
        and 0.035 <= height_ratio <= 0.32
        and 0.58 <= vertical_center_ratio <= 0.86
        and surface_gap_ratio <= 0.2
        and buried_depth_ratio <= 0.15
        and surface_penetration_ratio <= 0.22
    )


def score_job(job: dict, report: dict, root: Path) -> dict:
    score = 100
    flags: list[str] = []
    env = job.get("environment", {})
    review_quality = assess_review_quality(job, report)

    def penalize(points: int, flag: str) -> None:
        nonlocal score
        score -= points
        flags.append(flag)

    if job.get("status") != "ok" or report.get("status") != "ok":
        penalize(35, "job-not-ok")
    if report.get("errors"):
        penalize(30, "report-errors")

    output_glb = workspace_path(env.get("OUTPUT_GLB", ""), root) if env.get("OUTPUT_GLB") else None
    if not output_glb or not output_glb.exists():
        penalize(25, "missing-glb")

    expected_render_count = expected_renders(env)
    render_paths = report.get("pose_renders", [])
    existing_renders = [path for path in render_paths if workspace_path(path, root).exists()]
    if len(existing_renders) < expected_render_count:
        penalize(4 * (expected_render_count - len(existing_renders)), "missing-renders")

    fit_check = report.get("external_outfit", {}).get("fit_check", {})
    category = report.get("external_outfit", {}).get("classification", {}).get("category") or env.get("OUTFIT_CATEGORY")
    category = str(category).replace("-", "_")
    complete_torso_back_review = (
        category == "torso_back"
        and _has_render_angles(env, {"side", "back"})
        and len(existing_renders) >= expected_render_count
    )
    warnings = fit_check.get("warnings", [])
    metrics = fit_check.get("metrics", {})
    benign_neck_chest_depth_warning = is_benign_neck_chest_depth_warning(category, warnings, metrics)
    if fit_check.get("status") not in (None, "ok") and not benign_neck_chest_depth_warning:
        penalize(10 if complete_torso_back_review else 18, f"fit-{fit_check.get('status')}")
    if warnings:
        if not benign_neck_chest_depth_warning:
            warning_penalty = min(10, 3 * len(warnings)) if complete_torso_back_review else min(20, 5 * len(warnings))
            penalize(warning_penalty, "fit-warnings")

    width_ratio = float(metrics.get("width_ratio", 0) or 0)
    height_ratio = float(metrics.get("height_ratio", 0) or 0)
    if category == "head_face" and width_ratio > 0.35:
        penalize(12, "face-accessory-wide")
    if category == "head_face" and height_ratio > 0.18:
        penalize(8, "face-accessory-tall")
    if category in {"torso_back", "neck_chest"} and width_ratio > 0.9:
        penalize(10, "accessory-wide")

    matched_bones = report.get("matched_bones", {})
    for role in ("spine", "head", "left_arm", "right_arm"):
        if not matched_bones.get(role):
            penalize(8, f"missing-bone-{role}")

    expression = report.get("expression_animation", {})
    keyed_expressions = set(expression.get("keyed", []))
    required_expressions = {"blink"} if expression.get("preset") == "neutral" else {"smile", "blink"}
    if not required_expressions.issubset(keyed_expressions):
        penalize(8, "missing-expression-keys")

    exports = report.get("exports", {})
    if env.get("EXPORT_GLB", "1") == "1" and not exports.get("glb"):
        penalize(16, "glb-export-not-confirmed")

    for issue in review_quality["review_issues"]:
        penalize(int(issue.get("penalty", 0)), issue["flag"])

    score = max(0, min(100, score))
    grade = grade_for_score(score)
    review_priority = priority_for_grade(grade)
    if complete_torso_back_review and fit_check.get("status") not in (None, "ok") and review_priority == "ship":
        review_priority = "review"
    return {
        "qa_score": score,
        "qa_grade": grade,
        "qa_flags": flags,
        "review_tags": review_quality["review_tags"],
        "review_notes": review_quality["review_notes"],
        "preferred_review_frame": review_quality["preferred_review_frame"],
        "review_priority": review_priority,
        "expected_render_count": expected_render_count,
        "actual_render_count": len(existing_renders),
    }


def expected_renders(env: dict) -> int:
    if str(env.get("RENDER_POSE_STILLS", "1")) != "1":
        return 0
    angles = [item.strip() for item in str(env.get("RENDER_ANGLES", "front")).split(",") if item.strip()]
    frames = [item.strip() for item in str(env.get("RENDER_POSE_FRAMES", "")).split(",") if item.strip()]
    if not frames:
        frames = ["1", "24", "48", "72"]
    return len(angles or ["front"]) * len(frames)


def _has_render_angles(env: dict, required_angles: set[str]) -> bool:
    angles = {item.strip() for item in str(env.get("RENDER_ANGLES", "front")).split(",") if item.strip()}
    return required_angles.issubset(angles)
