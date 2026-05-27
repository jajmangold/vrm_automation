from __future__ import annotations

import argparse
import base64
import colorsys
import copy
import io
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


Box = list[float]


DEFAULT_QWEN_WORKFLOW_SEARCH_ROOTS = [
    Path("/srv/nvme-data/containers/comfy/storage-user/workflows"),
    Path("/srv/nvme-data/containers/wan2gp/defaults"),
    Path("/srv/nvme-data/containers/wan2gp/profiles/qwen"),
]
QWEN_EDIT_REQUIRED_CLASSES = {
    "LoadImage",
    "TextEncodeQwenImageEditPlus",
    "KSampler",
    "SaveImage",
}
ANCHOR_NAMES_BY_CATEGORY = {
    "head_face": "face_center",
    "neck_chest": "collar_center",
    "torso_back": "back_center",
    "torso_front": "torso_front_center",
    "unknown": "visual_target",
}


def parse_box(value: str) -> Box:
    parts = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(parts) != 4:
        raise ValueError("box must contain four numbers: x1,y1,x2,y2")
    x1, y1, x2, y2 = parts
    if x2 <= x1 or y2 <= y1:
        raise ValueError("box must be ordered as x1,y1,x2,y2 with positive width and height")
    return parts


def parse_named_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError("named values must use view=value syntax")
    name, raw = value.split("=", 1)
    name = name.strip()
    raw = raw.strip()
    if not name or not raw:
        raise ValueError("named values must include both view and value")
    return name, raw


def parse_device_map(values: list[str]) -> dict[str, str]:
    device_map = {}
    for value in values:
        class_type, device = parse_named_value(value)
        device_map[class_type] = device
    return device_map


def box_center(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def box_size(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x2 - x1, y2 - y1)


def normalized_measurement(box: Box, character_box: Box) -> dict[str, dict[str, float]]:
    center = box_center(box)
    size = box_size(box)
    character_size = box_size(character_box)
    char_x1, char_y1, _char_x2, _char_y2 = character_box
    return {
        "center_ratio": {
            "x": rounded((center[0] - char_x1) / max(character_size[0], 1e-6)),
            "y": rounded((center[1] - char_y1) / max(character_size[1], 1e-6)),
        },
        "size_ratio": {
            "width": rounded(size[0] / max(character_size[0], 1e-6)),
            "height": rounded(size[1] / max(character_size[1], 1e-6)),
        },
    }


def anchor_name_for_category(category: str | None, anchor_name: str | None = None) -> str:
    if anchor_name:
        return anchor_name
    cleaned = (category or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    target = ANCHOR_NAMES_BY_CATEGORY.get(cleaned, ANCHOR_NAMES_BY_CATEGORY["unknown"])
    return f"{cleaned}:{target}"


def anchor_calibration_from_boxes(
    current_box: Box,
    target_box: Box,
    character_box: Box,
    asset_key: str | None = None,
    category: str | None = None,
    source: str = "qwen-image-edit+sam31",
    anchor_name: str | None = None,
) -> dict[str, Any]:
    current = normalized_measurement(current_box, character_box)
    target = normalized_measurement(target_box, character_box)
    return {
        "asset_key": asset_key,
        "category": category or "unknown",
        "anchor_name": anchor_name_for_category(category, anchor_name),
        "source": source,
        "coordinate_space": "character_render_box_ratio",
        "target_center_ratio": target["center_ratio"],
        "target_size_ratio": target["size_ratio"],
        "current_center_ratio": current["center_ratio"],
        "current_size_ratio": current["size_ratio"],
        "correction_delta_ratio": {
            "x": rounded(target["center_ratio"]["x"] - current["center_ratio"]["x"]),
            "y": rounded(target["center_ratio"]["y"] - current["center_ratio"]["y"]),
        },
    }


def multi_view_anchor_calibration_from_boxes(
    view_measurements: list[dict[str, Any]],
    asset_key: str | None = None,
    category: str | None = None,
    source: str = "qwen-image-edit+sam31+multi-angle",
    anchor_name: str | None = None,
    primary_view: str | None = None,
) -> dict[str, Any]:
    if not view_measurements:
        raise ValueError("provide at least one view measurement")

    views: dict[str, dict[str, Any]] = {}
    primary: dict[str, Any] | None = None
    primary_name: str | None = None

    for measurement in view_measurements:
        view = str(measurement.get("view", "")).strip()
        if not view:
            raise ValueError("each view measurement must include a view name")
        calibration = anchor_calibration_from_boxes(
            current_box=measurement["current_box"],
            target_box=measurement["target_box"],
            character_box=measurement["character_box"],
            asset_key=asset_key,
            category=category,
            source=source,
            anchor_name=anchor_name,
        )
        view_record = {
            "view": view,
            "anchor_name": calibration["anchor_name"],
            "coordinate_space": calibration["coordinate_space"],
            "target_center_ratio": calibration["target_center_ratio"],
            "target_size_ratio": calibration["target_size_ratio"],
            "current_center_ratio": calibration["current_center_ratio"],
            "current_size_ratio": calibration["current_size_ratio"],
            "correction_delta_ratio": calibration["correction_delta_ratio"],
        }
        views[view] = view_record
        if (primary_view and view == primary_view) or (primary is None and primary_view is None):
            primary = calibration
            primary_name = view

    if primary is None or primary_name is None:
        raise ValueError(f"primary view was not found: {primary_view}")

    return {
        **primary,
        "primary_view": primary_name,
        "view_count": len(views),
        "views": views,
    }


def anchor_expected_for_view(anchor_calibration: dict[str, Any], view: str) -> dict[str, Any]:
    views = anchor_calibration.get("views", {})
    if isinstance(views, dict) and view in views:
        return views[view]
    return anchor_calibration


def validate_anchor_measurement(
    view: str,
    box: Box | None,
    character_box: Box,
    anchor_calibration: dict[str, Any],
    center_tolerance: float = 0.08,
    size_tolerance: float = 0.18,
) -> dict[str, Any]:
    expected = anchor_expected_for_view(anchor_calibration, view)
    if box is None:
        return {
            "view": view,
            "status": "review",
            "warnings": ["missing-detection"],
            "measurement": None,
            "expected": expected,
        }

    measurement = normalized_measurement(box, character_box)
    expected_center = expected.get("target_center_ratio", {})
    expected_size = expected.get("target_size_ratio", {})
    center_delta = {
        axis: rounded(measurement["center_ratio"].get(axis, 0.0) - float(expected_center.get(axis, 0.0)))
        for axis in ("x", "y")
    }
    size_delta = {
        axis: rounded(measurement["size_ratio"].get(axis, 0.0) - float(expected_size.get(axis, 0.0)))
        for axis in ("width", "height")
    }

    warnings = []
    if abs(center_delta["x"]) > center_tolerance:
        warnings.append("center-x-drift")
    if abs(center_delta["y"]) > center_tolerance:
        warnings.append("center-y-drift")
    if abs(size_delta["width"]) > size_tolerance:
        warnings.append("width-drift")
    if abs(size_delta["height"]) > size_tolerance:
        warnings.append("height-drift")

    return {
        "view": view,
        "status": "review" if warnings else "ok",
        "warnings": warnings,
        "measurement": measurement,
        "expected": {
            "target_center_ratio": expected_center,
            "target_size_ratio": expected_size,
            "anchor_name": expected.get("anchor_name", anchor_calibration.get("anchor_name")),
        },
        "delta": {
            "center_ratio": center_delta,
            "size_ratio": size_delta,
        },
        "thresholds": {
            "center_tolerance": center_tolerance,
            "size_tolerance": size_tolerance,
        },
    }


def validate_anchor_measurements(
    views: list[dict[str, Any]],
    anchor_calibration: dict[str, Any],
    center_tolerance: float = 0.08,
    size_tolerance: float = 0.18,
    minimum_views: int = 1,
) -> dict[str, Any]:
    results = [
        validate_anchor_measurement(
            view=str(view["view"]),
            box=view.get("box"),
            character_box=view["character_box"],
            anchor_calibration=anchor_calibration,
            center_tolerance=center_tolerance,
            size_tolerance=size_tolerance,
        )
        for view in views
    ]
    warnings = []
    for result in results:
        for warning in result["warnings"]:
            warnings.append(f"{warning}:{result['view']}")
    if len(results) < minimum_views:
        warnings.append(f"insufficient-views:{len(results)}<{minimum_views}")
    ok_count = sum(1 for result in results if result["status"] == "ok")
    return {
        "status": "ok" if results and ok_count == len(results) and len(results) >= minimum_views else "review",
        "anchor_name": anchor_calibration.get("anchor_name"),
        "view_count": len(results),
        "minimum_views": minimum_views,
        "ok_view_count": ok_count,
        "warnings": warnings,
        "views": results,
    }


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def rounded(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def bbox_from_mask_image(path: Path) -> Box:
    from PIL import Image

    image = Image.open(path).convert("L")
    pixels = image.load()
    width, height = image.size
    xs = []
    ys = []
    for y in range(height):
        for x in range(width):
            if pixels[x, y] > 0:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise ValueError(f"mask has no nonzero pixels: {path}")
    return [float(min(xs)), float(min(ys)), float(max(xs) + 1), float(max(ys) + 1)]


def bbox_from_color_image(path: Path, preset: str = "red-accessory") -> Box:
    from PIL import Image

    if preset != "red-accessory":
        raise ValueError(f"unsupported color bbox preset: {preset}")

    image = Image.open(path).convert("RGB")
    pixels = image.load()
    width, height = image.size
    xs = []
    ys = []
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            hue, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if value > 0.25 and saturation > 0.4 and (hue < 0.05 or hue > 0.95):
                xs.append(x)
                ys.append(y)
    if not xs:
        raise ValueError(f"image has no {preset} pixels: {path}")
    return [float(min(xs)), float(min(ys)), float(max(xs) + 1), float(max(ys) + 1)]


def bbox_from_foreground_image(path: Path, color_distance_threshold: float = 0.12) -> Box:
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    pixels = image.load()
    width, height = image.size
    corner_colors = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    background_samples = [
        (red / 255.0, green / 255.0, blue / 255.0)
        for red, green, blue, alpha in corner_colors
        if alpha > 0
    ]
    if not background_samples:
        background_samples = [(0.0, 0.0, 0.0)]

    xs = []
    ys = []
    threshold_sq = color_distance_threshold * color_distance_threshold
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            color = (red / 255.0, green / 255.0, blue / 255.0)
            distance_sq = min(
                sum((component - background) ** 2 for component, background in zip(color, sample))
                for sample in background_samples
            )
            if distance_sq > threshold_sq:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise ValueError(f"image has no foreground pixels: {path}")
    return [float(min(xs)), float(min(ys)), float(max(xs) + 1), float(max(ys) + 1)]


def best_detection_box(response: dict[str, Any], combine: bool = False) -> Box:
    candidates: list[tuple[float, Box]] = []
    for job in response.get("results", []):
        for prompt_result in job.get("results", []):
            for detection in prompt_result.get("detections", []):
                box = detection.get("box_xyxy")
                if box and len(box) == 4:
                    candidates.append((float(detection.get("score", 0.0)), [float(value) for value in box]))
    if not candidates:
        raise ValueError("SAM response did not contain any detections")
    if combine:
        boxes = [box for _score, box in candidates]
        return [
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ]
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def best_detection_mask(response: dict[str, Any]) -> dict[str, Any]:
    best: tuple[float, dict[str, Any]] | None = None
    for job in response.get("results", []):
        for prompt_result in job.get("results", []):
            for detection in prompt_result.get("detections", []):
                mask = detection.get("mask")
                if not mask or mask.get("format") != "png" or not mask.get("data"):
                    continue
                score = float(detection.get("score", 0.0))
                if best is None or score > best[0]:
                    best = (score, detection)
    if best is None:
        raise ValueError("SAM response did not contain any PNG masks")
    return best[1]


def mask_array_from_png_base64(value: str) -> Any:
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(base64.b64decode(value))).convert("L")
    return np.array(image) > 0


def mask_points(mask: Any, max_points: int = 4096) -> Any:
    import numpy as np

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("mask has no foreground pixels")
    points = np.column_stack([xs.astype(float), ys.astype(float)])
    if len(points) > max_points:
        step = max(1, len(points) // max_points)
        points = points[::step][:max_points]
    return points


def mask_moments(mask: Any) -> dict[str, Any]:
    import numpy as np

    try:
        import cv2  # type: ignore
    except ImportError:
        cv2 = None

    if cv2 is not None:
        binary = np.asarray(mask, dtype=np.uint8)
        points_yx = cv2.findNonZero(binary)
        if points_yx is None:
            raise ValueError("mask has no foreground pixels")
        points = points_yx.reshape(-1, 2).astype(float)
        moments = cv2.moments(binary)
        if abs(moments["m00"]) > 1e-6:
            centroid = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]])
        else:
            centroid = points.mean(axis=0)
        rect = cv2.minAreaRect(points.astype(np.float32))
        (_center_x, _center_y), (rect_w, rect_h), rect_angle = rect
        if rect_w < rect_h:
            angle = float(rect_angle)
            major = rect_h
            minor = rect_w
        else:
            angle = float(rect_angle + 90.0)
            major = rect_w
            minor = rect_h
        while angle > 90:
            angle -= 180
        while angle < -90:
            angle += 180
        x, y, w, h = cv2.boundingRect(points.astype(np.int32))
        return {
            "centroid": centroid,
            "angle_degrees": angle,
            "spread": np.array([max(float(major), 1e-6), max(float(minor), 1e-6)]),
            "area": int(binary.sum()),
            "box": [float(x), float(y), float(x + w), float(y + h)],
            "backend": "opencv",
        }

    points = mask_points(mask)
    centroid = points.mean(axis=0)
    centered = points - centroid
    covariance = np.cov(centered, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    major = eigenvectors[:, 0]
    if major[1] < 0:
        major = -major
    angle = float(np.degrees(np.arctan2(major[1], major[0])))
    if angle > 90:
        angle -= 180
    if angle < -90:
        angle += 180
    spread = np.sqrt(np.maximum(eigenvalues, 1e-6))
    return {
        "centroid": centroid,
        "angle_degrees": angle,
        "spread": spread,
        "area": int(points.shape[0]),
        "box": [
            float(points[:, 0].min()),
            float(points[:, 1].min()),
            float(points[:, 0].max() + 1),
            float(points[:, 1].max() + 1),
        ],
        "backend": "numpy",
    }


def similarity_transform_from_masks(current_mask: Any, target_mask: Any, character_box: Box) -> dict[str, Any]:
    import numpy as np

    current = mask_moments(current_mask)
    target = mask_moments(target_mask)
    current_size = box_size(current["box"])
    target_size = box_size(target["box"])
    character_size = box_size(character_box)
    current_spread = current["spread"]
    target_spread = target["spread"]
    major_scale = float(target_spread[0] / max(current_spread[0], 1e-6))
    minor_scale = float(target_spread[1] / max(current_spread[1], 1e-6))
    centroid_delta = target["centroid"] - current["centroid"]
    angle_delta = float(target["angle_degrees"] - current["angle_degrees"])
    return {
        "current_box": [rounded(value, 2) for value in current["box"]],
        "target_box": [rounded(value, 2) for value in target["box"]],
        "current_area": current["area"],
        "target_area": target["area"],
        "centroid_delta_pixels": {"x": rounded(centroid_delta[0], 2), "y": rounded(centroid_delta[1], 2)},
        "centroid_delta_ratio": {
            "x": rounded(centroid_delta[0] / max(character_size[0], 1e-6)),
            "y": rounded(centroid_delta[1] / max(character_size[1], 1e-6)),
        },
        "scale": {
            "major_axis": rounded(major_scale),
            "minor_axis": rounded(minor_scale),
            "width": rounded(target_size[0] / max(current_size[0], 1e-6)),
            "height": rounded(target_size[1] / max(current_size[1], 1e-6)),
            "area": rounded(float(np.sqrt(target["area"] / max(current["area"], 1e-6)))),
        },
        "rotation_delta_degrees": rounded(angle_delta),
        "current_angle_degrees": rounded(current["angle_degrees"]),
        "target_angle_degrees": rounded(target["angle_degrees"]),
        "backend": "opencv" if current.get("backend") == "opencv" and target.get("backend") == "opencv" else "numpy",
    }


def workflow_nodes_by_class(workflow: dict[str, Any], class_type: str) -> list[dict[str, Any]]:
    return [
        node
        for _node_id, node in sorted(workflow.items(), key=lambda item: str(item[0]))
        if node.get("class_type") == class_type
    ]


def first_workflow_node(workflow: dict[str, Any], class_type: str) -> dict[str, Any]:
    nodes = workflow_nodes_by_class(workflow, class_type)
    if not nodes:
        raise ValueError(f"workflow does not contain {class_type}")
    return nodes[0]


def workflow_class_types(workflow: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(node.get("class_type", ""))
            for node in workflow.values()
            if isinstance(node, dict) and node.get("class_type")
        }
    )


def workflow_lora_names(workflow: dict[str, Any]) -> list[str]:
    names = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        lora_name = inputs.get("lora_name")
        if lora_name:
            names.append(str(lora_name))
    return sorted(dict.fromkeys(names))


def qwen_workflow_score(path: Path, class_types: list[str], lora_names: list[str]) -> int:
    name = path.name.lower()
    score = 0
    for token, weight in (
        ("qwen-image-edit", 60),
        ("qwen", 25),
        ("edit", 15),
        ("api", 12),
        ("fast", 10),
        ("4step", 8),
        ("4-step", 8),
        ("nextscene", 6),
        ("next-scene", 6),
        ("multigpu", 4),
        ("q3ks", 3),
    ):
        if token in name:
            score += weight
    if path.suffix == ".json":
        score += 1
    if lora_names:
        score += min(len(lora_names), 4)
    score += len(set(class_types) & QWEN_EDIT_REQUIRED_CLASSES)
    return score


def qwen_edit_workflow_summary(path: Path) -> dict[str, Any] | None:
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(workflow, dict):
        return None
    class_types = workflow_class_types(workflow)
    if not QWEN_EDIT_REQUIRED_CLASSES.issubset(set(class_types)):
        return None
    lora_names = workflow_lora_names(workflow)
    return {
        "path": str(path),
        "class_types": class_types,
        "lora_names": lora_names,
        "score": qwen_workflow_score(path, class_types, lora_names),
    }


def discover_qwen_edit_workflows(search_roots: list[Path]) -> list[dict[str, Any]]:
    summaries = []
    seen = set()
    for root in search_roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*.json")
        for path in candidates:
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            summary = qwen_edit_workflow_summary(path)
            if summary:
                summaries.append(summary)
    summaries.sort(key=lambda item: (-int(item["score"]), item["path"]))
    return summaries


def qwen_workflow_search_roots(values: list[str]) -> list[Path]:
    if values:
        return [Path(value) for value in values]
    return DEFAULT_QWEN_WORKFLOW_SEARCH_ROOTS


def resolve_qwen_workflow_path(value: str, search_roots: list[Path]) -> tuple[Path, dict[str, Any] | None]:
    if value == "auto":
        workflows = discover_qwen_edit_workflows(search_roots)
        if not workflows:
            roots = ", ".join(str(root) for root in search_roots)
            raise ValueError(f"could not find a local Qwen Image Edit workflow under: {roots}")
        selected = workflows[0]
        return Path(selected["path"]), selected

    path = Path(value)
    return path, qwen_edit_workflow_summary(path)


def relative_to_root(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def stage_comfy_input(source_image: Path, input_root: Path, subfolder: str = "vrm_calibration") -> str:
    existing = relative_to_root(source_image, input_root)
    if existing:
        return existing

    destination_dir = input_root / subfolder if subfolder else input_root
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_image.name
    if source_image.resolve() != destination.resolve():
        shutil.copy2(source_image, destination)
    return destination.relative_to(input_root).as_posix()


def comfy_output_image_path(image: dict[str, str], output_root: Path) -> Path:
    filename = image.get("filename")
    if not filename:
        raise ValueError(f"ComfyUI image record did not include filename: {image}")
    subfolder = image.get("subfolder", "")
    return output_root / subfolder / filename


def prepare_qwen_edit_workflow(
    workflow: dict[str, Any],
    source_image: str,
    prompt: str,
    filename_prefix: str,
    seed: int,
    steps: int | None = None,
    denoise: float | None = None,
    megapixels: float | None = None,
    negative_prompt: str = "",
    device_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    prepared = copy.deepcopy(workflow)
    first_workflow_node(prepared, "LoadImage")["inputs"]["image"] = source_image

    text_nodes = workflow_nodes_by_class(prepared, "TextEncodeQwenImageEditPlus")
    if not text_nodes:
        raise ValueError("workflow does not contain TextEncodeQwenImageEditPlus")
    text_nodes[0]["inputs"]["prompt"] = prompt
    if len(text_nodes) > 1:
        text_nodes[1]["inputs"]["prompt"] = negative_prompt

    sampler = first_workflow_node(prepared, "KSampler")
    sampler["inputs"]["seed"] = int(seed)
    if steps is not None:
        sampler["inputs"]["steps"] = int(steps)
    if denoise is not None:
        sampler["inputs"]["denoise"] = float(denoise)

    if megapixels is not None:
        for node in workflow_nodes_by_class(prepared, "ImageScaleToTotalPixels"):
            if "megapixels" in node.get("inputs", {}):
                node["inputs"]["megapixels"] = float(megapixels)

    first_workflow_node(prepared, "SaveImage")["inputs"]["filename_prefix"] = filename_prefix

    for class_type, device in (device_map or {}).items():
        for node in workflow_nodes_by_class(prepared, class_type):
            if "device" in node.get("inputs", {}):
                node["inputs"]["device"] = device

    return prepared


def submit_comfy_workflow(
    workflow: dict[str, Any],
    endpoint: str = "http://127.0.0.1:8190",
    client_id: str = "vrm-accessory-calibrator",
    timeout_seconds: int = 120,
    urlopen=urllib.request.urlopen,
) -> str:
    payload = {"prompt": workflow, "client_id": client_id}
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/prompt",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
    return str(prompt_id)


def poll_comfy_history(
    prompt_id: str,
    endpoint: str = "http://127.0.0.1:8190",
    poll_interval_seconds: float = 2.0,
    timeout_seconds: float = 600.0,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    request = urllib.request.Request(f"{endpoint.rstrip('/')}/history/{prompt_id}", method="GET")
    last_response: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        with urlopen(request, timeout=120) as response:
            last_response = json.loads(response.read().decode("utf-8") or "{}")
        record = last_response.get(prompt_id, last_response)
        if record.get("outputs"):
            return last_response
        sleep(poll_interval_seconds)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}: {last_response}")


def comfy_saved_images(history: dict[str, Any], prompt_id: str | None = None) -> list[dict[str, str]]:
    record = history.get(prompt_id, history) if prompt_id else history
    images = []
    for node_id, output in sorted(record.get("outputs", {}).items(), key=lambda item: str(item[0])):
        for image in output.get("images", []):
            images.append(
                {
                    "node_id": str(node_id),
                    "filename": str(image.get("filename", "")),
                    "subfolder": str(image.get("subfolder", "")),
                    "type": str(image.get("type", "")),
                }
            )
    return images


def prepare_qwen_edit_from_args(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not args.qwen_source_image and not args.current_image:
        raise ValueError("provide --qwen-source-image or --current-image when using --qwen-workflow-json")
    source_image = Path(args.qwen_source_image or args.current_image)
    workflow_path, workflow_summary = resolve_qwen_workflow_path(
        args.qwen_workflow_json,
        qwen_workflow_search_roots(args.qwen_workflow_search_root),
    )
    workflow_template = json.loads(workflow_path.read_text(encoding="utf-8"))
    staged_source = stage_comfy_input(
        source_image=source_image,
        input_root=Path(args.comfy_input_root),
        subfolder=args.comfy_input_subfolder,
    )
    prepared = prepare_qwen_edit_workflow(
        workflow_template,
        source_image=staged_source,
        prompt=args.qwen_prompt,
        filename_prefix=args.qwen_filename_prefix,
        seed=args.qwen_seed,
        steps=args.qwen_steps,
        denoise=args.qwen_denoise,
        megapixels=args.qwen_megapixels,
        negative_prompt=args.qwen_negative_prompt,
        device_map=parse_device_map(args.qwen_device_map),
    )
    metadata = {
        "status": "prepared",
        "workflow_template": str(workflow_path),
        "endpoint": args.qwen_endpoint,
        "source_image": str(source_image),
        "staged_source_image": staged_source,
        "prompt": args.qwen_prompt,
        "negative_prompt": args.qwen_negative_prompt,
        "filename_prefix": args.qwen_filename_prefix,
        "seed": args.qwen_seed,
        "steps": args.qwen_steps,
        "denoise": args.qwen_denoise,
        "megapixels": args.qwen_megapixels,
        "run": bool(args.qwen_run),
    }
    if workflow_summary:
        metadata["workflow_discovery"] = workflow_summary
    return prepared, metadata, staged_source


def maybe_run_qwen_edit(
    prepared_workflow: dict[str, Any],
    metadata: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Path | None]:
    if args.qwen_prepared_workflow_json:
        prepared_path = Path(args.qwen_prepared_workflow_json)
        prepared_path.parent.mkdir(parents=True, exist_ok=True)
        prepared_path.write_text(json.dumps(prepared_workflow, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        metadata["prepared_workflow_json"] = str(prepared_path)

    if not args.qwen_run:
        return metadata, None

    prompt_id = submit_comfy_workflow(
        prepared_workflow,
        endpoint=args.qwen_endpoint,
        client_id=args.qwen_client_id,
        timeout_seconds=args.qwen_timeout_seconds,
    )
    history = poll_comfy_history(
        prompt_id,
        endpoint=args.qwen_endpoint,
        poll_interval_seconds=args.qwen_poll_interval_seconds,
        timeout_seconds=args.qwen_timeout_seconds,
    )
    if args.qwen_history_json:
        history_path = Path(args.qwen_history_json)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        metadata["history_json"] = str(history_path)

    saved_images = comfy_saved_images(history, prompt_id)
    if not saved_images:
        raise RuntimeError(f"ComfyUI prompt {prompt_id} completed without saved images")
    target_image = comfy_output_image_path(saved_images[0], Path(args.comfy_output_root))
    metadata.update(
        {
            "status": "completed",
            "prompt_id": prompt_id,
            "saved_images": saved_images,
            "target_image": str(target_image),
        }
    )
    return metadata, target_image


def sam31_segment_box(
    image_path: Path,
    prompt: str,
    endpoint: str = "http://127.0.0.1:8105",
    confidence_threshold: float = 0.35,
    combine_detections: bool = True,
) -> Box:
    image_bytes = image_path.read_bytes()
    payload = {
        "jobs": [
            {
                "id": image_path.stem,
                "image": {
                    "type": "base64",
                    "value": base64.b64encode(image_bytes).decode("ascii"),
                },
                "prompts": [{"id": "target", "type": "text", "text": prompt}],
                "confidence_threshold": confidence_threshold,
                "return_masks": False,
                "mask_format": "none",
                "max_detections": 4,
            }
        ]
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/v1/images/segment",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return best_detection_box(
                json.loads(response.read().decode("utf-8")),
                combine=combine_detections,
            )
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SAM31 endpoint unavailable at {endpoint}: {exc}") from exc


def sam31_segment_mask(
    image_path: Path,
    prompt: str,
    endpoint: str = "http://127.0.0.1:8105",
    confidence_threshold: float = 0.35,
) -> dict[str, Any]:
    image_bytes = image_path.read_bytes()
    payload = {
        "jobs": [
            {
                "id": image_path.stem,
                "image": {
                    "type": "base64",
                    "value": base64.b64encode(image_bytes).decode("ascii"),
                },
                "prompts": [{"id": "target", "type": "text", "text": prompt}],
                "confidence_threshold": confidence_threshold,
                "return_masks": True,
                "mask_format": "png",
                "max_detections": 4,
            }
        ]
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/v1/images/segment",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            detection = best_detection_mask(json.loads(response.read().decode("utf-8")))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SAM31 endpoint unavailable at {endpoint}: {exc}") from exc
    return {
        "box": [float(value) for value in detection["box_xyxy"]],
        "score": float(detection.get("score", 0.0)),
        "mask": mask_array_from_png_base64(detection["mask"]["data"]),
    }


def mask_registered_fit_overrides(
    current_mask: Any,
    target_mask: Any,
    character_box: Box,
    current_overrides: dict[str, Any] | None = None,
    asset_key: str | None = None,
    category: str | None = None,
    source: str = "qwen-image-edit+sam31-mask-registration",
    anchor_name: str | None = None,
    center_correction_gain: float = 1.0,
    size_correction_gain: float = 1.0,
    rotation_correction_gain: float = 1.0,
    min_target_size_ratio: float | None = None,
    max_target_size_ratio: float | None = None,
) -> dict[str, Any]:
    transform = similarity_transform_from_masks(current_mask, target_mask, character_box)
    result = calibrated_fit_overrides(
        current_box=transform["current_box"],
        target_box=transform["target_box"],
        character_box=character_box,
        current_overrides=current_overrides,
        asset_key=asset_key,
        category=category,
        source=source,
        anchor_name=anchor_name,
        center_correction_gain=center_correction_gain,
        size_correction_gain=size_correction_gain,
        min_target_size_ratio=min_target_size_ratio,
        max_target_size_ratio=max_target_size_ratio,
    )
    overrides = result["fit_overrides"]
    rotation_delta = transform["rotation_delta_degrees"] * rotation_correction_gain
    if abs(rotation_delta) >= 0.5:
        overrides["rotation_z_degrees"] = rounded(float(overrides.get("rotation_z_degrees", 0.0)) + rotation_delta)
    result["fit_overrides"] = overrides
    result["mask_registration"] = transform
    result["anchor_calibration"]["source"] = source
    return result


def calibrated_fit_overrides(
    current_box: Box,
    target_box: Box,
    character_box: Box,
    current_overrides: dict[str, Any] | None = None,
    asset_key: str | None = None,
    category: str | None = None,
    source: str = "qwen-image-edit+sam31",
    anchor_name: str | None = None,
    center_correction_gain: float = 1.0,
    size_correction_gain: float = 1.0,
    min_target_size_ratio: float | None = None,
    max_target_size_ratio: float | None = None,
) -> dict[str, Any]:
    overrides = dict(current_overrides or {})
    current_center = box_center(current_box)
    target_center = box_center(target_box)
    current_size = box_size(current_box)
    target_size = box_size(target_box)
    character_size = box_size(character_box)

    dx = target_center[0] - current_center[0]
    dy = target_center[1] - current_center[1]
    width_scale = target_size[0] / max(current_size[0], 1e-6)
    height_scale = target_size[1] / max(current_size[1], 1e-6)

    scale_axis = str(overrides.get("scale_axis", "width"))
    raw_scale = width_scale if scale_axis == "width" else height_scale
    scale = 1.0 + ((raw_scale - 1.0) * size_correction_gain)
    target_size_ratio = float(overrides.get("target_size_ratio", 0.22))
    vertical_center_ratio = float(overrides.get("vertical_center_ratio", 0.72))
    horizontal_offset_ratio = float(overrides.get("horizontal_center_offset_ratio", 0.0))
    solved_target_size_ratio = target_size_ratio * scale
    if min_target_size_ratio is not None:
        solved_target_size_ratio = max(solved_target_size_ratio, float(min_target_size_ratio))
    if max_target_size_ratio is not None:
        solved_target_size_ratio = min(solved_target_size_ratio, float(max_target_size_ratio))

    measured_overrides = {
        **overrides,
        "scale_axis": scale_axis,
        "target_size_ratio": rounded(clamp(solved_target_size_ratio, 0.01, 0.6)),
        "vertical_center_ratio": rounded(
            clamp(vertical_center_ratio - ((dy / max(character_size[1], 1e-6)) * center_correction_gain), 0.0, 1.1)
        ),
    }
    horizontal_delta = (dx / max(character_size[0], 1e-6)) * center_correction_gain
    if abs(horizontal_delta) >= 0.005 or "horizontal_center_offset_ratio" in overrides:
        measured_overrides["horizontal_center_offset_ratio"] = rounded(
            clamp(horizontal_offset_ratio + horizontal_delta, -0.5, 0.5)
        )

    return {
        "current_box": [rounded(value, 2) for value in current_box],
        "target_box": [rounded(value, 2) for value in target_box],
        "character_box": [rounded(value, 2) for value in character_box],
        "pixel_delta": {"x": rounded(dx, 2), "y": rounded(dy, 2)},
        "image_measurement": {
            "coordinate_space": "ratios inside character_box; y increases downward in the render",
            "current": normalized_measurement(current_box, character_box),
            "target": normalized_measurement(target_box, character_box),
            "delta_ratio": {
                "x": rounded(dx / max(character_size[0], 1e-6)),
                "y": rounded(dy / max(character_size[1], 1e-6)),
            },
        },
        "scale": {"width": width_scale, "height": height_scale},
        "correction_gain": {
            "center": center_correction_gain,
            "size": size_correction_gain,
        },
        "size_constraints": {
            "min_target_size_ratio": min_target_size_ratio,
            "max_target_size_ratio": max_target_size_ratio,
        },
        "fit_overrides": measured_overrides,
        "anchor_calibration": anchor_calibration_from_boxes(
            current_box=current_box,
            target_box=target_box,
            character_box=character_box,
            asset_key=asset_key,
            category=category,
            source=source,
            anchor_name=anchor_name,
        ),
    }


def load_overrides(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_anchor_calibration(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("anchor_calibration", data)


def asset_catalog_key(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.removeprefix("poly-pizza-")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")


def asset_lookup_keys(asset: dict[str, Any]) -> set[str]:
    keys = set()
    asset_id = str(asset.get("id", ""))
    title = str(asset.get("title", ""))
    creator = str(asset.get("creator", ""))
    for value in (asset_id, asset_catalog_key(asset_id), title, f"{title}-{creator}"):
        key = asset_catalog_key(value)
        if key:
            keys.add(key)
    return keys


def find_asset(config: dict[str, Any], asset_key: str) -> dict[str, Any]:
    requested = asset_catalog_key(asset_key)
    for asset in config.get("assets", []):
        if requested in asset_lookup_keys(asset):
            return asset
    raise ValueError(f"asset not found in config: {asset_key}")


def load_asset_fit_overrides(config_path: Path, asset_key: str) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    asset = find_asset(config, asset_key)
    return dict(asset.get("fit_overrides") or {})


def compact_anchor_calibration_for_asset(
    calibration_result: dict[str, Any],
    calibration_source: str,
    method: str,
    previous_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    anchor = calibration_result["anchor_calibration"]
    validation = {
        "status": "review",
        "notes": [
            "Updated from image-guided calibration; rerun multi-view anchor validation before promoting."
        ],
    }
    previous_validation = previous_validation or {}
    if previous_validation.get("status"):
        validation["previous_status"] = previous_validation["status"]
    if previous_validation.get("reports"):
        validation["previous_reports"] = previous_validation["reports"]

    return {
        "source": calibration_source,
        "method": method,
        "anchor_name": anchor.get("anchor_name"),
        "coordinate_space": anchor.get("coordinate_space"),
        "target_center_ratio": anchor.get("target_center_ratio"),
        "target_size_ratio": anchor.get("target_size_ratio"),
        "correction_delta_ratio": anchor.get("correction_delta_ratio"),
        "validation": validation,
    }


def apply_calibration_to_asset_config(
    config_path: Path,
    asset_key: str,
    calibration_result: dict[str, Any],
    calibration_source: str,
    method: str,
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    asset = find_asset(config, asset_key)
    previous_validation = (asset.get("anchor_calibration") or {}).get("validation") or {}
    asset["fit_overrides"] = calibration_result["fit_overrides"]
    asset["anchor_calibration"] = compact_anchor_calibration_for_asset(
        calibration_result=calibration_result,
        calibration_source=calibration_source,
        method=method,
        previous_validation=previous_validation,
    )
    config_path.write_text(json.dumps(config, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return {
        "status": "updated",
        "asset_id": asset.get("id"),
        "asset_key": asset_catalog_key(str(asset.get("id", asset_key))),
        "fit_overrides": asset["fit_overrides"],
        "anchor_calibration": asset["anchor_calibration"],
        "config_path": str(config_path),
    }


def apply_anchor_validation_to_asset_config(
    config_path: Path,
    asset_key: str,
    validation_result: dict[str, Any],
    validation_source: str,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    asset = find_asset(config, asset_key)
    anchor_calibration = dict(asset.get("anchor_calibration") or {})
    if not anchor_calibration:
        raise ValueError(f"asset does not have anchor_calibration: {asset_key}")

    previous_validation = dict(anchor_calibration.get("validation") or {})
    previous_reports = list(previous_validation.get("reports") or [])
    reports = [*previous_reports]
    if validation_source and validation_source not in reports:
        reports.append(validation_source)

    validation = {
        "status": str(validation_result.get("status", "review")),
        "minimum_views": int(validation_result.get("minimum_views", 0) or 0),
        "view_count": int(validation_result.get("view_count", 0) or 0),
        "ok_view_count": int(validation_result.get("ok_view_count", 0) or 0),
        "warnings": list(validation_result.get("warnings") or []),
        "reports": reports,
    }
    if notes:
        validation["notes"] = list(notes)
    elif previous_validation.get("notes"):
        validation["notes"] = list(previous_validation.get("notes") or [])
    if previous_validation.get("status"):
        validation["previous_status"] = previous_validation["status"]
    if previous_reports:
        validation["previous_reports"] = previous_reports
    if previous_validation.get("notes"):
        validation["previous_notes"] = list(previous_validation.get("notes") or [])
    if validation_result.get("anchor_name"):
        anchor_calibration["anchor_name"] = validation_result["anchor_name"]

    anchor_calibration["validation"] = validation
    asset["anchor_calibration"] = anchor_calibration
    config_path.write_text(json.dumps(config, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return {
        "status": "updated",
        "asset_id": asset.get("id"),
        "asset_key": asset_catalog_key(str(asset.get("id", asset_key))),
        "anchor_calibration": asset["anchor_calibration"],
        "config_path": str(config_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure image-guided accessory placement corrections and emit deterministic fit_overrides."
    )
    parser.add_argument("--current-box")
    parser.add_argument("--target-box")
    parser.add_argument("--character-box")
    parser.add_argument("--character-mask")
    parser.add_argument("--character-image")
    parser.add_argument("--character-image-box-mode", choices=("foreground", "sam"), default="foreground")
    parser.add_argument("--character-sam-prompt", default="person")
    parser.add_argument("--current-mask")
    parser.add_argument("--target-mask")
    parser.add_argument("--current-image")
    parser.add_argument("--target-image")
    parser.add_argument("--image-box-mode", choices=("sam", "red-accessory", "sam-red-fallback"), default="sam")
    parser.add_argument("--measurement-mode", choices=("box", "mask-registration"), default="box")
    parser.add_argument("--sam-prompt", default="bow tie")
    parser.add_argument("--sam-endpoint", default="http://127.0.0.1:8105")
    parser.add_argument("--qwen-workflow-json")
    parser.add_argument("--qwen-workflow-search-root", action="append", default=[])
    parser.add_argument("--qwen-source-image")
    parser.add_argument("--qwen-prompt", default="Move the bow tie to the shirt collar. Keep the same character and pose.")
    parser.add_argument("--qwen-negative-prompt", default="extra bow ties, detached object, floating accessory, torso block")
    parser.add_argument("--qwen-filename-prefix", default="vrm_calibration/accessory_corrected")
    parser.add_argument("--qwen-seed", type=int, default=42)
    parser.add_argument("--qwen-steps", type=int)
    parser.add_argument("--qwen-denoise", type=float)
    parser.add_argument("--qwen-megapixels", type=float)
    parser.add_argument("--qwen-endpoint", default="http://127.0.0.1:8190")
    parser.add_argument("--qwen-client-id", default="vrm-accessory-calibrator")
    parser.add_argument("--qwen-run", action="store_true")
    parser.add_argument("--qwen-timeout-seconds", type=int, default=600)
    parser.add_argument("--qwen-poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--qwen-prepared-workflow-json")
    parser.add_argument("--qwen-history-json")
    parser.add_argument("--qwen-device-map", action="append", default=[])
    parser.add_argument("--comfy-input-root", default="/srv/nvme-data/containers/comfy/storage-user/input")
    parser.add_argument("--comfy-input-subfolder", default="vrm_calibration")
    parser.add_argument("--comfy-output-root", default="/srv/nvme-data/containers/comfy/storage-user/output")
    parser.add_argument("--current-overrides-json")
    parser.add_argument("--asset-config-json")
    parser.add_argument("--current-overrides-from-asset-config", action="store_true")
    parser.add_argument("--apply-to-asset-config", action="store_true")
    parser.add_argument("--calibration-method")
    parser.add_argument("--center-correction-gain", type=float, default=1.0)
    parser.add_argument("--size-correction-gain", type=float, default=1.0)
    parser.add_argument("--rotation-correction-gain", type=float, default=1.0)
    parser.add_argument("--min-target-size-ratio", type=float)
    parser.add_argument("--max-target-size-ratio", type=float)
    parser.add_argument("--asset-key")
    parser.add_argument("--category")
    parser.add_argument("--source", default="qwen-image-edit+sam31")
    parser.add_argument("--anchor-name")
    parser.add_argument("--anchor-calibration-json")
    parser.add_argument("--validation-result-json")
    parser.add_argument("--apply-validation-to-asset-config", action="store_true")
    parser.add_argument("--validation-note", action="append", default=[])
    parser.add_argument("--current-view-box", action="append", default=[])
    parser.add_argument("--target-view-box", action="append", default=[])
    parser.add_argument("--current-view-mask", action="append", default=[])
    parser.add_argument("--target-view-mask", action="append", default=[])
    parser.add_argument("--current-view-image", action="append", default=[])
    parser.add_argument("--target-view-image", action="append", default=[])
    parser.add_argument("--view-character-box", action="append", default=[])
    parser.add_argument("--primary-view")
    parser.add_argument("--view-box", action="append", default=[])
    parser.add_argument("--view-mask", action="append", default=[])
    parser.add_argument("--view-image", action="append", default=[])
    parser.add_argument("--center-tolerance", type=float, default=0.08)
    parser.add_argument("--size-tolerance", type=float, default=0.18)
    parser.add_argument("--minimum-views", type=int, default=2)
    parser.add_argument("--output-json")
    return parser.parse_args()


def resolve_box(
    explicit_box: str | None,
    mask_path: str | None,
    image_path: str | None,
    prompt: str,
    sam_endpoint: str,
    image_box_mode: str = "sam",
) -> Box:
    if explicit_box:
        return parse_box(explicit_box)
    if mask_path:
        return bbox_from_mask_image(Path(mask_path))
    if image_path:
        if image_box_mode == "red-accessory":
            return bbox_from_color_image(Path(image_path), "red-accessory")
        if image_box_mode == "sam-red-fallback":
            try:
                return sam31_segment_box(Path(image_path), prompt, endpoint=sam_endpoint)
            except (RuntimeError, ValueError):
                return bbox_from_color_image(Path(image_path), "red-accessory")
        return sam31_segment_box(Path(image_path), prompt, endpoint=sam_endpoint)
    raise ValueError("provide a box, mask, or image for both current and target")


def resolve_character_box(args: argparse.Namespace) -> Box:
    if args.character_box:
        return parse_box(args.character_box)
    if args.character_mask:
        return bbox_from_mask_image(Path(args.character_mask))

    character_image = args.character_image or args.current_image
    if character_image:
        if args.character_image_box_mode == "sam":
            return sam31_segment_box(
                Path(character_image),
                args.character_sam_prompt,
                endpoint=args.sam_endpoint,
            )
        return bbox_from_foreground_image(Path(character_image))

    raise ValueError("provide --character-box, --character-mask, --character-image, or --current-image")


def resolve_view_boxes(args: argparse.Namespace, character_box: Box) -> list[dict[str, Any]]:
    views: dict[str, dict[str, Any]] = {}
    for value in args.view_box:
        view, raw_box = parse_named_value(value)
        views[view] = {
            "view": view,
            "box": parse_box(raw_box),
            "character_box": character_box,
        }
    for value in args.view_mask:
        view, raw_path = parse_named_value(value)
        views[view] = {
            "view": view,
            "box": bbox_from_mask_image(Path(raw_path)),
            "character_box": character_box,
        }
    for value in args.view_image:
        view, raw_path = parse_named_value(value)
        try:
            box = resolve_box(
                explicit_box=None,
                mask_path=None,
                image_path=raw_path,
                prompt=args.sam_prompt,
                sam_endpoint=args.sam_endpoint,
                image_box_mode=args.image_box_mode,
            )
        except ValueError:
            box = None
        views[view] = {
            "view": view,
            "box": box,
            "character_box": character_box,
        }
    if not views:
        raise ValueError("provide at least one --view-box, --view-mask, or --view-image")
    return [views[view] for view in sorted(views)]


def resolve_named_box_map(
    box_values: list[str],
    mask_values: list[str],
    image_values: list[str],
    args: argparse.Namespace,
) -> dict[str, Box]:
    boxes: dict[str, Box] = {}
    for value in box_values:
        view, raw_box = parse_named_value(value)
        boxes[view] = parse_box(raw_box)
    for value in mask_values:
        view, raw_path = parse_named_value(value)
        boxes[view] = bbox_from_mask_image(Path(raw_path))
    for value in image_values:
        view, raw_path = parse_named_value(value)
        boxes[view] = resolve_box(
            explicit_box=None,
            mask_path=None,
            image_path=raw_path,
            prompt=args.sam_prompt,
            sam_endpoint=args.sam_endpoint,
            image_box_mode=args.image_box_mode,
        )
    return boxes


def resolve_multiview_calibration_measurements(
    args: argparse.Namespace,
    default_character_box: Box,
) -> list[dict[str, Any]]:
    current_boxes = resolve_named_box_map(
        args.current_view_box,
        args.current_view_mask,
        args.current_view_image,
        args,
    )
    target_boxes = resolve_named_box_map(
        args.target_view_box,
        args.target_view_mask,
        args.target_view_image,
        args,
    )
    character_boxes = {
        view: parse_box(raw_box)
        for view, raw_box in (parse_named_value(value) for value in args.view_character_box)
    }

    all_views = sorted(set(current_boxes) | set(target_boxes))
    if not all_views:
        raise ValueError("provide at least one current/target view pair")

    missing = [
        view
        for view in all_views
        if view not in current_boxes or view not in target_boxes
    ]
    if missing:
        raise ValueError(f"missing current or target measurement for views: {', '.join(missing)}")

    return [
        {
            "view": view,
            "current_box": current_boxes[view],
            "target_box": target_boxes[view],
            "character_box": character_boxes.get(view, default_character_box),
        }
        for view in all_views
    ]


def write_result(result: dict[str, Any], output_json: str | None) -> None:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output_json:
        output = Path(output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


def main() -> None:
    args = parse_args()
    if args.validation_result_json:
        validation_result = json.loads(Path(args.validation_result_json).read_text(encoding="utf-8"))
        result = {"validation": validation_result}
        if args.apply_validation_to_asset_config:
            if not args.asset_config_json or not args.asset_key:
                raise ValueError("--apply-validation-to-asset-config requires --asset-config-json and --asset-key")
            result["asset_config_update"] = apply_anchor_validation_to_asset_config(
                config_path=Path(args.asset_config_json),
                asset_key=args.asset_key,
                validation_result=validation_result,
                validation_source=args.validation_result_json,
                notes=args.validation_note,
            )
        write_result(result, args.output_json)
        return

    character_box = resolve_character_box(args)
    if args.anchor_calibration_json:
        result = validate_anchor_measurements(
            views=resolve_view_boxes(args, character_box),
            anchor_calibration=load_anchor_calibration(Path(args.anchor_calibration_json)),
            center_tolerance=args.center_tolerance,
            size_tolerance=args.size_tolerance,
            minimum_views=args.minimum_views,
        )
        if args.apply_validation_to_asset_config:
            if not args.asset_config_json or not args.asset_key:
                raise ValueError("--apply-validation-to-asset-config requires --asset-config-json and --asset-key")
            result["asset_config_update"] = apply_anchor_validation_to_asset_config(
                config_path=Path(args.asset_config_json),
                asset_key=args.asset_key,
                validation_result=result,
                validation_source=args.output_json or args.anchor_calibration_json,
                notes=args.validation_note,
            )
        write_result(result, args.output_json)
        return

    if any(
        (
            args.current_view_box,
            args.target_view_box,
            args.current_view_mask,
            args.target_view_mask,
            args.current_view_image,
            args.target_view_image,
        )
    ):
        result = multi_view_anchor_calibration_from_boxes(
            view_measurements=resolve_multiview_calibration_measurements(args, character_box),
            asset_key=args.asset_key,
            category=args.category,
            source=args.source,
            anchor_name=args.anchor_name,
            primary_view=args.primary_view,
        )
        write_result(result, args.output_json)
        return

    qwen_metadata = None
    qwen_target_image = None
    if args.qwen_workflow_json:
        prepared_workflow, qwen_metadata, _staged_source = prepare_qwen_edit_from_args(args)
        qwen_metadata, qwen_target_image = maybe_run_qwen_edit(prepared_workflow, qwen_metadata, args)

    target_image = str(qwen_target_image) if qwen_target_image else args.target_image
    if args.qwen_workflow_json and not args.qwen_run and not target_image and not args.target_box and not args.target_mask:
        raise ValueError("provide --target-image/--target-box/--target-mask or use --qwen-run to measure a Qwen edit")
    current_overrides = {}
    if args.current_overrides_from_asset_config:
        if not args.asset_config_json or not args.asset_key:
            raise ValueError("--current-overrides-from-asset-config requires --asset-config-json and --asset-key")
        current_overrides.update(load_asset_fit_overrides(Path(args.asset_config_json), args.asset_key))
    current_overrides.update(load_overrides(Path(args.current_overrides_json) if args.current_overrides_json else None))
    if args.measurement_mode == "mask-registration":
        if args.current_box or args.target_box or args.current_mask or args.target_mask:
            raise ValueError("--measurement-mode mask-registration requires current/target images")
        if not args.current_image or not target_image:
            raise ValueError("--measurement-mode mask-registration requires --current-image and --target-image or --qwen-run")
        current_detection = sam31_segment_mask(
            Path(args.current_image),
            args.sam_prompt,
            endpoint=args.sam_endpoint,
        )
        target_detection = sam31_segment_mask(
            Path(target_image),
            args.sam_prompt,
            endpoint=args.sam_endpoint,
        )
        result = mask_registered_fit_overrides(
            current_mask=current_detection["mask"],
            target_mask=target_detection["mask"],
            character_box=character_box,
            current_overrides=current_overrides,
            asset_key=args.asset_key,
            category=args.category,
            source=args.source,
            anchor_name=args.anchor_name,
            center_correction_gain=args.center_correction_gain,
            size_correction_gain=args.size_correction_gain,
            rotation_correction_gain=args.rotation_correction_gain,
            min_target_size_ratio=args.min_target_size_ratio,
            max_target_size_ratio=args.max_target_size_ratio,
        )
        result["sam_masks"] = {
            "current": {"box": [rounded(value, 2) for value in current_detection["box"]], "score": current_detection["score"]},
            "target": {"box": [rounded(value, 2) for value in target_detection["box"]], "score": target_detection["score"]},
        }
    else:
        current_box = resolve_box(
            args.current_box,
            args.current_mask,
            args.current_image,
            args.sam_prompt,
            args.sam_endpoint,
            args.image_box_mode,
        )
        target_box = resolve_box(
            args.target_box,
            args.target_mask,
            target_image,
            args.sam_prompt,
            args.sam_endpoint,
            args.image_box_mode,
        )
        result = calibrated_fit_overrides(
            current_box=current_box,
            target_box=target_box,
            character_box=character_box,
            current_overrides=current_overrides,
            asset_key=args.asset_key,
            category=args.category,
            source=args.source,
            anchor_name=args.anchor_name,
            center_correction_gain=args.center_correction_gain,
            size_correction_gain=args.size_correction_gain,
            min_target_size_ratio=args.min_target_size_ratio,
            max_target_size_ratio=args.max_target_size_ratio,
        )
    if qwen_metadata:
        if target_image and "target_image" not in qwen_metadata:
            qwen_metadata["target_image"] = target_image
        result["qwen_edit"] = qwen_metadata
    if args.apply_to_asset_config:
        if not args.asset_config_json or not args.asset_key:
            raise ValueError("--apply-to-asset-config requires --asset-config-json and --asset-key")
        result["asset_config_update"] = apply_calibration_to_asset_config(
            config_path=Path(args.asset_config_json),
            asset_key=args.asset_key,
            calibration_result=result,
            calibration_source=args.output_json or args.source,
            method=args.calibration_method or args.source,
        )
    write_result(result, args.output_json)


if __name__ == "__main__":
    main()
