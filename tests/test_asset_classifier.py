import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.asset_classifier import classify_asset, placement_profile


class AssetClassifierTests(unittest.TestCase):
    def test_backpack_and_bag_use_torso_back_profile(self):
        for name in ("backpack_quaternius.glb", "poly-pizza-bag-quaternius"):
            classified = classify_asset(name)
            profile = placement_profile(classified["category"])

            self.assertEqual(classified["category"], "torso_back")
            self.assertEqual(profile["scale_axis"], "height")
            self.assertEqual(profile["surface"], "back")
            self.assertEqual(profile["bind_roles"], ["hips", "spine", "chest"])
            self.assertEqual(profile["fit_scope"], "torso")

    def test_necklace_uses_neck_chest_profile(self):
        classified = classify_asset("necklace_quaternius.glb")
        profile = placement_profile(classified["category"])

        self.assertEqual(classified["category"], "neck_chest")
        self.assertGreater(profile["vertical_center_ratio"], 0.65)
        self.assertEqual(profile["bind_roles"], ["spine", "chest", "neck"])
        self.assertEqual(profile["weighting_mode"], "upper-torso-neck")

    def test_bowtie_keyword_wins_before_generic_tie(self):
        classified = classify_asset("bowtie_jeremy.glb")

        self.assertEqual(classified["category"], "neck_chest")
        self.assertEqual(classified["matched_keyword"], "bowtie")

    def test_pixel_glasses_use_head_face_width_scaling(self):
        classified = classify_asset("pixel_glasses_ipoly3d.glb")
        profile = placement_profile(classified["category"])

        self.assertEqual(classified["category"], "head_face")
        self.assertEqual(profile["scale_axis"], "width")
        self.assertEqual(profile["target_bone_role"], "head")
        self.assertEqual(profile["bind_roles"], ["head"])
        self.assertLessEqual(profile["target_size_ratio"], 0.24)
        self.assertGreaterEqual(profile["vertical_center_ratio"], 0.89)
        self.assertLessEqual(profile["surface_offset_ratio"], 0.2)

    def test_more_wearable_head_assets_use_head_face_profile(self):
        for name in ("Monocle", "Headphones", "Fedora"):
            with self.subTest(name=name):
                self.assertEqual(classify_asset(name)["category"], "head_face")

    def test_handheld_assets_use_hand_profile(self):
        classified = classify_asset("leather_briefcase.glb")
        profile = placement_profile(classified["category"])

        self.assertEqual(classified["category"], "hand_held")
        self.assertEqual(profile["target_bone_role"], "right_hand")
        self.assertEqual(profile["bind_roles"], ["right_hand"])
        self.assertEqual(profile["fit_scope"], "hand-held")

    def test_explicit_category_overrides_name_heuristic(self):
        classified = classify_asset("bag.glb", explicit_category="head-face")
        profile = placement_profile(classified["category"])

        self.assertEqual(classified["category"], "head_face")
        self.assertEqual(classified["confidence"], "explicit")
        self.assertEqual(profile["weighting_mode"], "single-bone")

    def test_unknown_assets_fall_back_to_visual_review(self):
        classified = classify_asset("abstract_prop.glb")
        profile = placement_profile(classified["category"])

        self.assertEqual(classified["category"], "unknown")
        self.assertEqual(profile["fit_scope"], "visual-review")
        self.assertEqual(profile["bind_roles"], ["spine"])


if __name__ == "__main__":
    unittest.main()
