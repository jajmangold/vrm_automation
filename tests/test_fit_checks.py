import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fit_checks import outfit_fit_check


CHARACTER_BOUNDS = {
    "min": (-0.69, -0.25, 0.0),
    "max": (0.65, 0.26, 1.67),
    "center": (-0.02, 0.0, 0.835),
    "size": (1.34, 0.51, 1.67),
}


def outfit_bounds(center, size):
    cx, cy, cz = center
    sx, sy, sz = (value / 2 for value in size)
    return {
        "min": (cx - sx, cy - sy, cz - sz),
        "max": (cx + sx, cy + sy, cz + sz),
        "center": center,
        "size": size,
    }


class OutfitFitCheckTests(unittest.TestCase):
    def test_accepts_reasonable_front_surface_fit(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.17, 0.95), size=(0.16, 0.025, 0.27)),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["metrics"]["depth_zone"], "front-surface")

    def test_flags_floating_forward_outfit(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.62, 0.95), size=(0.16, 0.025, 0.27)),
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("outfit-floating-forward", result["warnings"])
        self.assertEqual(result["metrics"]["depth_zone"], "floating-forward")

    def test_flags_buried_deep_outfit(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, 0.2, 0.95), size=(0.16, 0.08, 0.27)),
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("outfit-buried-deep", result["warnings"])
        self.assertEqual(result["metrics"]["depth_zone"], "buried-deep")

    def test_flags_front_surface_penetration_before_center_burial(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.11, 0.95), size=(0.16, 0.12, 0.27)),
            scope="neck-chest",
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("outfit-surface-penetration", result["warnings"])
        self.assertEqual(result["metrics"]["depth_zone"], "surface-penetration")

    def test_accepts_back_surface_accessory_with_visible_outer_depth(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, 0.175, 0.95), size=(0.34, 0.207, 0.27)),
            surface="back",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["metrics"]["surface"], "back")
        self.assertEqual(result["metrics"]["depth_zone"], "back-surface")

    def test_flags_back_surface_accessory_buried_inside_body(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, 0.01, 0.95), size=(0.34, 0.12, 0.27)),
            surface="back",
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("outfit-buried-deep", result["warnings"])
        self.assertEqual(result["metrics"]["depth_zone"], "buried-deep")

    def test_flags_vertical_and_lateral_outliers(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(0.42, -0.17, 1.48), size=(0.16, 0.025, 0.27)),
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("outfit-lateral-offset", result["warnings"])
        self.assertIn("outfit-too-high", result["warnings"])

    def test_accepts_head_face_accessory_near_eyes(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.13, 1.45), size=(0.38, 0.26, 0.074)),
            scope="head-face",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "head-face")
        self.assertNotIn("outfit-too-high", result["warnings"])
        self.assertNotIn("outfit-depth-large", result["warnings"])

    def test_accepts_headwear_wrapping_top_of_head(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.0201, 1.6575), size=(0.368, 0.4788, 0.1754)),
            scope="headwear",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "headwear")
        self.assertNotIn("outfit-depth-large", result["warnings"])
        self.assertNotIn("outfit-too-high", result["warnings"])
        self.assertNotIn("outfit-buried-deep", result["warnings"])

    def test_flags_head_face_accessory_when_on_torso(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.13, 0.95), size=(0.38, 0.26, 0.074)),
            scope="head-face",
        )

        self.assertEqual(result["status"], "review")
        self.assertIn("outfit-too-low", result["warnings"])

    def test_accepts_neck_chest_accessory_above_torso_center(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.02, -0.12, 1.24), size=(0.2, 0.18, 0.2)),
            scope="neck-chest",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "neck-chest")

    def test_accepts_calibrated_tiny_bowtie_at_collar(self):
        result = outfit_fit_check(
            CHARACTER_BOUNDS,
            outfit_bounds(center=(-0.0219, -0.1091, 1.3853), size=(0.1313, 0.0163, 0.0453)),
            scope="neck-chest",
        )

        self.assertEqual(result["metrics"]["height_ratio"], 0.0271)
        self.assertEqual(result["metrics"]["vertical_center_ratio"], 0.8295)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
