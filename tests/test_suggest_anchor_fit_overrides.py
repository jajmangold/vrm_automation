import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.suggest_anchor_fit_overrides import (
    TARGET_PROFILES,
    suggest_fit_overrides,
)


class SuggestAnchorFitOverridesTests(unittest.TestCase):
    def test_suggests_shrinking_oversized_glasses_without_mutating_catalog(self):
        result = suggest_fit_overrides(
            measurement={
                "asset_key": "glasses-jeremy",
                "target_anchor_name": "head_face:eye_line",
                "measurement": {
                    "center_ratio": {"x": 0.3828, "y": 0.4376},
                    "size_ratio": {"width": 0.6278, "height": 0.2446},
                },
            },
            current_overrides={
                "scale_axis": "width",
                "target_size_ratio": 0.22,
                "vertical_center_ratio": 0.9,
            },
            center_correction_gain=0.42,
            horizontal_correction_gain=0.0,
        )

        self.assertEqual(result["asset_key"], "glasses-jeremy")
        self.assertEqual(result["target_profile"], TARGET_PROFILES["head_face:eye_line"])
        self.assertAlmostEqual(result["suggested_fit_overrides"]["target_size_ratio"], 0.1472, places=4)
        self.assertAlmostEqual(result["suggested_fit_overrides"]["vertical_center_ratio"], 0.9032, places=4)
        self.assertNotIn("horizontal_center_offset_ratio", result["suggested_fit_overrides"])
        self.assertEqual(result["review_warnings"], [])

    def test_flags_large_hat_recentering_for_qwen_review(self):
        result = suggest_fit_overrides(
            measurement={
                "asset_key": "crown-quaternius",
                "target_anchor_name": "head_face:hat_top",
                "measurement": {
                    "center_ratio": {"x": 0.3066, "y": 0.2543},
                    "size_ratio": {"width": 0.6137, "height": 0.5032},
                },
            },
            current_overrides={
                "anchor": "hat_top",
                "scale_axis": "height",
                "target_size_ratio": 0.13,
                "vertical_center_ratio": 0.965,
            },
            center_correction_gain=0.42,
            horizontal_correction_gain=0.0,
        )

        self.assertAlmostEqual(result["suggested_fit_overrides"]["target_size_ratio"], 0.062, places=4)
        self.assertAlmostEqual(result["suggested_fit_overrides"]["vertical_center_ratio"], 1.0046, places=4)
        self.assertNotIn("horizontal_center_offset_ratio", result["suggested_fit_overrides"])
        self.assertIn("large-horizontal-correction", result["review_warnings"])

    def test_clamps_collar_center_suggestions_to_neck_chest_band(self):
        result = suggest_fit_overrides(
            measurement={
                "asset_key": "necktie-jeremy",
                "target_anchor_name": "neck_chest:collar_center",
                "measurement": {
                    "center_ratio": {"x": 0.431, "y": 0.897},
                    "size_ratio": {"width": 0.1572, "height": 0.2026},
                },
            },
            current_overrides={
                "category": "neck_chest",
                "scale_axis": "height",
                "target_size_ratio": 0.12,
                "vertical_center_ratio": 0.74,
            },
            center_correction_gain=0.42,
            horizontal_correction_gain=0.0,
        )

        self.assertEqual(result["suggested_fit_overrides"]["vertical_center_ratio"], 0.84)
        self.assertIn("neck-chest-vertical-clamp", result["review_warnings"])

    def test_clamps_large_torso_back_size_suggestions(self):
        result = suggest_fit_overrides(
            measurement={
                "asset_key": "backpack-quaternius",
                "target_anchor_name": "torso_back:back_center",
                "measurement": {
                    "center_ratio": {"x": 0.5352, "y": 0.6055},
                    "size_ratio": {"width": 0.1016, "height": 0.1138},
                },
            },
            current_overrides={
                "category": "torso_back",
                "scale_axis": "height",
                "target_size_ratio": 0.16,
                "vertical_center_ratio": 0.57,
            },
            center_correction_gain=0.42,
            horizontal_correction_gain=0.0,
        )

        self.assertEqual(result["suggested_fit_overrides"]["target_size_ratio"], 0.32)
        self.assertIn("torso-back-size-clamp", result["review_warnings"])


if __name__ == "__main__":
    unittest.main()
