#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accessory_visual_calibration import sam31_segment_mask
from scripts.blender_silhouette_fit import mask_quality


def mask_image(mask: Any) -> Image.Image:
    return Image.fromarray((np.asarray(mask, dtype=np.uint8) * 255), mode="L")


def union_mask(masks: Sequence[Any]) -> np.ndarray:
    if not masks:
        raise ValueError("at least one mask is required")
    union = np.zeros_like(np.asarray(masks[0], dtype=bool), dtype=bool)
    for mask in masks:
        arr = np.asarray(mask, dtype=bool)
        if arr.shape != union.shape:
            raise ValueError("all SAM masks must have matching dimensions")
        union |= arr
    return union


def overlay_mask(image_path: Path, mask: Any, color: tuple[int, int, int]) -> Image.Image:
    base = Image.open(image_path).convert("RGBA")
    mask_img = mask_image(mask).resize(base.size)
    overlay = Image.new("RGBA", base.size, (*color, 0))
    overlay.putalpha(mask_img.point(lambda value: 125 if value else 0))
    return Image.alpha_composite(base, overlay).convert("RGB")


def fit_to_cell(image: Image.Image, width: int, height: int) -> Image.Image:
    fitted = image.convert("RGB")
    fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def build_review_sheet(cells: list[tuple[str, Image.Image]], output_path: Path) -> None:
    cell_w, cell_h, label_h = 260, 360, 32
    cols = 3
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(cells):
        x = (index % cols) * cell_w
        y = (index // cols) * (cell_h + label_h)
        draw.rectangle([x, y, x + cell_w - 1, y + label_h - 1], fill=(245, 245, 245), outline=(210, 210, 210))
        draw.text((x + 8, y + 9), label, fill=(0, 0, 0))
        sheet.paste(fit_to_cell(image, cell_w, cell_h), (x, y + label_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def build_complete_target_mask(
    image_path: Path,
    prompts: Sequence[str],
    output_dir: Path,
    *,
    endpoint: str,
    confidence_threshold: float,
    expected_min_bbox_aspect: float | None,
    target_bbox_aspect: float | None = None,
    bbox_aspect_tolerance: float = 0.25,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    detections = []
    masks = []
    cells: list[tuple[str, Image.Image]] = [("target image", Image.open(image_path).convert("RGB"))]

    for index, prompt in enumerate(prompts):
        try:
            detection = sam31_segment_mask(
                image_path,
                prompt,
                endpoint=endpoint,
                confidence_threshold=confidence_threshold,
            )
        except Exception as exc:  # noqa: BLE001 - every prompt is an independent target-mask attempt.
            detections.append({"prompt": prompt, "status": "error", "error": str(exc)})
            continue
        mask = detection["mask"]
        masks.append(mask)
        mask_path = output_dir / f"mask_{index:02d}_{slug(prompt)}.png"
        overlay_path = output_dir / f"overlay_{index:02d}_{slug(prompt)}.png"
        mask_image(mask).save(mask_path)
        overlay_mask(image_path, mask, (32, 180, 255)).save(overlay_path)
        quality = mask_quality(np.asarray(mask, dtype=bool).tolist())
        aspect_error = None
        selected = True
        if target_bbox_aspect is not None:
            aspect = quality.get("bbox_aspect")
            aspect_error = abs(float(aspect) - target_bbox_aspect) if aspect is not None else None
            selected = aspect_error is not None and aspect_error <= bbox_aspect_tolerance
        detections.append(
            {
                "status": "ok",
                "prompt": prompt,
                "score": detection["score"],
                "box": detection["box"],
                "mask": str(mask_path),
                "overlay": str(overlay_path),
                "quality": quality,
                "template_aspect_error": round(aspect_error, 6) if aspect_error is not None else None,
                "selected_for_union": selected,
            }
        )
        cells.append((f"{prompt} mask", Image.open(mask_path).convert("RGB")))

    if not masks:
        raise ValueError("SAM did not return any usable masks for the requested prompts")

    selected_masks = [
        mask
        for mask, detection in zip(masks, [item for item in detections if item.get("status") == "ok"])
        if detection.get("selected_for_union", True)
    ]
    if not selected_masks:
        ok_detections = [item for item in detections if item.get("status") == "ok"]
        best = min(ok_detections, key=lambda item: float(item.get("template_aspect_error") or 999.0))
        selected_masks = [masks[ok_detections.index(best)]]
        best["selected_for_union"] = True
        best["selection_reason"] = "best-template-aspect-fallback"

    combined = union_mask(selected_masks)
    union_path = output_dir / "target_mask_union.png"
    union_overlay_path = output_dir / "target_mask_union_overlay.png"
    mask_image(combined).save(union_path)
    overlay_mask(image_path, combined, (255, 64, 32)).save(union_overlay_path)
    union_quality = mask_quality(combined.tolist(), expected_min_bbox_aspect=expected_min_bbox_aspect)
    cells.extend(
        [
            ("union mask", Image.open(union_path).convert("RGB")),
            ("union overlay", Image.open(union_overlay_path).convert("RGB")),
        ]
    )
    sheet_path = output_dir / "complete_target_mask_review_sheet.png"
    build_review_sheet(cells, sheet_path)
    report = {
        "status": "ok",
        "image": str(image_path),
        "endpoint": endpoint,
        "prompts": list(prompts),
        "target_bbox_aspect": target_bbox_aspect,
        "bbox_aspect_tolerance": bbox_aspect_tolerance,
        "detections": detections,
        "union_mask": str(union_path),
        "union_overlay": str(union_overlay_path),
        "union_quality": union_quality,
        "review_sheet": str(sheet_path),
    }
    (output_dir / "complete_target_mask.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "prompt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a complete target mask by unioning SAM masks from multiple prompts.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sam-endpoint", default="http://127.0.0.1:8105")
    parser.add_argument("--confidence-threshold", type=float, default=0.25)
    parser.add_argument("--expected-min-bbox-aspect", type=float)
    parser.add_argument("--target-bbox-aspect", type=float)
    parser.add_argument("--bbox-aspect-tolerance", type=float, default=0.25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_complete_target_mask(
        Path(args.image),
        args.prompt,
        Path(args.output_dir),
        endpoint=args.sam_endpoint,
        confidence_threshold=args.confidence_threshold,
        expected_min_bbox_aspect=args.expected_min_bbox_aspect,
        target_bbox_aspect=args.target_bbox_aspect,
        bbox_aspect_tolerance=args.bbox_aspect_tolerance,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
