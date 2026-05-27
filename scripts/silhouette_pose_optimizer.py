from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence


Mask = Sequence[Sequence[bool | int]]
Objective = Callable[[list[float]], float]


@dataclass(frozen=True)
class PoseBounds:
    lower: list[float]
    upper: list[float]


DEFAULT_PARAMETER_NAMES = ("x", "y", "z", "rot_x", "rot_y", "rot_z", "scale")


def clamp_vector(values: Sequence[float], bounds: PoseBounds) -> list[float]:
    return [max(low, min(high, float(value))) for value, low, high in zip(values, bounds.lower, bounds.upper)]


def mask_iou(a: Mask, b: Mask) -> float:
    intersection = 0
    union = 0
    for row_a, row_b in zip(a, b):
        for value_a, value_b in zip(row_a, row_b):
            hit_a = bool(value_a)
            hit_b = bool(value_b)
            if hit_a and hit_b:
                intersection += 1
            if hit_a or hit_b:
                union += 1
    return intersection / union if union else 1.0


def mask_centroid(mask: Mask) -> tuple[float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for y, row in enumerate(mask):
        for x, value in enumerate(row):
            if value:
                xs.append(float(x))
                ys.append(float(y))
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def mask_bbox(mask: Mask) -> tuple[int, int, int, int] | None:
    xs: list[int] = []
    ys: list[int] = []
    for y, row in enumerate(mask):
        for x, value in enumerate(row):
            if value:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def normalized_centroid_distance(a: Mask, b: Mask) -> float:
    centroid_a = mask_centroid(a)
    centroid_b = mask_centroid(b)
    if centroid_a is None or centroid_b is None:
        return 1.0
    height = max(len(a), len(b), 1)
    width = max(len(a[0]) if a else 0, len(b[0]) if b else 0, 1)
    diagonal = math.hypot(width, height)
    return math.hypot(centroid_a[0] - centroid_b[0], centroid_a[1] - centroid_b[1]) / max(diagonal, 1e-6)


def bbox_size_error(a: Mask, b: Mask) -> float:
    bbox_a = mask_bbox(a)
    bbox_b = mask_bbox(b)
    if bbox_a is None or bbox_b is None:
        return 1.0
    width_a = bbox_a[2] - bbox_a[0]
    height_a = bbox_a[3] - bbox_a[1]
    width_b = bbox_b[2] - bbox_b[0]
    height_b = bbox_b[3] - bbox_b[1]
    return (abs(width_a - width_b) / max(width_b, 1)) + (abs(height_a - height_b) / max(height_b, 1))


def silhouette_score(
    rendered_mask: Mask,
    target_mask: Mask,
    *,
    collision_penalty: float = 0.0,
    floating_penalty: float = 0.0,
    offscreen_penalty: float = 0.0,
    wrong_depth_penalty: float = 0.0,
    contour_distance: float = 0.0,
) -> dict[str, float]:
    iou = mask_iou(rendered_mask, target_mask)
    centroid = normalized_centroid_distance(rendered_mask, target_mask)
    bbox_error = bbox_size_error(rendered_mask, target_mask)
    penalty = (
        0.5 * centroid
        + 0.5 * bbox_error
        + 0.25 * contour_distance
        + 2.0 * collision_penalty
        + 1.0 * floating_penalty
        + 1.0 * offscreen_penalty
        + 1.0 * wrong_depth_penalty
    )
    score = (2.0 * iou) - penalty
    return {
        "score": round(score, 6),
        "iou": round(iou, 6),
        "centroid_distance": round(centroid, 6),
        "bbox_size_error": round(bbox_error, 6),
        "penalty": round(penalty, 6),
    }


def optimize_pose(
    objective: Objective,
    initial_pose: Sequence[float],
    bounds: PoseBounds,
    *,
    population_size: int = 32,
    generations: int = 24,
    sigma: float = 0.25,
    seed: int = 13,
) -> dict[str, object]:
    try:
        return optimize_pose_with_cma(
            objective,
            initial_pose,
            bounds,
            population_size=population_size,
            generations=generations,
            sigma=sigma,
            seed=seed,
        )
    except ModuleNotFoundError:
        return optimize_pose_with_evolutionary_search(
            objective,
            initial_pose,
            bounds,
            population_size=population_size,
            generations=generations,
            sigma=sigma,
            seed=seed,
        )


def optimize_pose_with_cma(
    objective: Objective,
    initial_pose: Sequence[float],
    bounds: PoseBounds,
    *,
    population_size: int,
    generations: int,
    sigma: float,
    seed: int,
) -> dict[str, object]:
    import cma  # type: ignore

    options = {
        "bounds": [bounds.lower, bounds.upper],
        "popsize": population_size,
        "seed": seed,
        "maxiter": generations,
        "verb_disp": 0,
        "verbose": -9,
    }
    es = cma.CMAEvolutionStrategy(clamp_vector(initial_pose, bounds), sigma, options)
    evaluations = 0
    while not es.stop():
        candidates = [clamp_vector(candidate, bounds) for candidate in es.ask()]
        losses = [objective(candidate) for candidate in candidates]
        evaluations += len(candidates)
        es.tell(candidates, losses)
    return {
        "method": "cma-es",
        "pose": clamp_vector(es.result.xbest, bounds),
        "loss": float(es.result.fbest),
        "evaluations": evaluations,
    }


def optimize_pose_with_evolutionary_search(
    objective: Objective,
    initial_pose: Sequence[float],
    bounds: PoseBounds,
    *,
    population_size: int,
    generations: int,
    sigma: float,
    seed: int,
) -> dict[str, object]:
    rng = random.Random(seed)
    center = clamp_vector(initial_pose, bounds)
    spread = [max((high - low) * sigma, 1e-6) for low, high in zip(bounds.lower, bounds.upper)]
    best_pose = center
    best_loss = objective(best_pose)
    evaluations = 1

    for _generation in range(generations):
        candidates = [best_pose]
        while len(candidates) < population_size:
            candidate = [rng.gauss(value, width) for value, width in zip(center, spread)]
            candidates.append(clamp_vector(candidate, bounds))
        scored = [(objective(candidate), candidate) for candidate in candidates]
        evaluations += len(scored)
        scored.sort(key=lambda item: item[0])
        if scored[0][0] < best_loss:
            best_loss, best_pose = scored[0]
        elite = [candidate for _loss, candidate in scored[: max(2, population_size // 4)]]
        center = [sum(candidate[index] for candidate in elite) / len(elite) for index in range(len(best_pose))]
        spread = [max(width * 0.72, (high - low) * 0.005) for width, low, high in zip(spread, bounds.lower, bounds.upper)]

    return {
        "method": "evolutionary-search",
        "pose": best_pose,
        "loss": float(best_loss),
        "evaluations": evaluations,
    }
