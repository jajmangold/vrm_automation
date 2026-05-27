from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accessory_visual_calibration import (  # noqa: E402
    bbox_from_foreground_image,
    normalized_measurement,
    resolve_box,
)


DEFAULT_QUEUE = Path("results/accessory_anchor_calibration_queue_latest.json")
DEFAULT_OUTPUT = Path("results/accessory_anchor_current_measurements_latest.json")


def resolve_render_path(value: str, workspace_root: Path) -> Path:
    if value.startswith("/workspace/"):
        return workspace_root / value.removeprefix("/workspace/")
    path = Path(value)
    if path.is_absolute():
        return path
    return workspace_root / path


def queue_items(
    queue: dict[str, Any],
    include_validated: bool = False,
    asset_keys: set[str] | None = None,
    max_items: int = 0,
) -> list[dict[str, Any]]:
    source_items = queue.get("all_items") if include_validated else queue.get("work_items")
    items = [item for item in (source_items or []) if isinstance(item, dict)]
    if not include_validated:
        items = [item for item in items if item.get("calibration_state") != "validated"]
    if asset_keys:
        items = [item for item in items if str(item.get("asset_key")) in asset_keys]
    if max_items > 0:
        items = items[:max_items]
    return items


def render_paths_for_item(item: dict[str, Any], workspace_root: Path, max_renders: int) -> list[tuple[str | None, Path]]:
    paths: list[tuple[str | None, Path]] = []
    for example in item.get("render_examples") or []:
        if not isinstance(example, dict):
            continue
        job_id = str(example.get("job_id") or "") or None
        for render in example.get("pose_renders") or []:
            paths.append((job_id, resolve_render_path(str(render), workspace_root)))
            if max_renders > 0 and len(paths) >= max_renders:
                return paths
    return paths


def measurement_error(item: dict[str, Any], image_path: Path | None, warning: str, job_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "review",
        "asset_key": item.get("asset_key"),
        "target_anchor_name": item.get("target_anchor_name"),
        "sam_prompt": item.get("sam_prompt"),
        "job_id": job_id,
        "image": str(image_path) if image_path else None,
        "warning": warning,
    }


def measure_render(
    item: dict[str, Any],
    image_path: Path,
    workspace_root: Path,
    image_box_mode: str,
    sam_endpoint: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    if not image_path.exists():
        return measurement_error(item, image_path, f"render image not found: {image_path}", job_id=job_id)

    try:
        character_box = bbox_from_foreground_image(image_path)
        accessory_box = resolve_box(
            explicit_box=None,
            mask_path=None,
            image_path=str(image_path),
            prompt=str(item.get("sam_prompt") or item.get("title") or item.get("asset_key") or "accessory"),
            sam_endpoint=sam_endpoint,
            image_box_mode=image_box_mode,
        )
        measurement = normalized_measurement(accessory_box, character_box)
    except Exception as exc:  # noqa: BLE001 - report per-item failures without aborting the batch.
        return measurement_error(item, image_path, str(exc), job_id=job_id)

    return {
        "status": "ok",
        "asset_key": item.get("asset_key"),
        "target_anchor_name": item.get("target_anchor_name"),
        "sam_prompt": item.get("sam_prompt"),
        "job_id": job_id,
        "image": str(image_path),
        "accessory_box": [float(value) for value in accessory_box],
        "character_box": [float(value) for value in character_box],
        "measurement": measurement,
    }


def build_measurement_report(
    queue: dict[str, Any],
    workspace_root: Path = Path("."),
    include_validated: bool = False,
    asset_keys: set[str] | None = None,
    max_items: int = 0,
    max_renders_per_item: int = 1,
    image_box_mode: str = "sam",
    sam_endpoint: str = "http://127.0.0.1:8105",
) -> dict[str, Any]:
    items = queue_items(
        queue,
        include_validated=include_validated,
        asset_keys=asset_keys,
        max_items=max_items,
    )
    measurements: list[dict[str, Any]] = []
    for item in items:
        render_paths = render_paths_for_item(item, workspace_root, max_renders_per_item)
        if not render_paths:
            measurements.append(measurement_error(item, None, "no render examples"))
            continue
        for job_id, image_path in render_paths:
            measurements.append(
                measure_render(
                    item=item,
                    image_path=image_path,
                    workspace_root=workspace_root,
                    image_box_mode=image_box_mode,
                    sam_endpoint=sam_endpoint,
                    job_id=job_id,
                )
            )

    measured_count = sum(1 for measurement in measurements if measurement.get("status") == "ok")
    review_items = [measurement for measurement in measurements if measurement.get("status") != "ok"]
    asset_count = len({str(item.get("asset_key")) for item in items if item.get("asset_key")})
    return {
        "status": "ok" if measurements and not review_items else "review",
        "source": "accessory-anchor-render-examples",
        "image_box_mode": image_box_mode,
        "sam_endpoint": sam_endpoint,
        "summary": {
            "item_count": len(items),
            "asset_count": asset_count,
            "measurement_count": len(measurements),
            "measured_count": measured_count,
            "review_count": len(review_items),
        },
        "measurements": measurements,
        "review_items": review_items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure accessory anchor placement from queued pose renders.")
    parser.add_argument("--queue-json", default=str(DEFAULT_QUEUE))
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--include-validated", action="store_true")
    parser.add_argument("--asset-key", action="append", default=[])
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--max-renders-per-item", type=int, default=1)
    parser.add_argument(
        "--image-box-mode",
        choices=("sam", "red-accessory", "sam-red-fallback"),
        default="sam",
    )
    parser.add_argument("--sam-endpoint", default="http://127.0.0.1:8105")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queue_path = Path(args.queue_json)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    report = build_measurement_report(
        queue,
        workspace_root=Path(args.workspace_root),
        include_validated=args.include_validated,
        asset_keys=set(args.asset_key),
        max_items=args.max_items,
        max_renders_per_item=args.max_renders_per_item,
        image_box_mode=args.image_box_mode,
        sam_endpoint=args.sam_endpoint,
    )
    report["queue_json"] = str(queue_path)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
