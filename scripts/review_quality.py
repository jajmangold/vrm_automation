from __future__ import annotations

from pathlib import PurePosixPath


MANUAL_ASSET_ISSUES = {
    "fedora-google": [
        {
            "flag": "known-weak-asset",
            "tag": "asset:weak",
            "penalty": 12,
            "note": "Fedora asset is visibly blocky in portrait QA; prefer replacement or manual approval.",
        },
        {
            "flag": "hat-low",
            "tag": "issue:hat-low",
            "penalty": 6,
            "note": "Fedora sits low over the face after current automatic hat anchor fit.",
        },
    ],
    "hard-hat-google": [
        {
            "flag": "hat-low",
            "tag": "issue:hat-low",
            "penalty": 6,
            "note": "Hard hat is usable but sits slightly low and should be manually reviewed.",
        }
    ],
    "glasses-jeremy": [
        {
            "flag": "glasses-large-low",
            "tag": "issue:glasses-large-low",
            "penalty": 12,
            "note": "Jeremy glasses read large/low on male portrait QA; keep for review until fit tuning is improved.",
        }
    ],
    "crown-quaternius": [
        {
            "flag": "hat-large",
            "tag": "issue:hat-large",
            "penalty": 7,
            "note": "Crown reads large/low in portrait QA; keep as review until tuned or replaced.",
        }
    ],
    "monocle-google": [
        {
            "flag": "needs-open-eye-review",
            "tag": "issue:open-eye-review",
            "penalty": 4,
            "note": "Monocle/glasses assets need an open-eye portrait frame because smile frames may hide the fit.",
        }
    ],
    "anon-mask-scott-marshall": [
        {
            "flag": "face-occluding-mask",
            "tag": "issue:face-occlusion",
            "penalty": 16,
            "note": "Anon mask fully occludes identity and facial expressions; require manual approval for speaking/person assets.",
        }
    ],
    "wizard-hat-google": [
        {
            "flag": "hat-tiny-hidden",
            "tag": "issue:hat-tiny-hidden",
            "penalty": 12,
            "note": "Wizard hat reads too small and hidden by hair in portrait QA; keep for review until fit tuning is improved.",
        }
    ],
}


def assess_review_quality(job: dict, report: dict) -> dict:
    tokens = _asset_tokens(job, report)
    category = _category(job, report)
    issues = []
    review_tags: set[str] = set()
    notes: list[str] = []

    if category == "head_face":
        review_tags.add("review:head-face")
    if category == "torso_back":
        review_tags.add("review:torso-back")
        notes.append("Use side/back QA frames for torso-back accessory fit review.")

    for asset_key, asset_issues in MANUAL_ASSET_ISSUES.items():
        if asset_key not in tokens:
            continue
        for issue in asset_issues:
            issues.append(dict(issue))
            review_tags.add(issue["tag"])
            notes.append(issue["note"])

    fit_metrics = report.get("external_outfit", {}).get("fit_check", {}).get("metrics", {})
    vertical_center_ratio = float(fit_metrics.get("vertical_center_ratio", 0) or 0)
    if category == "neck_chest" and "anchor:neck-chest-neck-loop" in tokens and vertical_center_ratio < 0.8:
        issue = {
            "flag": "neck-loop-low",
            "tag": "issue:neck-loop-low",
            "penalty": 12,
            "note": "Neck-loop accessory center is low in the render; review pendant placement before catalog promotion.",
        }
        issues.append(issue)
        review_tags.add(issue["tag"])
        notes.append(issue["note"])
    if category == "neck_chest" and "necktie-jeremy" in tokens and vertical_center_ratio > 0.8:
        issue = {
            "flag": "necktie-head-placement",
            "tag": "issue:necktie-head-placement",
            "penalty": 28,
            "note": "Necktie is landing on the forehead in portrait QA; keep as fix until collar anchoring is corrected.",
        }
        issues.append(issue)
        review_tags.add(issue["tag"])
        notes.append(issue["note"])

    if report.get("lipsync_animation", {}).get("enabled"):
        preferred_frame = _preferred_lipsync_frame(report.get("pose_renders", []))
    elif category == "torso_back":
        preferred_frame = _preferred_back_frame(report.get("pose_renders", []))
    else:
        preferred_frame = _preferred_open_eye_frame(report.get("pose_renders", []))
    if preferred_frame:
        review_tags.add(f"frame:{_frame_tag(preferred_frame)}")
        if any(issue["flag"] == "needs-open-eye-review" for issue in issues):
            notes.append(f"Prefer {preferred_frame} for face accessory QA.")

    return {
        "qa_flags": [issue["flag"] for issue in issues],
        "review_tags": sorted(review_tags),
        "review_notes": notes,
        "review_issues": issues,
        "preferred_review_frame": preferred_frame,
    }


def _asset_tokens(job: dict, report: dict) -> str:
    metadata = job.get("metadata", {})
    env = job.get("environment", {})
    parts = [
        job.get("id", ""),
        " ".join(metadata.get("tags", [])),
        metadata.get("display_name", ""),
        metadata.get("notes", ""),
        env.get("OUTFIT_MODEL", ""),
        env.get("OUTFIT_CATEGORY", ""),
    ]
    classification = report.get("external_outfit", {}).get("classification", {})
    parts.extend(
        [
            classification.get("source_label", ""),
            classification.get("category", ""),
        ]
    )
    normalized = " ".join(str(part) for part in parts if part).lower()
    return normalized.replace("_", "-").replace("/", " ")


def _category(job: dict, report: dict) -> str:
    category = (
        report.get("external_outfit", {}).get("classification", {}).get("category")
        or job.get("environment", {}).get("OUTFIT_CATEGORY")
        or ""
    )
    return str(category).replace("-", "_")


def _preferred_open_eye_frame(render_paths: list[str]) -> str:
    portrait_frames = [PurePosixPath(path).name for path in render_paths if "portrait" in path]
    for preferred in ("pose_portrait_0072.png", "pose_portrait_0048.png", "pose_portrait_0001.png"):
        if any(frame.endswith(preferred.removeprefix("pose_")) or frame == preferred for frame in portrait_frames):
            return preferred
    return portrait_frames[-1] if portrait_frames else ""


def _preferred_back_frame(render_paths: list[str]) -> str:
    back_frames = [PurePosixPath(path).name for path in render_paths if "pose_back" in path]
    for preferred in ("pose_back_0072.png", "pose_back_0048.png", "pose_back_0024.png"):
        if preferred in back_frames:
            return preferred
    return back_frames[-1] if back_frames else _preferred_open_eye_frame(render_paths)


def _preferred_lipsync_frame(render_paths: list[str]) -> str:
    portrait_frames = [PurePosixPath(path).name for path in render_paths if "portrait" in path]
    for preferred in (
        "pose_portrait_0009.png",
        "pose_portrait_0006.png",
        "pose_portrait_0003.png",
        "pose_portrait_0012.png",
        "pose_portrait_0016.png",
        "pose_portrait_0024.png",
    ):
        if any(frame.endswith(preferred.removeprefix("pose_")) or frame == preferred for frame in portrait_frames):
            return preferred
    return _preferred_open_eye_frame(render_paths)


def _frame_tag(preferred_frame: str) -> str:
    stem = preferred_frame.removesuffix(".png")
    if stem.startswith("pose_"):
        stem = stem.removeprefix("pose_")
    return stem.replace("_", "-")
