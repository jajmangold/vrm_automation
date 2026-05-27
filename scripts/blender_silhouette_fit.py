from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.silhouette_pose_optimizer import PoseBounds, mask_bbox, optimize_pose, silhouette_score


def parse_vector(value: str, expected: int) -> list[float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != expected:
        raise argparse.ArgumentTypeError(f"expected {expected} comma-separated values")
    return [float(part) for part in parts]


def load_mask_png(path: Path, *, threshold: int = 16) -> list[list[bool]]:
    try:
        from PIL import Image

        image = Image.open(path).convert("L")
        pixels = list(image.getdata())
        rows: list[list[bool]] = []
        for y in range(image.height):
            start = y * image.width
            rows.append([pixels[start + x] > threshold for x in range(image.width)])
        return rows
    except ModuleNotFoundError:
        return load_mask_png_with_blender(path, threshold=threshold)


def load_mask_png_with_blender(path: Path, *, threshold: int = 16) -> list[list[bool]]:
    import bpy

    image = bpy.data.images.load(str(path))
    try:
        width, height = image.size
        pixels = list(image.pixels)
        alpha_values = pixels[3::4]
        use_alpha = bool(alpha_values) and min(alpha_values) < 0.99
        rows: list[list[bool]] = []
        for y in range(height):
            row = []
            for x in range(width):
                index = ((height - 1 - y) * width + x) * 4
                alpha = pixels[index + 3]
                value = alpha if use_alpha else max(pixels[index], pixels[index + 1], pixels[index + 2])
                row.append(value * 255.0 > threshold)
            rows.append(row)
        return rows
    finally:
        bpy.data.images.remove(image)


def load_mask(path: Path) -> list[list[bool]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_mask = data.get("mask", data) if isinstance(data, dict) else data
        return [[bool(value) for value in row] for row in raw_mask]
    return load_mask_png(path)


def resize_mask(mask: list[list[bool]], width: int, height: int) -> list[list[bool]]:
    if not mask or not mask[0]:
        return [[False for _x in range(width)] for _y in range(height)]
    source_height = len(mask)
    source_width = len(mask[0])
    rows: list[list[bool]] = []
    for y in range(height):
        source_y = min(source_height - 1, int(y * source_height / max(height, 1)))
        row = []
        for x in range(width):
            source_x = min(source_width - 1, int(x * source_width / max(width, 1)))
            row.append(bool(mask[source_y][source_x]))
        rows.append(row)
    return rows


def union_masks(masks: Sequence[list[list[bool]]]) -> list[list[bool]]:
    if not masks:
        raise ValueError("at least one mask is required")
    height = len(masks[0])
    width = len(masks[0][0]) if height else 0
    union = [[False for _x in range(width)] for _y in range(height)]
    for mask in masks:
        if len(mask) != height or (height and len(mask[0]) != width):
            raise ValueError("all masks must have matching dimensions before union")
        for y, row in enumerate(mask):
            for x, value in enumerate(row):
                union[y][x] = union[y][x] or bool(value)
    return union


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def mask_foreground_count(mask: list[list[bool]]) -> int:
    return sum(sum(1 for value in row if value) for row in mask)


def mask_quality(mask: list[list[bool]], *, expected_min_bbox_aspect: float | None = None) -> dict:
    height = len(mask)
    width = len(mask[0]) if height else 0
    foreground = mask_foreground_count(mask)
    fraction = foreground / max(width * height, 1)
    bbox = mask_bbox(mask)
    warnings = []
    if foreground == 0:
        warnings.append("empty-target-mask")
    if fraction < 0.001:
        warnings.append("tiny-target-mask")
    if bbox is not None:
        bbox_width = bbox[2] - bbox[0]
        bbox_height = bbox[3] - bbox[1]
        if bbox_width <= 1 or bbox_height <= 1:
            warnings.append("degenerate-target-mask-bbox")
        aspect = bbox_width / max(bbox_height, 1)
        if expected_min_bbox_aspect is not None and aspect < expected_min_bbox_aspect:
            warnings.append("target-mask-too-slender-for-object")
    else:
        aspect = None
    return {
        "width": width,
        "height": height,
        "foreground_pixels": foreground,
        "foreground_fraction": round(fraction, 6),
        "bbox": list(bbox) if bbox else None,
        "bbox_aspect": round(aspect, 6) if aspect is not None else None,
        "warnings": warnings,
    }


def save_mask_pgm(path: Path, mask: list[list[bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    height = len(mask)
    width = len(mask[0]) if height else 0
    with path.open("wb") as handle:
        handle.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        for row in mask:
            handle.write(bytes(255 if value else 0 for value in row))


def set_pose(obj, pose: Sequence[float]) -> None:
    obj.location = (pose[0], pose[1], pose[2])
    obj.rotation_euler = (pose[3], pose[4], pose[5])
    obj.scale = (pose[6], pose[6], pose[6])


def object_pose(obj) -> list[float]:
    return [
        float(obj.location.x),
        float(obj.location.y),
        float(obj.location.z),
        float(obj.rotation_euler.x),
        float(obj.rotation_euler.y),
        float(obj.rotation_euler.z),
        float(obj.scale.x),
    ]


def resolve_object(name: str):
    import bpy

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"object not found: {name}")
    return obj


def render_object_mask(obj, width: int, height: int) -> list[list[bool]]:
    import bpy

    scene = bpy.context.scene
    previous_resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent)
    hidden = {other.name: other.hide_render for other in bpy.context.scene.objects}
    active = bpy.context.view_layer.objects.active
    selected = [other for other in bpy.context.selected_objects]

    try:
        for other in bpy.context.scene.objects:
            other.hide_render = other.name != obj.name
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.film_transparent = True
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            output_path = Path(handle.name)
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        rows = load_mask_png_with_blender(output_path, threshold=16)
        output_path.unlink(missing_ok=True)
        return rows
    finally:
        for other in bpy.context.scene.objects:
            if other.name in hidden:
                other.hide_render = hidden[other.name]
        scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent = previous_resolution
        bpy.ops.object.select_all(action="DESELECT")
        for other in selected:
            other.select_set(True)
        bpy.context.view_layer.objects.active = active


def offscreen_penalty(mask: list[list[bool]]) -> float:
    if not mask or not mask[0]:
        return 1.0
    height = len(mask)
    width = len(mask[0])
    edge_hits = sum(mask[0]) + sum(mask[-1])
    edge_hits += sum(row[0] for row in mask) + sum(row[-1] for row in mask)
    total_hits = sum(sum(row) for row in mask)
    if total_hits == 0:
        return 1.0
    return min(1.0, edge_hits / max(width + height, 1))


def fit_object_to_mask(
    *,
    object_name: str,
    target_mask: list[list[bool]],
    bounds: PoseBounds,
    initial_pose: Sequence[float] | None,
    width: int,
    height: int,
    population_size: int,
    generations: int,
    sigma: float,
    seed: int,
    apply: bool,
    scale_prior_weight: float = 0.0,
    area_prior_weight: float = 0.0,
    expected_min_bbox_aspect: float | None = None,
    lock_scale_on_small_target: bool = False,
    output_blend: Path | None = None,
    debug_dir: Path | None = None,
) -> dict:
    import bpy

    obj = resolve_object(object_name)
    start_pose = list(initial_pose) if initial_pose else object_pose(obj)
    target_mask = resize_mask(target_mask, width, height)
    target_quality = mask_quality(target_mask, expected_min_bbox_aspect=expected_min_bbox_aspect)
    evaluations: list[dict] = []
    best_rendered_mask: list[list[bool]] | None = None
    best_score: float | None = None
    initial_rendered_mask = render_object_mask(obj, width, height)
    initial_rendered_quality = mask_quality(initial_rendered_mask)
    if target_quality["foreground_pixels"] < initial_rendered_quality["foreground_pixels"] * 0.65:
        target_quality["warnings"].append("target-mask-smaller-than-initial-object")
    lock_scale = lock_scale_on_small_target and "target-mask-smaller-than-initial-object" in target_quality["warnings"]

    def objective(candidate: list[float]) -> float:
        nonlocal best_rendered_mask, best_score
        candidate = list(candidate)
        if lock_scale:
            candidate[6] = start_pose[6]
        set_pose(obj, candidate)
        rendered_mask = render_object_mask(obj, width, height)
        score = silhouette_score(rendered_mask, target_mask, offscreen_penalty=offscreen_penalty(rendered_mask))
        scale_prior_penalty = 0.0
        if scale_prior_weight and start_pose[6] > 0 and candidate[6] > 0:
            scale_prior_penalty = scale_prior_weight * abs(math.log(candidate[6] / start_pose[6]))
            score = {**score, "score": round(float(score["score"]) - scale_prior_penalty, 6)}
        rendered_count = mask_foreground_count(rendered_mask)
        target_count = mask_foreground_count(target_mask)
        area_prior_penalty = 0.0
        if area_prior_weight and rendered_count and target_count:
            area_prior_penalty = area_prior_weight * abs(math.log(rendered_count / target_count))
            score = {**score, "score": round(float(score["score"]) - area_prior_penalty, 6)}
        observation = {
            "pose": [round(value, 6) for value in candidate],
            "rendered_foreground_pixels": rendered_count,
            "target_foreground_pixels": target_count,
            "scale_prior_penalty": round(scale_prior_penalty, 6),
            "area_prior_penalty": round(area_prior_penalty, 6),
            **score,
        }
        evaluations.append(observation)
        if best_score is None or float(score["score"]) > best_score:
            best_score = float(score["score"])
            best_rendered_mask = rendered_mask
        return -float(score["score"])

    result = optimize_pose(
        objective,
        start_pose,
        bounds,
        population_size=population_size,
        generations=generations,
        sigma=sigma,
        seed=seed,
    )
    best_pose = [float(value) for value in result["pose"]]
    if lock_scale:
        best_pose[6] = start_pose[6]
    if apply:
        set_pose(obj, best_pose)
        if output_blend is not None:
            output_blend.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    else:
        set_pose(obj, start_pose)

    debug_paths: dict[str, str] = {}
    if debug_dir is not None:
        save_mask_pgm(debug_dir / "target_mask_resized.pgm", target_mask)
        debug_paths["target_mask_resized"] = str(debug_dir / "target_mask_resized.pgm")
        if best_rendered_mask is not None:
            save_mask_pgm(debug_dir / "best_rendered_mask.pgm", best_rendered_mask)
            debug_paths["best_rendered_mask"] = str(debug_dir / "best_rendered_mask.pgm")

    return {
        "status": "ok",
        "object_name": object_name,
        "method": result["method"],
        "initial_pose": [round(value, 6) for value in start_pose],
        "best_pose": [round(value, 6) for value in best_pose],
        "loss": round(float(result["loss"]), 6),
        "evaluations": result["evaluations"],
        "best_observation": max(evaluations, key=lambda item: item["score"]) if evaluations else None,
        "initial_observation": evaluations[0] if evaluations else None,
        "target_mask_quality": target_quality,
        "initial_rendered_mask_quality": initial_rendered_quality,
        "scale_locked": lock_scale,
        "target_foreground_pixels": target_quality["foreground_pixels"],
        "debug_paths": debug_paths,
        "output_blend": str(output_blend) if output_blend else None,
        "parameters": ["x", "y", "z", "rot_x", "rot_y", "rot_z", "scale"],
        "score_terms": [
            "iou",
            "centroid_distance",
            "bbox_size_error",
            "offscreen_penalty",
            "scale_prior_penalty",
            "area_prior_penalty",
        ],
    }


def load_union_target_mask(paths: Sequence[Path], width: int, height: int) -> list[list[bool]]:
    return union_masks([resize_mask(load_mask(path), width, height) for path in paths])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None and "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :]
    parser = argparse.ArgumentParser(description="Fit a Blender object pose to a target silhouette mask.")
    parser.add_argument("--object-name", required=True)
    parser.add_argument("--target-mask", action="append", required=True)
    parser.add_argument("--report-json", default="/workspace/results/blender_silhouette_fit.json")
    parser.add_argument("--output-blend")
    parser.add_argument("--debug-dir")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--population-size", type=int, default=32)
    parser.add_argument("--generations", type=int, default=24)
    parser.add_argument("--sigma", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--scale-prior-weight", type=float, default=0.0)
    parser.add_argument("--area-prior-weight", type=float, default=0.0)
    parser.add_argument("--expected-min-bbox-aspect", type=float)
    parser.add_argument("--lock-scale-on-small-target", action="store_true")
    parser.add_argument("--initial-pose", type=lambda value: parse_vector(value, 7))
    parser.add_argument(
        "--lower-bounds",
        type=lambda value: parse_vector(value, 7),
        default=[-1.0, -1.0, -1.0, -3.14159, -3.14159, -3.14159, 0.05],
    )
    parser.add_argument(
        "--upper-bounds",
        type=lambda value: parse_vector(value, 7),
        default=[1.0, 1.0, 1.0, 3.14159, 3.14159, 3.14159, 3.0],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    target_mask_paths = [Path(value) for value in args.target_mask]
    report_path = Path(args.report_json)
    if str(report_path).startswith("/workspace/"):
        report_path = ROOT / str(report_path).removeprefix("/workspace/")
    output_blend = Path(args.output_blend) if args.output_blend else None
    if output_blend is not None and str(output_blend).startswith("/workspace/"):
        output_blend = ROOT / str(output_blend).removeprefix("/workspace/")
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    if debug_dir is not None and str(debug_dir).startswith("/workspace/"):
        debug_dir = ROOT / str(debug_dir).removeprefix("/workspace/")
    report = fit_object_to_mask(
        object_name=args.object_name,
        target_mask=load_union_target_mask(target_mask_paths, args.width, args.height),
        bounds=PoseBounds(lower=args.lower_bounds, upper=args.upper_bounds),
        initial_pose=args.initial_pose,
        width=args.width,
        height=args.height,
        population_size=args.population_size,
        generations=args.generations,
        sigma=args.sigma,
        seed=args.seed,
        apply=args.apply,
        scale_prior_weight=args.scale_prior_weight,
        area_prior_weight=args.area_prior_weight,
        expected_min_bbox_aspect=args.expected_min_bbox_aspect,
        lock_scale_on_small_target=args.lock_scale_on_small_target,
        output_blend=output_blend,
        debug_dir=debug_dir,
    )
    save_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
