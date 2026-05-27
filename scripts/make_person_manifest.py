from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.asset_classifier import classify_asset
    from scripts.facial_presets import facial_preset_for_animation
except ModuleNotFoundError:
    from asset_classifier import classify_asset
    from facial_presets import facial_preset_for_animation


ACCESSORIES = [
    {
        "key": "backpack",
        "outfit_model": "/workspace/input/outfits/poly_pizza/backpack_quaternius.glb",
        "category": "torso_back",
        "tags": ["travel", "backpack", "full-body"],
        "role": "scout",
    },
    {
        "key": "bag",
        "outfit_model": "/workspace/input/outfits/poly_pizza/bag_quaternius.glb",
        "category": "torso_back",
        "tags": ["student", "bag", "full-body"],
        "role": "student",
    },
    {
        "key": "necklace",
        "outfit_model": "/workspace/input/outfits/poly_pizza/necklace_quaternius.glb",
        "category": "neck_chest",
        "tags": ["portrait", "necklace", "facial"],
        "role": "host",
    },
    {
        "key": "glasses",
        "outfit_model": "/workspace/input/outfits/poly_pizza/pixel_glasses_ipoly3d.glb",
        "category": "head_face",
        "tags": ["glasses", "face", "expressive"],
        "role": "streamer",
    },
]


BASE_MODELS = [
    {
        "key": "female",
        "model_path": "/workspace/input/base_models/vroid_hairsample_female_cc0.vrm",
        "tags": ["base:female-hairsample"],
    },
    {
        "key": "male",
        "model_path": "/workspace/input/base_models/vroid_hairsample_male_cc0.vrm",
        "tags": ["base:male-hairsample"],
    },
]


ANIMATIONS = [
    {"preset": "cheerful_wave", "tags": ["cheerful", "wave"], "verb": "greets"},
    {"preset": "talk_idle", "tags": ["talk-idle", "dialogue"], "verb": "talks"},
    {"preset": "look_around", "tags": ["look-around", "ambient"], "verb": "scans"},
    {"preset": "confident_point", "tags": ["point", "guide"], "verb": "points"},
    {"preset": "present_explain", "tags": ["presenter", "explain", "dialogue"], "verb": "explains"},
    {"preset": "thinking_idle", "tags": ["thinking", "idle", "subtle"], "verb": "thinks"},
    {"preset": "listening_nod", "tags": ["listening", "nod", "dialogue"], "verb": "listens"},
    {"preset": "celebrate", "tags": ["celebrate", "happy"], "verb": "celebrates"},
    {"preset": "turntable_review", "tags": ["turntable", "review"], "verb": "reviews"},
    {"preset": "shy_bounce", "tags": ["shy", "subtle"], "verb": "waits"},
    {"preset": "idle_turn", "tags": ["idle-turn", "calm"], "verb": "turns"},
    {"preset": "wave", "tags": ["wave", "friendly"], "verb": "waves"},
]


DEFAULT_INCLUDE_QUALITIES = {"ship"}
REVIEW_INCLUDE_QUALITIES = {"ship", "review", "fix"}


NAMES = [
    "Ari",
    "Mina",
    "Nora",
    "Rin",
    "Kei",
    "Sora",
    "Yuna",
    "Tao",
    "Lena",
    "Mika",
    "Jules",
    "Iris",
    "Theo",
    "Nova",
    "Remy",
    "Aya",
    "Kira",
    "Sol",
    "Emi",
    "Rook",
    "Zara",
    "Niko",
    "Vera",
    "Pax",
    "Lio",
    "Miri",
    "Cato",
    "June",
    "Nyx",
    "Oli",
    "Tess",
    "Rae",
]


def slug(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in cleaned.split("-") if part)


def workspace_path(path: str) -> str:
    if path.startswith("/workspace/"):
        return path
    return f"/workspace/{path}"


def load_accessories(config_path: Path, include_qualities: set[str] | None = None) -> list[dict]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    allowed_qualities = include_qualities or DEFAULT_INCLUDE_QUALITIES
    accessories = []
    for asset in config["assets"]:
        quality = asset_quality(asset)
        if quality not in allowed_qualities:
            continue
        key = slug(asset["id"].replace("poly-pizza-", ""))
        license_tag = "license:cc0" if asset["license"] == "CC0 1.0" else "license:cc-by-3.0"
        attribution_tag = "attribution:required" if asset.get("attribution_required") else "attribution:not-required"
        category = asset.get("category") or classify_asset(asset["title"], asset["output_path"]).get("category")
        anchor_calibration = asset.get("anchor_calibration") or {}
        calibration_tags = []
        if anchor_calibration:
            calibration_tags.append("calibration:image-guided-anchor")
            anchor_name = anchor_calibration.get("anchor_name")
            if anchor_name:
                calibration_tags.append(f"anchor:{slug(anchor_name)}")
            validation = anchor_calibration.get("validation") or {}
            validation_status = validation.get("status")
            if validation_status:
                calibration_tags.append(f"anchor-validation:{slug(str(validation_status))}")
        accessories.append(
            {
                "key": key,
                "outfit_model": workspace_path(asset["output_path"]),
                "category": category,
                "fit_overrides": asset.get("fit_overrides", {}),
                "anchor_calibration": anchor_calibration,
                "tags": [
                    key,
                    category.replace("_", "-"),
                    license_tag,
                    attribution_tag,
                    f"quality:{quality}",
                    f"creator:{slug(asset['creator'])}",
                    *calibration_tags,
                ],
                "role": asset.get("role", key),
                "title": asset["title"],
                "source_url": asset["source_url"],
                "license": asset["license"],
                "creator": asset["creator"],
                "quality": quality,
                "quality_notes": asset_quality_notes(asset),
            }
        )
    return accessories


def asset_quality(asset: dict) -> str:
    quality = asset.get("quality", "ship")
    if isinstance(quality, dict):
        return quality.get("status", "ship")
    return str(quality)


def asset_quality_notes(asset: dict) -> list[str]:
    quality = asset.get("quality", {})
    if isinstance(quality, dict):
        notes = quality.get("notes", [])
        if isinstance(notes, str):
            return [notes]
        return list(notes)
    return []


def job_for_index(index: int, accessories: list[dict] | None = None) -> dict:
    pool = accessories or ACCESSORIES
    accessory = pool[index % len(pool)]
    animation = ANIMATIONS[(index // len(pool)) % len(ANIMATIONS)]
    base_model = BASE_MODELS[(index // len(pool)) % len(BASE_MODELS)]
    name = NAMES[index % len(NAMES)]
    facial_preset = facial_preset_for_animation(animation["preset"])
    suffix = f"{base_model['key']}-{accessory['key']}-{animation['preset'].replace('_', '-')}"
    job_id = f"gen-{index + 1:03d}-{suffix}"
    display_name = f"{name} {animation['verb'].title()}"
    job = {
        "id": job_id,
        "display_name": display_name,
        "persona": f"{accessory['role']} character who {animation['verb']} on command",
        "model_path": base_model["model_path"],
        "outfit_model": accessory["outfit_model"],
        "category": accessory["category"],
        "animation_preset": animation["preset"],
        "facial_preset": facial_preset,
        "render_angles": render_angles_for_category(accessory["category"]),
        "render_pose_frames": render_frames_for_facial_preset(facial_preset),
        "license": accessory.get("license"),
        "source_url": accessory.get("source_url"),
        "creator": accessory.get("creator"),
        "tags": [
            "generated",
            "controllable",
            *base_model["tags"],
            *accessory["tags"],
            *animation["tags"],
            f"face:{facial_preset.replace('_', '-')}",
        ],
        "notes": f"Generated control candidate {index + 1}: {accessory['key']} accessory with {animation['preset']} motion.",
    }
    for key, value in accessory.get("fit_overrides", {}).items():
        job[f"outfit_{key}"] = value
    return job


def render_angles_for_category(category: str) -> str:
    if category == "torso_back":
        return "front,side,back,portrait"
    return "front,portrait"


def render_frames_for_facial_preset(facial_preset: str) -> str:
    if facial_preset in {"talking_soft", "talking_wide"}:
        return "8,18,29,40,72"
    if facial_preset == "shy":
        return "22,54,72"
    if facial_preset == "surprised":
        return "18,36,72"
    return "24,36,72"


def build_manifest(count: int, accessories: list[dict] | None = None, start_index: int = 0) -> dict:
    return {
        "defaults": {
            "model_path": "/workspace/input/base_models/vroid_hairsample_female_cc0.vrm",
            "render_angles": "front,portrait",
            "render_pose_frames": "24,72",
            "render_pose_stills": "1",
            "render_width": "640",
            "render_height": "960",
            "export_blend": "0",
            "export_glb": "1",
            "export_vrm": "0",
            "cache_base_scenes": "1",
        },
        "jobs": [job_for_index(index, accessories=accessories) for index in range(start_index, start_index + count)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a batch manifest for controllable VRM person candidates.")
    parser.add_argument("count", nargs="?", type=int, default=24)
    parser.add_argument("output_path", nargs="?", default="config/person_factory.generated.json")
    parser.add_argument("asset_config_path", nargs="?", default="config/poly_pizza_assets.json")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument(
        "--include-quality",
        default=",".join(sorted(DEFAULT_INCLUDE_QUALITIES)),
        help="Comma-separated asset quality statuses to include. Default: ship.",
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="Shortcut for --include-quality ship,review,fix.",
    )
    args = parser.parse_args()

    include_qualities = REVIEW_INCLUDE_QUALITIES if args.include_review else {
        item.strip() for item in args.include_quality.split(",") if item.strip()
    }
    output_path = Path(args.output_path)
    asset_config_path = Path(args.asset_config_path)
    accessories = load_accessories(asset_config_path, include_qualities=include_qualities) if asset_config_path.exists() else ACCESSORIES
    manifest = build_manifest(args.count, accessories=accessories, start_index=args.start_index)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(output_path),
                "jobs": len(manifest["jobs"]),
                "start_index": args.start_index,
                "include_qualities": sorted(include_qualities),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
