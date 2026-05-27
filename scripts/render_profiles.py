from __future__ import annotations

from pathlib import Path


RENDER_PROFILES = {
    "standard": {
        "render_angles": "front,portrait",
        "render_pose_frames": "1,9,24",
        "render_width": "640",
        "render_height": "960",
    },
    "standard_lipsync": {
        "render_angles": "front,portrait",
        "render_pose_frames": "1,3,6,9,12,16,24",
        "render_width": "640",
        "render_height": "960",
    },
    "fast_lipsync": {
        "render_angles": "portrait",
        "render_pose_frames": "3,9,16",
        "render_width": "640",
        "render_height": "960",
    },
    "rough_lipsync": {
        "render_angles": "portrait",
        "render_pose_frames": "9",
        "render_width": "512",
        "render_height": "768",
    },
    "thumbnail_lipsync": {
        "render_angles": "portrait",
        "render_pose_frames": "1",
        "render_compact_arms": "1",
        "render_portrait_lens": "135",
        "render_review_pose_version": "3",
        "render_width": "384",
        "render_height": "576",
    },
    "control_lipsync": {
        "render_angles": "portrait",
        "render_pose_frames": "9",
        "render_pose_stills": "0",
        "render_width": "384",
        "render_height": "576",
    },
}


def render_defaults(profile: str = "auto", *, has_lipsync: bool = False) -> dict[str, str]:
    selected = profile
    if profile == "auto":
        selected = "standard_lipsync" if has_lipsync else "standard"
    if selected not in RENDER_PROFILES:
        raise ValueError(f"unknown render profile: {profile}")
    return dict(RENDER_PROFILES[selected])


def clear_pose_render_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    removed = []
    for path in sorted(output_dir.glob("pose_*.png")):
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed
