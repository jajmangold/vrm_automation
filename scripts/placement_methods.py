from __future__ import annotations

from typing import Any


CANONICAL_PLACEMENT_METHOD = "qwen-image-edit-2509+sam31-iterative-damped"
CANONICAL_PLACEMENT_SOURCE = "qwen-image-edit+sam31"


def is_canonical_placement_method(method: str | None) -> bool:
    cleaned = (method or "").strip().lower()
    return "qwen-image-edit" in cleaned and "sam31" in cleaned


def is_canonical_anchor_calibration(anchor_calibration: dict[str, Any] | None) -> bool:
    calibration = anchor_calibration or {}
    method = calibration.get("method")
    source = calibration.get("source")
    return is_canonical_placement_method(str(method or source or ""))


def canonical_placement_note() -> str:
    return (
        "Canonical placement requires Qwen Image Edit target generation plus SAM 3.1 measurement; "
        "profile-only SAM suggestions are legacy review inputs."
    )
