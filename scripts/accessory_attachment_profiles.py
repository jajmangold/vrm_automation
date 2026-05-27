from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "accessory_attachment_profiles.json"


REQUIRED_PROFILE_KEYS = {
    "id",
    "category",
    "keywords",
    "anchors",
    "placement",
    "binding",
    "motion",
    "validation",
}


def load_attachment_profiles(path: Path | str = DEFAULT_PROFILE_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    validate_attachment_profiles(data)
    return data


def validate_attachment_profiles(data: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise ValueError("accessory attachment profiles must use schema_version 1")
    if not isinstance(data.get("bone_roles"), dict) or not data["bone_roles"]:
        raise ValueError("accessory attachment profiles require bone_roles")
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("accessory attachment profiles require at least one profile")

    seen_ids: set[str] = set()
    for profile in profiles:
        missing = REQUIRED_PROFILE_KEYS - set(profile)
        if missing:
            raise ValueError(f"profile {profile.get('id', '<unknown>')} missing keys: {sorted(missing)}")
        profile_id = profile["id"]
        if profile_id in seen_ids:
            raise ValueError(f"duplicate profile id: {profile_id}")
        seen_ids.add(profile_id)

        anchors = profile["anchors"]
        if "primary" not in anchors or "asset" not in anchors:
            raise ValueError(f"profile {profile_id} requires primary and asset anchors")
        if not profile["binding"].get("target_bone_role"):
            raise ValueError(f"profile {profile_id} requires binding.target_bone_role")
        if not profile["validation"].get("required_views"):
            raise ValueError(f"profile {profile_id} requires validation.required_views")

