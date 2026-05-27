#!/usr/bin/env python3
"""Save Qwen edit and SAM mask review artifacts for placement calibration runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from scripts.accessory_visual_calibration import mask_registered_fit_overrides, sam31_segment_mask


def mask_image(mask: Any) -> Image.Image:
    return Image.fromarray((np.asarray(mask, dtype=np.uint8) * 255), mode="L")


def overlay_mask(image_path: Path, mask: Any, color: tuple[int, int, int]) -> Image.Image:
    base = Image.open(image_path).convert("RGBA")
    mask_img = mask_image(mask).resize(base.size)
    overlay = Image.new("RGBA", base.size, (*color, 0))
    alpha = mask_img.point(lambda value: 120 if value else 0)
    overlay.putalpha(alpha)
    return Image.alpha_composite(base, overlay).convert("RGB")


def fit_to_cell(image: Image.Image, width: int, height: int) -> Image.Image:
    fitted = image.convert("RGB")
    fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def draw_box(image_path: Path, box: list[float], color: tuple[int, int, int]) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle([round(value) for value in box], outline=color, width=4)
    return image


def review_run(calibration_path: Path, prompt: str, endpoint: str, output_dir: Path) -> dict[str, Any]:
    data = json.loads(calibration_path.read_text(encoding="utf-8"))
    qwen = data.get("qwen_edit") or {}
    source_image = Path(qwen.get("source_image") or data.get("source_image") or "")
    target_image = Path(qwen.get("target_image") or data.get("target_image") or "")
    if not source_image.exists():
        raise FileNotFoundError(source_image)
    if not target_image.exists():
        raise FileNotFoundError(target_image)

    slug = calibration_path.stem
    run_dir = output_dir / slug
    run_dir.mkdir(parents=True, exist_ok=True)

    current = sam31_segment_mask(source_image, prompt, endpoint=endpoint)
    target = sam31_segment_mask(target_image, prompt, endpoint=endpoint)
    current_mask_path = run_dir / "current_sam_mask.png"
    target_mask_path = run_dir / "target_sam_mask.png"
    current_overlay_path = run_dir / "current_sam_overlay.png"
    target_overlay_path = run_dir / "target_sam_overlay.png"
    current_box_path = run_dir / "current_sam_box.png"
    target_box_path = run_dir / "target_sam_box.png"
    mask_image(current["mask"]).save(current_mask_path)
    mask_image(target["mask"]).save(target_mask_path)
    overlay_mask(source_image, current["mask"], (255, 32, 32)).save(current_overlay_path)
    overlay_mask(target_image, target["mask"], (32, 180, 255)).save(target_overlay_path)
    draw_box(source_image, current["box"], (255, 32, 32)).save(current_box_path)
    draw_box(target_image, target["box"], (32, 180, 255)).save(target_box_path)

    character_box = [float(value) for value in data["character_box"]]
    fit = mask_registered_fit_overrides(
        current_mask=current["mask"],
        target_mask=target["mask"],
        character_box=character_box,
        current_overrides=data.get("fit_overrides") or {},
        asset_key=(data.get("anchor_calibration") or {}).get("asset_key", ""),
        category=(data.get("anchor_calibration") or {}).get("category", "neck_chest"),
    )

    cells = [
        ("source", Image.open(source_image)),
        ("qwen edit", Image.open(target_image)),
        ("current mask", Image.open(current_mask_path).convert("RGB")),
        ("target mask", Image.open(target_mask_path).convert("RGB")),
        ("current overlay", Image.open(current_overlay_path)),
        ("target overlay", Image.open(target_overlay_path)),
        ("current box", Image.open(current_box_path)),
        ("target box", Image.open(target_box_path)),
    ]
    cell_w, cell_h, label_h = 260, 360, 32
    sheet = Image.new("RGB", (4 * cell_w, 2 * (cell_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(cells):
        x = (index % 4) * cell_w
        y = (index // 4) * (cell_h + label_h)
        draw.rectangle([x, y, x + cell_w - 1, y + label_h - 1], fill=(245, 245, 245), outline=(210, 210, 210))
        draw.text((x + 8, y + 9), label, fill=(0, 0, 0))
        sheet.paste(fit_to_cell(image, cell_w, cell_h), (x, y + label_h))
    sheet_path = run_dir / "qwen_sam_review_sheet.png"
    sheet.save(sheet_path)

    summary = {
        "calibration": str(calibration_path),
        "prompt": prompt,
        "source_image": str(source_image),
        "target_image": str(target_image),
        "qwen_prompt": qwen.get("prompt"),
        "qwen_steps": qwen.get("steps"),
        "qwen_megapixels": qwen.get("megapixels"),
        "current_sam": {"box": current["box"], "score": current["score"], "mask": str(current_mask_path)},
        "target_sam": {"box": target["box"], "score": target["score"], "mask": str(target_mask_path)},
        "mask_registration": fit["mask_registration"],
        "fit_overrides_from_masks": fit["fit_overrides"],
        "review_sheet": str(sheet_path),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("calibrations", nargs="+")
    parser.add_argument("--prompt", default="necktie")
    parser.add_argument("--sam-endpoint", default="http://127.0.0.1:8105")
    parser.add_argument("--output-dir", default="outputs/calibration/qwen_sam_step_review")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    summaries = [
        review_run(Path(path), args.prompt, args.sam_endpoint, output_dir)
        for path in args.calibrations
    ]
    (output_dir / "summary.json").write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summaries, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
