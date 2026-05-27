import unittest

from scripts.silhouette_pose_optimizer import (
    PoseBounds,
    bbox_size_error,
    mask_centroid,
    mask_iou,
    optimize_pose,
    silhouette_score,
)


def rect_mask(width: int, height: int, box: tuple[int, int, int, int]) -> list[list[int]]:
    x1, y1, x2, y2 = box
    return [[1 if x1 <= x < x2 and y1 <= y < y2 else 0 for x in range(width)] for y in range(height)]


class SilhouettePoseOptimizerTests(unittest.TestCase):
    def test_mask_metrics_measure_overlap_and_shape_error(self):
        target = rect_mask(16, 16, (4, 4, 10, 12))
        shifted = rect_mask(16, 16, (6, 4, 12, 12))

        self.assertAlmostEqual(mask_iou(target, target), 1.0)
        self.assertLess(mask_iou(shifted, target), 1.0)
        self.assertEqual(mask_centroid(target), (6.5, 7.5))
        self.assertEqual(bbox_size_error(target, target), 0.0)

    def test_silhouette_score_rewards_iou_and_penalizes_centroid(self):
        target = rect_mask(16, 16, (4, 4, 10, 12))
        shifted = rect_mask(16, 16, (6, 4, 12, 12))

        perfect = silhouette_score(target, target)
        imperfect = silhouette_score(shifted, target)

        self.assertGreater(perfect["score"], imperfect["score"])
        self.assertEqual(perfect["iou"], 1.0)

    def test_optimizer_fits_synthetic_pose_without_gradients(self):
        target_x = 0.37
        target_y = -0.22

        def objective(pose: list[float]) -> float:
            return ((pose[0] - target_x) ** 2) + ((pose[1] - target_y) ** 2)

        result = optimize_pose(
            objective,
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            PoseBounds(
                lower=[-1, -1, -1, -0.5, -0.5, -0.5, 0.5],
                upper=[1, 1, 1, 0.5, 0.5, 0.5, 1.5],
            ),
            population_size=24,
            generations=18,
            sigma=0.3,
            seed=3,
        )

        pose = result["pose"]
        self.assertLess(abs(pose[0] - target_x), 0.08)
        self.assertLess(abs(pose[1] - target_y), 0.08)
        self.assertIn(result["method"], {"cma-es", "evolutionary-search"})


if __name__ == "__main__":
    unittest.main()
