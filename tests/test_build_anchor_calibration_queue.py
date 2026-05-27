import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_anchor_calibration_queue import (
    build_anchor_calibration_queue,
    calibration_state,
    target_anchor_name_for_asset,
)


class BuildAnchorCalibrationQueueTests(unittest.TestCase):
    def test_target_anchor_names_are_more_specific_than_category_defaults(self):
        self.assertEqual(
            target_anchor_name_for_asset({"title": "Wizard Hat", "category": "head_face"}),
            "head_face:hat_top",
        )
        self.assertEqual(
            target_anchor_name_for_asset({"title": "Pixel Glasses", "category": "head_face"}),
            "head_face:eye_line",
        )
        self.assertEqual(
            target_anchor_name_for_asset({"title": "Bowtie", "category": "neck_chest"}),
            "neck_chest:collar_center",
        )
        self.assertEqual(
            target_anchor_name_for_asset({"title": "Backpack", "category": "torso_back"}),
            "torso_back:back_center",
        )
        self.assertEqual(
            target_anchor_name_for_asset(
                {
                    "id": "poly-pizza-backpack-j-toastie",
                    "title": "Backpack",
                    "category": "torso_back",
                }
            ),
            "torso_back:back_center",
        )

    def test_calibration_state_uses_validation_before_fit_overrides(self):
        self.assertEqual(
            calibration_state(
                {
                    "fit_overrides": {"target_size_ratio": 0.1},
                    "anchor_calibration": {
                        "method": "qwen-image-edit-2509+sam31-iterative-damped",
                        "validation": {"status": "ok"},
                    },
                }
            ),
            "validated",
        )
        self.assertEqual(
            calibration_state(
                {
                    "fit_overrides": {"target_size_ratio": 0.1},
                    "anchor_calibration": {
                        "method": "sam31-profile-suggestion-multibase-validation",
                        "validation": {"status": "ok"},
                    },
                }
            ),
            "needs-qwen-sam-calibration",
        )
        self.assertEqual(
            calibration_state({"anchor_calibration": {"validation": {"status": "review"}}}),
            "validate-existing-calibration",
        )
        self.assertEqual(
            calibration_state({"fit_overrides": {"target_size_ratio": 0.1}}),
            "validate-existing-fit",
        )
        self.assertEqual(calibration_state({}), "needs-calibration")

    def test_queue_prioritizes_unvalidated_fix_assets_and_finds_render_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_dir = root / "outputs" / "batch" / "crown_pose_renders"
            render_dir.mkdir(parents=True)
            (render_dir / "pose_portrait_0009.png").write_bytes(b"png")
            config_path = root / "assets.json"
            combined_path = root / "combined.json"
            config_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "id": "poly-pizza-bowtie-jeremy",
                                "title": "Bowtie",
                                "category": "neck_chest",
                                "quality": {"status": "ship"},
                                "output_path": "input/outfits/poly_pizza/bowtie_jeremy.glb",
                                "fit_overrides": {"target_size_ratio": 0.1},
                                "anchor_calibration": {
                                    "method": "qwen-image-edit-2509+sam31-iterative-damped",
                                    "validation": {"status": "ok"},
                                },
                            },
                            {
                                "id": "poly-pizza-crown-quaternius",
                                "title": "Crown",
                                "category": "head_face",
                                "quality": {"status": "fix"},
                                "output_path": "input/outfits/poly_pizza/crown_quaternius.glb",
                                "fit_overrides": {"anchor": "hat_top", "target_size_ratio": 0.12},
                            },
                            {
                                "id": "poly-pizza-backpack-quaternius",
                                "title": "Backpack",
                                "category": "torso_back",
                                "output_path": "input/outfits/poly_pizza/backpack_quaternius.glb",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            combined_path.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "crown-demo",
                                "metadata": {"tags": ["crown-quaternius", "head-face"]},
                                "environment": {
                                    "OUTFIT_MODEL": "/workspace/input/outfits/poly_pizza/crown_quaternius.glb",
                                    "RENDER_DIR": "/workspace/outputs/batch/crown_pose_renders",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = build_anchor_calibration_queue(
                asset_config_path=config_path,
                combined_result_path=combined_path,
                workspace_root=root,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["asset_count"], 3)
        self.assertEqual(result["summary"]["validated_count"], 1)
        self.assertEqual(result["summary"]["work_item_count"], 2)
        self.assertEqual(result["work_items"][0]["asset_key"], "crown-quaternius")
        self.assertEqual(result["work_items"][0]["calibration_state"], "validate-existing-fit")
        self.assertEqual(result["work_items"][0]["target_anchor_name"], "head_face:hat_top")
        self.assertEqual(result["work_items"][0]["render_examples"][0]["job_id"], "crown-demo")
        self.assertTrue(result["work_items"][0]["render_examples"][0]["pose_renders"][0].endswith("pose_portrait_0009.png"))
        self.assertIn(
            "--qwen-device-map UnetLoaderGGUFMultiGPU=cuda:0",
            result["work_items"][0]["calibration_command_template"],
        )
        self.assertEqual(result["work_items"][1]["asset_key"], "backpack-quaternius")
        self.assertEqual(result["work_items"][1]["target_anchor_name"], "torso_back:back_center")


if __name__ == "__main__":
    unittest.main()
