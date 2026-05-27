from __future__ import annotations

import json
import sys
from pathlib import Path


VISEME_RULES = {
    "aa": ("fcl_mth_a", "mouth_a", "mth_a"),
    "ih": ("fcl_mth_i", "mouth_i", "mth_i"),
    "ou": ("fcl_mth_u", "mouth_u", "mth_u"),
    "ee": ("fcl_mth_e", "mouth_e", "mth_e"),
    "oh": ("fcl_mth_o", "mouth_o", "mth_o"),
}

EXPRESSION_RULES = {
    "blink": ("eye_close", "blink"),
    "blink_l": ("eye_close_l", "blink_l"),
    "blink_r": ("eye_close_r", "blink_r"),
    "happy": ("all_joy", "joy", "fun"),
    "angry": ("all_angry", "angry"),
    "sad": ("all_sorrow", "sorrow", "sad"),
    "surprised": ("all_surprised", "surprised"),
}

VISEME_ALIASES = {
    "a": "aa",
    "aa": "aa",
    "i": "ih",
    "ih": "ih",
    "u": "ou",
    "ou": "ou",
    "e": "ee",
    "ee": "ee",
    "o": "oh",
    "oh": "oh",
    "rest": "rest",
    "sil": "rest",
}


def normalized(value: str) -> str:
    return value.lower().replace(".", "_").replace("-", "_")


def find_shape(shape_keys: dict[str, list[str]], needles: tuple[str, ...]) -> tuple[str, str] | None:
    for mesh_name, keys in shape_keys.items():
        for key in keys:
            label = normalized(key)
            if any(needle in label for needle in needles):
                return mesh_name, key
    return None


def build_mapping(shape_keys: dict[str, list[str]], rules: dict[str, tuple[str, ...]]) -> dict:
    mapping = {}
    for canonical, needles in rules.items():
        found = find_shape(shape_keys, needles)
        if found:
            mesh_name, shape = found
            mapping[canonical] = {"mesh": mesh_name, "shape": shape}
    return mapping


def build_face_profile(character_id: str, shape_keys: dict[str, list[str]]) -> dict:
    visemes = build_mapping(shape_keys, VISEME_RULES)
    expressions = build_mapping(shape_keys, EXPRESSION_RULES)
    viseme_count = len(visemes)
    expression_count = len(expressions)
    grade = "A" if viseme_count >= 5 and expression_count >= 3 else "B" if viseme_count >= 5 else "C"
    return {
        "schema": "vrm-person-factory.face-profile.v1",
        "character_id": character_id,
        "shape_key_count": sum(len(keys) for keys in shape_keys.values()),
        "shape_keys": shape_keys,
        "visemes": visemes,
        "expressions": expressions,
        "quality": {
            "grade": grade,
            "viseme_count": viseme_count,
            "expression_count": expression_count,
            "missing_visemes": [name for name in VISEME_RULES if name not in visemes],
            "missing_expressions": [name for name in EXPRESSION_RULES if name not in expressions],
        },
    }


def viseme_payload(profile: dict, viseme: str, value: float) -> dict[str, float]:
    canonical = VISEME_ALIASES.get(viseme.lower(), viseme.lower())
    payload = {entry["shape"]: 0.0 for entry in profile.get("visemes", {}).values()}
    if canonical == "rest":
        return payload
    entry = profile.get("visemes", {}).get(canonical)
    if entry:
        payload[entry["shape"]] = value
    return payload


def main() -> None:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2] if len(sys.argv) > 2 else "results/face_profile.json")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    shape_keys = data.get("shape_keys", {})
    profile = build_face_profile(data.get("id", input_path.stem), shape_keys)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"path": str(output_path), "quality": profile["quality"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
