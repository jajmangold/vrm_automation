from __future__ import annotations


PRESETS = {
    "wave": {
        "frames": [1, 24, 48, 72],
        "right_arm": [0, 45, -25, 0],
        "spine_lean": [0, 5, -5, 0],
        "leg_lift": True,
        "secondary_sway": [0, 8, -8, 0],
    },
    "cheerful_wave": {
        "frames": [1, 18, 36, 54, 72],
        "right_arm": [0, 58, 18, 52, 0],
        "spine_lean": [0, 7, 3, 6, 0],
        "leg_lift": True,
        "secondary_sway": [0, 10, -5, 9, 0],
    },
    "shy_bounce": {
        "frames": [1, 24, 48, 72],
        "right_arm": [0, 12, -8, 0],
        "spine_lean": [0, -4, 3, 0],
        "leg_lift": False,
        "secondary_sway": [0, 5, -5, 0],
    },
    "idle_turn": {
        "frames": [1, 24, 48, 72],
        "right_arm": [0, 10, -10, 0],
        "spine_lean": [0, 0, 0, 0],
        "spine_twist": [0, 10, -10, 0],
        "leg_lift": False,
        "secondary_sway": [0, 6, -6, 0],
    },
    "confident_point": {
        "frames": [1, 20, 44, 72],
        "right_arm": [0, 64, 58, 0],
        "spine_lean": [0, 3, 5, 0],
        "spine_twist": [0, -7, -5, 0],
        "leg_lift": False,
        "secondary_sway": [0, 5, 4, 0],
    },
    "talk_idle": {
        "frames": [1, 16, 32, 48, 64, 72],
        "right_arm": [0, 8, -4, 10, -6, 0],
        "spine_lean": [0, 1, -1, 1, -1, 0],
        "spine_twist": [0, -3, 2, -2, 3, 0],
        "leg_lift": False,
        "secondary_sway": [0, 2, -2, 2, -2, 0],
    },
    "look_around": {
        "frames": [1, 18, 36, 54, 72],
        "right_arm": [0, 6, -6, 4, 0],
        "spine_lean": [0, 0, 0, 0, 0],
        "spine_twist": [0, 12, -12, 8, 0],
        "leg_lift": False,
        "secondary_sway": [0, 4, -4, 3, 0],
    },
    "thinking_idle": {
        "frames": [1, 18, 36, 54, 72],
        "right_arm": [0, 8, 12, 6, 0],
        "right_arm_z": [0, 0, 4, 0, 0],
        "left_arm_z": [-18, -12, -10, -14, -18],
        "spine_lean": [0, -2, -3, -1, 0],
        "spine_twist": [0, 3, -3, 2, 0],
        "head_pitch": [0, -4, -7, -3, 0],
        "head_yaw": [0, 4, -5, 3, 0],
        "leg_lift": False,
        "secondary_sway": [0, 3, -3, 2, 0],
        "tags": ["thinking", "idle", "subtle"],
        "review_frames": [18, 36, 72],
    },
    "listening_nod": {
        "frames": [1, 14, 28, 42, 56, 72],
        "right_arm": [0, 4, 2, 5, 3, 0],
        "left_arm_z": [-18, -16, -18, -15, -18, -18],
        "spine_lean": [0, 1, -1, 1, -1, 0],
        "spine_twist": [0, 2, 0, -2, 1, 0],
        "head_pitch": [0, 5, -2, 6, -1, 0],
        "head_yaw": [0, -2, 1, 2, -1, 0],
        "leg_lift": False,
        "secondary_sway": [0, 2, -1, 2, -2, 0],
        "tags": ["listening", "nod", "dialogue"],
        "review_frames": [14, 42, 72],
    },
    "present_explain": {
        "frames": [1, 16, 32, 48, 64, 72],
        "right_arm": [0, 48, 36, 58, 30, 0],
        "right_arm_z": [0, 10, -6, 12, -4, 0],
        "left_arm_z": [-18, -28, -20, -30, -18, -18],
        "spine_lean": [0, 2, 0, 3, 1, 0],
        "spine_twist": [0, -6, 4, -8, 5, 0],
        "head_pitch": [0, -2, 1, -2, 1, 0],
        "head_yaw": [0, -4, 3, -5, 4, 0],
        "leg_lift": False,
        "secondary_sway": [0, 5, -3, 5, -2, 0],
        "tags": ["presenter", "explain", "dialogue"],
        "review_frames": [16, 48, 72],
    },
    "celebrate": {
        "frames": [1, 14, 28, 42, 56, 72],
        "right_arm": [0, 70, 52, 72, 44, 0],
        "right_arm_z": [0, 8, -8, 10, -6, 0],
        "left_arm": [0, 34, 24, 36, 18, 0],
        "left_arm_z": [-18, -6, -12, -4, -14, -18],
        "spine_lean": [0, 6, -3, 7, -2, 0],
        "spine_twist": [0, -5, 5, -7, 4, 0],
        "leg_lift": True,
        "secondary_sway": [0, 12, -10, 12, -8, 0],
        "tags": ["celebrate", "happy", "high-energy"],
        "review_frames": [14, 42, 72],
    },
    "turntable_review": {
        "frames": [1, 18, 36, 54, 72],
        "right_arm": [0, 0, 0, 0, 0],
        "left_arm_z": [-18, -18, -18, -18, -18],
        "spine_lean": [0, 0, 0, 0, 0],
        "spine_twist": [0, 18, 0, -18, 0],
        "head_yaw": [0, 8, 0, -8, 0],
        "leg_lift": False,
        "secondary_sway": [0, 5, 0, -5, 0],
        "tags": ["turntable", "review", "qa"],
        "review_frames": [18, 36, 54, 72],
    },
}


def animation_preset(name: str | None) -> dict:
    preset_name = (name or "wave").strip().lower().replace("-", "_")
    preset = PRESETS.get(preset_name, PRESETS["wave"]).copy()
    preset["name"] = preset_name if preset_name in PRESETS else "wave"
    preset["frames"] = list(preset["frames"])
    return preset


def preset_value(preset: dict, key: str, index: int, default: float = 0.0) -> float:
    values = preset.get(key)
    if not values:
        return default
    return float(values[min(index, len(values) - 1)])
