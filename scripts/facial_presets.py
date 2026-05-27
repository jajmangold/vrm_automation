from __future__ import annotations


ANIMATION_TO_FACIAL_PRESET = {
    "talk_idle": "talking_soft",
    "shy_bounce": "shy",
    "confident_point": "happy",
    "present_explain": "talking_soft",
    "thinking_idle": "neutral",
    "listening_nod": "neutral",
    "celebrate": "happy",
    "turntable_review": "neutral",
    "cheerful_wave": "happy",
    "wave": "happy",
    "look_around": "neutral",
    "idle_turn": "neutral",
}


PRESETS = {
    "neutral": {
        "tracks": [
            {"kind": "expression", "name": "blink", "keys": [(1, 0.0), (36, 1.0), (38, 0.0), (72, 0.0)]}
        ]
    },
    "happy": {
        "tracks": [
            {"kind": "expression", "name": "happy", "keys": [(1, 0.0), (18, 0.0), (24, 0.8), (48, 0.35), (72, 0.0)]},
            {"kind": "expression", "name": "blink", "keys": [(1, 0.0), (34, 0.0), (36, 1.0), (38, 0.0), (72, 0.0)]},
        ]
    },
    "shy": {
        "tracks": [
            {"kind": "expression", "name": "happy", "keys": [(1, 0.0), (20, 0.28), (48, 0.18), (72, 0.0)]},
            {"kind": "expression", "name": "blink", "keys": [(1, 0.0), (22, 1.0), (25, 0.0), (54, 1.0), (57, 0.0)]},
        ]
    },
    "surprised": {
        "tracks": [
            {"kind": "expression", "name": "surprised", "keys": [(1, 0.0), (18, 1.0), (42, 0.35), (72, 0.0)]},
            {"kind": "viseme", "name": "oh", "keys": [(1, 0.0), (18, 0.75), (36, 0.15), (72, 0.0)]},
        ]
    },
    "talking_soft": {
        "tracks": [
            {"kind": "expression", "name": "happy", "keys": [(1, 0.0), (12, 0.22), (64, 0.18), (72, 0.0)]},
            {"kind": "expression", "name": "blink", "keys": [(1, 0.0), (40, 1.0), (42, 0.0), (72, 0.0)]},
            {"kind": "viseme", "name": "aa", "keys": [(1, 0.0), (8, 0.45), (12, 0.0)]},
            {"kind": "viseme", "name": "ih", "keys": [(12, 0.0), (18, 0.35), (22, 0.0)]},
            {"kind": "viseme", "name": "ou", "keys": [(22, 0.0), (29, 0.32), (33, 0.0)]},
            {"kind": "viseme", "name": "ee", "keys": [(33, 0.0), (42, 0.38), (46, 0.0)]},
            {"kind": "viseme", "name": "oh", "keys": [(46, 0.0), (56, 0.34), (60, 0.0)]},
        ]
    },
    "talking_wide": {
        "tracks": [
            {"kind": "expression", "name": "happy", "keys": [(1, 0.0), (10, 0.35), (64, 0.28), (72, 0.0)]},
            {"kind": "expression", "name": "blink", "keys": [(1, 0.0), (38, 1.0), (40, 0.0), (72, 0.0)]},
            {"kind": "viseme", "name": "aa", "keys": [(1, 0.0), (7, 0.75), (12, 0.0)]},
            {"kind": "viseme", "name": "ih", "keys": [(12, 0.0), (18, 0.62), (23, 0.0)]},
            {"kind": "viseme", "name": "ou", "keys": [(23, 0.0), (30, 0.58), (36, 0.0)]},
            {"kind": "viseme", "name": "ee", "keys": [(36, 0.0), (45, 0.7), (50, 0.0)]},
            {"kind": "viseme", "name": "oh", "keys": [(50, 0.0), (59, 0.68), (64, 0.0)]},
        ]
    },
}


def normalize_preset_name(name: str | None) -> str:
    preset_name = (name or "happy").strip().lower().replace("-", "_")
    return preset_name if preset_name in PRESETS else "happy"


def facial_preset_for_animation(animation_name: str | None) -> str:
    animation = (animation_name or "wave").strip().lower().replace("-", "_")
    return ANIMATION_TO_FACIAL_PRESET.get(animation, "happy")


def plan_facial_animation(profile: dict, preset_name: str | None, frame_end: int = 72) -> dict:
    preset = normalize_preset_name(preset_name)
    expressions = profile.get("expressions", {})
    visemes = profile.get("visemes", {})
    keyframes = []
    missing_expressions = set()
    missing_visemes = set()
    keyed_expressions = set()
    keyed_visemes = set()

    for track in PRESETS[preset]["tracks"]:
        kind = track["kind"]
        name = track["name"]
        lookup = visemes if kind == "viseme" else expressions
        entry = lookup.get(name)
        if not entry:
            if kind == "viseme":
                missing_visemes.add(name)
            else:
                missing_expressions.add(name)
            continue
        for frame, value in track["keys"]:
            keyframes.append(
                {
                    "kind": kind,
                    "name": name,
                    "mesh": entry["mesh"],
                    "shape": entry["shape"],
                    "frame": min(int(frame), int(frame_end)),
                    "value": float(value),
                }
            )
        if kind == "viseme":
            keyed_visemes.add(name)
        else:
            keyed_expressions.add(name)

    keyed = sorted(keyed_expressions)
    if "happy" in keyed_expressions:
        keyed.append("smile")
    if "blink" in keyed_expressions:
        keyed.append("blink")

    return {
        "preset": preset,
        "keyframes": sorted(keyframes, key=lambda item: (item["frame"], item["shape"])),
        "keyframe_count": len(keyframes),
        "keyed": sorted(set(keyed)),
        "keyed_expressions": sorted(keyed_expressions),
        "keyed_visemes": sorted(keyed_visemes),
        "missing": sorted(missing_expressions | missing_visemes),
        "missing_expressions": sorted(missing_expressions),
        "missing_visemes": sorted(missing_visemes),
    }
