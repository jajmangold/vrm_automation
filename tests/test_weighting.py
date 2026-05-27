import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.weighting import torso_weight_plan


BONES = {
    "hips": "J_Bip_C_Hips",
    "spine": "J_Bip_C_Spine",
    "chest": "J_Bip_C_Chest",
}

CHARACTER_BOUNDS = {
    "min": (-0.69, -0.25, 0.0),
    "max": (0.65, 0.26, 1.67),
    "center": (-0.02, 0.0, 0.835),
    "size": (1.34, 0.51, 1.67),
}


def z_at(ratio):
    return CHARACTER_BOUNDS["min"][2] + CHARACTER_BOUNDS["size"][2] * ratio


class TorsoWeightPlanTests(unittest.TestCase):
    def test_low_vertices_blend_hips_and_spine(self):
        weights = torso_weight_plan(z_at(0.48), CHARACTER_BOUNDS, BONES)

        self.assertGreater(weights["J_Bip_C_Hips"], weights.get("J_Bip_C_Chest", 0))
        self.assertGreater(weights["J_Bip_C_Spine"], 0)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_mid_vertices_favor_spine(self):
        weights = torso_weight_plan(z_at(0.57), CHARACTER_BOUNDS, BONES)

        self.assertGreater(weights["J_Bip_C_Spine"], weights["J_Bip_C_Hips"])
        self.assertGreater(weights["J_Bip_C_Spine"], weights["J_Bip_C_Chest"])
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_high_vertices_blend_spine_and_chest(self):
        weights = torso_weight_plan(z_at(0.68), CHARACTER_BOUNDS, BONES)

        self.assertGreater(weights["J_Bip_C_Chest"], weights.get("J_Bip_C_Hips", 0))
        self.assertGreater(weights["J_Bip_C_Spine"], 0)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_missing_optional_bones_falls_back_to_spine(self):
        weights = torso_weight_plan(z_at(0.68), CHARACTER_BOUNDS, {"spine": "J_Bip_C_Spine"})

        self.assertEqual(weights, {"J_Bip_C_Spine": 1.0})


if __name__ == "__main__":
    unittest.main()
