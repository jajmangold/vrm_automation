import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.placement_api import placement_assets, placement_plan, placement_suggestion


class PlacementApiTests(unittest.TestCase):
    def test_placement_assets_reports_catalog_state(self):
        result = placement_assets(ROOT / "config/poly_pizza_assets.json", include_qualities={"ship"})

        self.assertEqual(result["status"], "ok")
        self.assertIn("rough", result["profiles"])
        keys = {asset["key"] for asset in result["assets"]}
        self.assertIn("necktie-jeremy", keys)
        self.assertTrue(all(asset["quality"] == "ship" for asset in result["assets"]))
        self.assertGreaterEqual(result["placement_priorities"]["qwen-sam-recalibration-required"], 1)

    def test_placement_plan_builds_rough_qwen_sam_command_template(self):
        result = placement_plan("bowtie", config_path=ROOT / "config/poly_pizza_assets.json", profile="rough")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["profile"], "rough")
        self.assertEqual(result["asset"]["key"], "bowtie-jeremy")
        self.assertEqual(result["render"]["width"], "512")
        self.assertEqual(result["render"]["pose_frames"], "9")
        self.assertIn("Bowtie", result["qwen"]["prompt"])
        self.assertTrue(result["qwen"]["run_by_default"])
        self.assertEqual(result["qwen"]["steps"], 3)
        self.assertEqual(result["qwen"]["megapixels"], 0.25)
        self.assertIn("--image-box-mode", result["command_template"])
        self.assertIn("sam-red-fallback", result["command_template"])
        self.assertIn("--qwen-run", result["command_template"])
        self.assertIn("--qwen-steps", result["command_template"])
        self.assertIn("--qwen-megapixels", result["command_template"])

    def test_placement_plan_exposes_multiview_registered_profile(self):
        result = placement_plan("necktie", config_path=ROOT / "config/poly_pizza_assets.json", profile="multiview")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["render"]["angles"], "front,side,three_quarter,portrait")
        self.assertTrue(result["render"]["sequential_multiview"])
        self.assertEqual(result["render"]["view_sequence"], "front,side,three_quarter,portrait")
        self.assertEqual(result["render"]["zoom_levels"], "full,anchor,tight")
        self.assertTrue(result["solver"]["require_body_registration"])
        self.assertEqual(result["solver"]["observation_contract"]["registered_zoom_fields"], ["current_body_box", "target_body_box"])
        self.assertIn("sequential_rule", result["solver"]["observation_contract"])
        self.assertEqual(result["solver"]["pose_optimizer"], "blender-silhouette-cma")
        self.assertIn("scale", result["solver"]["pose_parameters"])
        self.assertIn("iou", result["solver"]["mask_scoring"])
        self.assertEqual(result["solver"]["opencv_role"], "mask metrics only; Blender optimizer moves the object")
        self.assertIn("blender-silhouette-fit", result["solver"]["optimizer_command_template"])
        self.assertIn("scripts/blender_silhouette_fit.py", result["solver"]["optimizer_command_template"])
        self.assertIn("--target-mask", result["solver"]["optimizer_command_template"])
        self.assertIn("--debug-dir", result["solver"]["optimizer_command_template"])
        self.assertIn("--output-blend", result["solver"]["optimizer_command_template"])
        self.assertIn("--scale-prior-weight", result["solver"]["optimizer_command_template"])
        self.assertIn("--area-prior-weight", result["solver"]["optimizer_command_template"])
        self.assertIn("--lock-scale-on-small-target", result["solver"]["optimizer_command_template"])
        self.assertIn("--measurement-mode", result["command_template"])
        self.assertIn("mask-registration", result["command_template"])
        self.assertEqual(result["qwen"]["steps"], 8)
        self.assertEqual(result["qwen"]["megapixels"], 0.75)

    def test_placement_suggestion_computes_fit_override_delta(self):
        result = placement_suggestion(
            {
                "asset_key": "bowtie-jeremy",
                "current_box": [120, 260, 220, 310],
                "target_box": [130, 240, 210, 280],
                "character_box": [0, 0, 400, 800],
                "center_correction_gain": 0.5,
            },
            config_path=ROOT / "config/poly_pizza_assets.json",
        )

        suggestion = result["suggestion"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["asset"]["key"], "bowtie-jeremy")
        self.assertLess(suggestion["fit_overrides"]["target_size_ratio"], 0.082)
        self.assertGreater(suggestion["fit_overrides"]["vertical_center_ratio"], 0.805)
        self.assertEqual(suggestion["anchor_calibration"]["anchor_name"], "neck_chest:collar_center")

    def test_placement_plan_rejects_unknown_profile(self):
        with self.assertRaises(ValueError):
            placement_plan("bowtie", config_path=ROOT / "config/poly_pizza_assets.json", profile="bad")


if __name__ == "__main__":
    unittest.main()
