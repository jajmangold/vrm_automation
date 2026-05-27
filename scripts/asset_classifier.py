from __future__ import annotations


VALID_CATEGORIES = {"torso_back", "neck_chest", "head_face", "torso_front", "hand_held", "unknown"}

KEYWORDS = {
    "head_face": (
        "glasses",
        "sunglasses",
        "eyeglasses",
        "goggles",
        "mask",
        "helmet",
        "hat",
        "fedora",
        "crown",
        "headphones",
        "monocle",
    ),
    "neck_chest": (
        "bowtie",
        "bow_tie",
        "necklace",
        "pendant",
        "collar",
        "scarf",
        "choker",
        "tie",
    ),
    "torso_back": (
        "backpack",
        "knapsack",
        "satchel",
        "quiver",
        "bag",
        "purse",
    ),
    "hand_held": (
        "briefcase",
        "suitcase",
        "luggage",
        "handbag",
        "toolbox",
        "lantern",
        "umbrella",
    ),
    "torso_front": (
        "belt",
        "sash",
        "vest",
        "jacket",
        "shirt",
    ),
}

PLACEMENT_PROFILES = {
    "torso_back": {
        "category": "torso_back",
        "scale_axis": "height",
        "target_size_ratio": 0.16,
        "vertical_center_ratio": 0.57,
        "surface": "back",
        "surface_offset_ratio": 0.34,
        "target_bone_role": "spine",
        "bind_roles": ("hips", "spine", "chest"),
        "weighting_mode": "height-band-torso",
        "fit_scope": "torso",
    },
    "torso_front": {
        "category": "torso_front",
        "scale_axis": "height",
        "target_size_ratio": 0.14,
        "vertical_center_ratio": 0.55,
        "surface": "torso",
        "surface_offset_ratio": 0.28,
        "target_bone_role": "spine",
        "bind_roles": ("hips", "spine", "chest"),
        "weighting_mode": "height-band-torso",
        "fit_scope": "torso",
    },
    "neck_chest": {
        "category": "neck_chest",
        "scale_axis": "height",
        "target_size_ratio": 0.12,
        "vertical_center_ratio": 0.74,
        "surface": "front",
        "surface_offset_ratio": 0.22,
        "target_bone_role": "chest",
        "bind_roles": ("spine", "chest", "neck"),
        "weighting_mode": "upper-torso-neck",
        "fit_scope": "neck-chest",
    },
    "head_face": {
        "category": "head_face",
        "scale_axis": "width",
        "target_size_ratio": 0.22,
        "vertical_center_ratio": 0.90,
        "surface": "front",
        "surface_offset_ratio": 0.18,
        "target_bone_role": "head",
        "bind_roles": ("head",),
        "weighting_mode": "single-bone",
        "fit_scope": "head-face",
    },
    "hand_held": {
        "category": "hand_held",
        "scale_axis": "height",
        "target_size_ratio": 0.18,
        "vertical_center_ratio": 0.45,
        "horizontal_center_offset_ratio": 0.22,
        "surface": "hand",
        "surface_offset_ratio": 0.08,
        "target_bone_role": "right_hand",
        "bind_roles": ("right_hand",),
        "weighting_mode": "single-bone",
        "fit_scope": "hand-held",
    },
    "unknown": {
        "category": "unknown",
        "scale_axis": "height",
        "target_size_ratio": 0.12,
        "vertical_center_ratio": 0.57,
        "surface": "front",
        "surface_offset_ratio": 0.34,
        "target_bone_role": "spine",
        "bind_roles": ("spine",),
        "weighting_mode": "single-bone",
        "fit_scope": "visual-review",
    },
}


def normalize_category(category: str | None) -> str | None:
    if not category:
        return None
    cleaned = category.strip().lower().replace("-", "_").replace(" ", "_")
    return cleaned if cleaned in VALID_CATEGORIES else None


def classify_asset(asset_name: str, source_path: str = "", explicit_category: str | None = None) -> dict:
    explicit = normalize_category(explicit_category)
    label = f"{asset_name} {source_path}".lower().replace("-", "_")
    if explicit:
        return {
            "category": explicit,
            "confidence": "explicit",
            "matched_keyword": None,
            "source_label": label.strip(),
        }

    for category, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in label:
                return {
                    "category": category,
                    "confidence": "name-keyword",
                    "matched_keyword": keyword,
                    "source_label": label.strip(),
                }

    return {
        "category": "unknown",
        "confidence": "fallback",
        "matched_keyword": None,
        "source_label": label.strip(),
    }


def placement_profile(category: str) -> dict:
    normalized = normalize_category(category) or "unknown"
    profile = PLACEMENT_PROFILES[normalized].copy()
    profile["bind_roles"] = list(profile["bind_roles"])
    return profile
