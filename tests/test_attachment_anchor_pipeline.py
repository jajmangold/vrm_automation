import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.attachment_anchor_pipeline import build_pipeline, parse_args, workspace_path


class AttachmentAnchorPipelineTests(unittest.TestCase):
    def test_workspace_path_maps_repo_relative_paths(self):
        self.assertEqual(workspace_path("outputs/demo.blend"), "/workspace/outputs/demo.blend")

    def test_dry_run_plan_connects_profile_mask_and_silhouette_fit(self):
        args = parse_args(
            [
                "--profile-id",
                "neck_chest.tie",
                "--source-blend",
                "outputs/batch/source.blend",
                "--object-name",
                "outfit_external_necktie_jeremy_01",
                "--qwen-target-image",
                "outputs/calibration/qwen.png",
                "--lower-bounds",
                "-0.1,-0.4,1.0,-0.2,-0.2,-0.2,0.03",
                "--upper-bounds",
                "0.1,-0.2,1.2,0.2,0.2,0.2,0.06",
                "--run-id",
                "unit-pipeline",
            ]
        )

        plan = build_pipeline(args)
        steps = {step["name"]: step for step in plan["steps"]}

        self.assertEqual(plan["profile"]["id"], "neck_chest.tie")
        self.assertIn("sam-target-mask", steps)
        self.assertIn("blender-silhouette-fit", steps)
        self.assertIn("scripts/build_complete_target_mask.py", steps["sam-target-mask"]["command"])
        self.assertIn("scripts/blender_silhouette_fit.py", steps["blender-silhouette-fit"]["command"])
        self.assertTrue(any(value.startswith("--lower-bounds=") for value in steps["blender-silhouette-fit"]["command"]))
        self.assertTrue(any(value.startswith("--upper-bounds=") for value in steps["blender-silhouette-fit"]["command"]))
        self.assertEqual(
            steps["blender-silhouette-fit"]["opencv_role"],
            "metrics only; object movement is real Blender transform optimization",
        )

    def test_reviewed_target_mask_skips_sam_stage(self):
        args = parse_args(
            [
                "--profile-id",
                "neck_chest.tie",
                "--source-blend",
                "outputs/batch/source.blend",
                "--object-name",
                "outfit_external_necktie_jeremy_01",
                "--target-mask",
                "outputs/calibration/target_mask.png",
            ]
        )

        plan = build_pipeline(args)
        sam_step = [step for step in plan["steps"] if step["name"] == "sam-target-mask"][0]

        self.assertEqual(sam_step["status"], "provided")
        self.assertNotIn("command", sam_step)


if __name__ == "__main__":
    unittest.main()
