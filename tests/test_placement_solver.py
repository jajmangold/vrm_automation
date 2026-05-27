import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.placement_api import placement_suggestion
from scripts.placement_solver import solve_placement


class PlacementSolverTests(unittest.TestCase):
    def test_solver_blends_body_relative_and_observed_scale(self):
        result = solve_placement(
            {
                "asset_key": "bowtie-jeremy",
                "category": "neck_chest",
                "current_overrides": {
                    "scale_axis": "width",
                    "target_size_ratio": 0.08,
                    "vertical_center_ratio": 0.8,
                },
                "body_metrics": {"shoulder_width": 220},
                "body_scale_weight": 0.5,
                "observations": [
                    {
                        "view": "front",
                        "current_box": [100, 300, 180, 340],
                        "target_box": [110, 280, 230, 340],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["placement_transform"]["scale"]["source"], "body-metrics+image-observations")
        self.assertAlmostEqual(result["fit_overrides"]["target_size_ratio"], 0.104, places=3)
        self.assertAlmostEqual(result["fit_overrides"]["vertical_center_ratio"], 0.8125, places=3)
        self.assertIn("horizontal_center_offset_ratio", result["fit_overrides"])

    def test_solver_uses_side_view_to_adjust_depth_offset(self):
        result = solve_placement(
            {
                "asset_key": "backpack",
                "category": "torso_back",
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.2,
                    "vertical_center_ratio": 0.6,
                    "front_offset_ratio": 0.2,
                },
                "observations": [
                    {
                        "view": "front",
                        "current_box": [150, 250, 230, 450],
                        "target_box": [150, 250, 230, 450],
                        "character_box": [0, 0, 400, 800],
                    },
                    {
                        "view": "right",
                        "current_box": [180, 250, 260, 450],
                        "target_box": [220, 250, 300, 450],
                        "character_box": [0, 0, 400, 800],
                    },
                ],
            }
        )

        self.assertAlmostEqual(result["fit_overrides"]["front_offset_ratio"], 0.3, places=3)
        self.assertAlmostEqual(result["placement_transform"]["translation_ratio"]["y_depth"], 0.1, places=3)

    def test_solver_clamps_side_depth_to_surface_safe_limit(self):
        result = solve_placement(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.14,
                    "vertical_center_ratio": 0.76,
                    "front_offset_ratio": 0.26,
                },
                "observations": [
                    {
                        "view": "front",
                        "current_box": [300, 360, 340, 500],
                        "target_box": [300, 360, 340, 500],
                        "character_box": [0, 0, 640, 960],
                    },
                    {
                        "view": "right",
                        "current_box": [300, 360, 340, 500],
                        "target_box": [620, 360, 660, 500],
                        "character_box": [0, 0, 640, 960],
                    },
                ],
            }
        )

        self.assertEqual(result["fit_overrides"]["front_offset_ratio"], 0.5)
        self.assertEqual(result["diagnostics"]["depth_unclamped_front_offset_ratio"], 0.76)
        self.assertIn("depth:front-offset-clamped:0.5", result["diagnostics"]["warnings"])

    def test_solver_uses_render_side_depth_sign(self):
        result = solve_placement(
            {
                "asset_key": "necktie",
                "category": "neck_chest",
                "current_overrides": {
                    "target_size_ratio": 0.14,
                    "vertical_center_ratio": 0.76,
                    "front_offset_ratio": 0.26,
                },
                "depth_correction_gain": 0.42,
                "observations": [
                    {
                        "view": "side",
                        "current_box": [180, 250, 260, 450],
                        "target_box": [220, 250, 300, 450],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            }
        )

        self.assertAlmostEqual(result["fit_overrides"]["front_offset_ratio"], 0.218, places=3)
        self.assertAlmostEqual(result["diagnostics"]["depth_delta_ratio"], -0.042, places=3)

    def test_solver_accepts_explicit_side_depth_sign(self):
        result = solve_placement(
            {
                "asset_key": "necktie",
                "category": "neck_chest",
                "current_overrides": {"target_size_ratio": 0.14, "front_offset_ratio": 0.2},
                "depth_correction_gain": 1.0,
                "observations": [
                    {
                        "view": "side",
                        "depth_delta_sign": 1,
                        "current_box": [180, 250, 260, 450],
                        "target_box": [220, 250, 300, 450],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            }
        )

        self.assertAlmostEqual(result["fit_overrides"]["front_offset_ratio"], 0.3, places=3)

    def test_solver_rejects_side_target_off_body(self):
        result = solve_placement(
            {
                "asset_key": "necktie",
                "category": "neck_chest",
                "current_overrides": {"target_size_ratio": 0.14, "front_offset_ratio": 0.26},
                "observations": [
                    {
                        "view": "front",
                        "current_box": [286, 570, 332, 804],
                        "target_box": [291, 591, 439, 904],
                        "character_box": [0, 298, 640, 960],
                    },
                    {
                        "view": "side",
                        "current_box": [307, 380, 348, 438],
                        "target_box": [378, 389, 411, 435],
                        "character_box": [278, 315, 358, 665],
                    },
                ],
                "max_observation_center_delta_ratio": 1.2,
            }
        )

        rejected = result["diagnostics"]["rejected_observations"]
        self.assertEqual(rejected[0]["reason"], "side-target-off-body")
        self.assertEqual(result["diagnostics"]["evidence"]["side_view_count"], 0)
        self.assertEqual(result["fit_overrides"]["front_offset_ratio"], 0.26)

    def test_solver_can_clamp_side_target_to_body_before_depth_solve(self):
        result = solve_placement(
            {
                "asset_key": "necktie",
                "category": "neck_chest",
                "current_overrides": {"target_size_ratio": 0.14, "front_offset_ratio": 0.26},
                "clamp_side_target_to_body": True,
                "side_target_center_ratio_limits": [-0.05, 0.9],
                "depth_correction_gain": 0.42,
                "observations": [
                    {
                        "view": "side",
                        "current_box": [307, 380, 348, 438],
                        "target_box": [378, 389, 411, 435],
                        "character_box": [278, 315, 358, 665],
                    },
                ],
                "max_observation_center_delta_ratio": 1.2,
            }
        )

        observation = result["observations"][0]
        self.assertEqual(observation["body_clamp"]["status"], "clamped")
        self.assertEqual(observation["body_clamp"]["clamped_center_ratio"], 0.9)
        self.assertAlmostEqual(result["fit_overrides"]["front_offset_ratio"], 0.142, places=3)

    def test_solver_does_not_use_side_depth_view_for_scale_when_front_exists(self):
        result = solve_placement(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.14,
                    "vertical_center_ratio": 0.76,
                    "front_offset_ratio": 0.26,
                },
                "observations": [
                    {
                        "view": "front",
                        "current_box": [300, 360, 340, 500],
                        "target_box": [300, 360, 340, 500],
                        "character_box": [0, 0, 640, 960],
                    },
                    {
                        "view": "right",
                        "current_box": [300, 360, 340, 500],
                        "target_box": [330, 320, 390, 740],
                        "character_box": [0, 0, 640, 960],
                    },
                ],
            }
        )

        self.assertEqual(result["fit_overrides"]["target_size_ratio"], 0.14)
        self.assertEqual(result["diagnostics"]["evidence"]["scale_view_count"], 1)

    def test_solver_carries_explicit_rotation_observation(self):
        result = solve_placement(
            {
                "asset_key": "hard-hat",
                "category": "head_face",
                "current_overrides": {"rotation_z_degrees": 90, "target_size_ratio": 0.1},
                "observations": [
                    {
                        "view": "front",
                        "current_box": [100, 100, 200, 160],
                        "target_box": [100, 100, 200, 160],
                        "character_box": [0, 0, 400, 800],
                        "rotation_delta_degrees": -12,
                    }
                ],
            }
        )

        self.assertEqual(result["fit_overrides"]["rotation_z_degrees"], 78)
        self.assertEqual(result["placement_transform"]["rotation_degrees"]["roll"], 78)

    def test_solver_carries_independent_pitch_yaw_roll_observations(self):
        result = solve_placement(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "current_overrides": {
                    "rotation_x_degrees": -5,
                    "rotation_y_degrees": 2,
                    "rotation_z_degrees": 0,
                },
                "observations": [
                    {
                        "view": "front",
                        "current_box": [100, 100, 200, 240],
                        "target_box": [100, 100, 200, 240],
                        "character_box": [0, 0, 400, 800],
                        "pitch_delta_degrees": 12,
                        "yaw_delta_degrees": -4,
                        "rotation_delta_degrees": 7,
                    }
                ],
            }
        )

        self.assertEqual(result["fit_overrides"]["rotation_x_degrees"], 7)
        self.assertEqual(result["fit_overrides"]["rotation_y_degrees"], -2)
        self.assertEqual(result["fit_overrides"]["rotation_z_degrees"], 7)
        self.assertEqual(result["placement_transform"]["rotation_degrees"]["pitch"], 7)
        self.assertEqual(result["placement_transform"]["rotation_degrees"]["yaw"], -2)
        self.assertEqual(result["placement_transform"]["rotation_degrees"]["roll"], 7)

    def test_placement_api_uses_solver_for_observation_payloads(self):
        result = placement_suggestion(
            {
                "asset_key": "bowtie-jeremy",
                "solve_3d": True,
                "body_metrics": {"shoulder_width": 220},
                "observations": [
                    {
                        "view": "front",
                        "current_box": [120, 260, 220, 310],
                        "target_box": [130, 240, 210, 280],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            },
            config_path=ROOT / "config/poly_pizza_assets.json",
        )

        self.assertEqual(result["suggestion"]["solver"], "body-relative-multiview-v1")
        self.assertIn("placement_transform", result["suggestion"])

    def test_solver_accepts_custom_rules_for_unknown_objects(self):
        result = solve_placement(
            {
                "asset_key": "magic-orb",
                "category": "hand_prop",
                "anchor_name": "right_hand:palm",
                "scale_rule": {"metric": "hand_width", "fraction": 1.8, "axis": "width"},
                "placement_rule": {
                    "scale_axis": "width",
                    "target_size_ratio": 0.08,
                    "vertical_center_ratio": 0.42,
                    "surface_offset_ratio": 0.08,
                    "target_bone_role": "right_hand",
                    "fit_scope": "hand-prop",
                },
                "body_metrics": {"hand_width": 40},
                "body_scale_weight": 0.75,
                "observations": [
                    {
                        "view": "front",
                        "current_box": [300, 340, 340, 380],
                        "target_box": [308, 332, 348, 372],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            }
        )

        self.assertEqual(result["category"], "hand_prop")
        self.assertEqual(result["anchor"], "right_hand:palm")
        self.assertEqual(result["placement_transform"]["bone"], "right_hand")
        self.assertEqual(result["placement_transform"]["scale"]["source"], "body-metrics+image-observations")
        self.assertAlmostEqual(result["fit_overrides"]["target_size_ratio"], 0.155, places=3)
        self.assertIn("depth:not-observed", result["diagnostics"]["warnings"])
        self.assertEqual(result["diagnostics"]["quality"]["status"], "solved")

    def test_solver_falls_back_to_image_observations_without_body_metrics(self):
        result = solve_placement(
            {
                "asset_key": "unknown-prop",
                "category": "unclassified",
                "current_overrides": {"target_size_ratio": 0.2, "vertical_center_ratio": 0.5},
                "observations": [
                    {
                        "view": "front",
                        "current_box": [100, 100, 200, 200],
                        "target_box": [100, 100, 150, 150],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            }
        )

        self.assertEqual(result["placement_transform"]["scale"]["source"], "image-observations")
        self.assertAlmostEqual(result["fit_overrides"]["target_size_ratio"], 0.1, places=3)
        self.assertIn("scale:missing-body-metric:character_height", result["diagnostics"]["warnings"])
        self.assertIn("category-defaulted:unclassified", result["diagnostics"]["warnings"])

    def test_solver_marks_missing_required_evidence_for_review(self):
        result = solve_placement(
            {
                "asset_key": "handheld-sword",
                "category": "hand_prop",
                "placement_rule": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.25,
                    "vertical_center_ratio": 0.5,
                    "target_bone_role": "right_hand",
                    "require_depth": True,
                    "require_rotation": True,
                },
                "observations": [
                    {
                        "view": "front",
                        "current_box": [260, 250, 300, 430],
                        "target_box": [280, 250, 320, 430],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            }
        )

        quality = result["diagnostics"]["quality"]
        self.assertEqual(quality["status"], "review")
        self.assertIn("missing-side-view", quality["blocking"])
        self.assertIn("missing-rotation", quality["blocking"])

    def test_solver_marks_required_side_and_rotation_evidence_solved(self):
        result = solve_placement(
            {
                "asset_key": "handheld-sword",
                "category": "hand_prop",
                "scale_rule": {"metric": "hand_width", "fraction": 3.0, "axis": "height"},
                "placement_rule": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.25,
                    "vertical_center_ratio": 0.5,
                    "target_bone_role": "right_hand",
                    "require_depth": True,
                    "require_rotation": True,
                },
                "body_metrics": {"hand_width": 42},
                "observations": [
                    {
                        "view": "front",
                        "current_box": [260, 250, 300, 430],
                        "target_box": [280, 250, 320, 430],
                        "character_box": [0, 0, 400, 800],
                        "rotation_delta_degrees": -8,
                    },
                    {
                        "view": "right",
                        "current_box": [220, 250, 260, 430],
                        "target_box": [235, 250, 275, 430],
                        "character_box": [0, 0, 400, 800],
                        "rotation_delta_degrees": -8,
                    },
                ],
            }
        )

        self.assertEqual(result["diagnostics"]["quality"]["status"], "solved")
        self.assertEqual(result["diagnostics"]["quality"]["blocking"], [])
        self.assertIn("front_offset_ratio", result["fit_overrides"])
        self.assertEqual(result["fit_overrides"]["rotation_z_degrees"], -8)

    def test_solver_registers_qwen_zoom_to_source_body_frame(self):
        result = solve_placement(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "require_body_registration": True,
                "current_overrides": {
                    "scale_axis": "height",
                    "target_size_ratio": 0.1,
                    "vertical_center_ratio": 0.7,
                },
                "observations": [
                    {
                        "view": "front",
                        "zoom": "torso-crop",
                        "qwen_edit_id": "qwen-zoomed",
                        "current_box": [300, 500, 340, 620],
                        "target_box": [220, 260, 300, 560],
                        "character_box": [0, 0, 640, 960],
                        "current_body_box": [160, 240, 480, 840],
                        "target_body_box": [80, 120, 400, 720],
                    }
                ],
            }
        )

        observation = result["observations"][0]
        self.assertEqual(observation["body_registration"]["status"], "registered")
        self.assertEqual(observation["target_box"], [300, 380, 380, 680])
        self.assertAlmostEqual(result["fit_overrides"]["target_size_ratio"], 0.25, places=3)
        self.assertEqual(result["diagnostics"]["accepted_observation_count"], 1)

    def test_solver_rejects_bad_qwen_body_registration_outlier(self):
        result = solve_placement(
            {
                "asset_key": "necktie-jeremy",
                "category": "neck_chest",
                "require_body_registration": True,
                "observations": [
                    {
                        "view": "front",
                        "zoom": "torso-crop",
                        "qwen_edit_id": "good",
                        "current_box": [300, 500, 340, 620],
                        "target_box": [300, 480, 340, 600],
                        "character_box": [0, 0, 640, 960],
                        "current_body_box": [160, 240, 480, 840],
                        "target_body_box": [160, 240, 480, 840],
                    },
                    {
                        "view": "front",
                        "zoom": "bad-crop",
                        "qwen_edit_id": "warped",
                        "current_box": [300, 500, 340, 620],
                        "target_box": [100, 100, 180, 440],
                        "character_box": [0, 0, 640, 960],
                        "current_body_box": [160, 240, 480, 840],
                        "target_body_box": [10, 20, 610, 320],
                    },
                ],
            }
        )

        rejected = result["diagnostics"]["rejected_observations"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["qwen_edit_id"], "warped")
        self.assertEqual(rejected[0]["reason"], "body-registration-aspect-change")
        self.assertEqual(result["diagnostics"]["accepted_observation_count"], 1)

    def test_solver_rejects_malformed_custom_scale_rule(self):
        with self.assertRaisesRegex(ValueError, "scale_rule missing required"):
            solve_placement(
                {
                    "asset_key": "bad-custom",
                    "category": "hand_prop",
                    "scale_rule": {"fraction": 2.0, "axis": "width"},
                    "observations": [
                        {
                            "view": "front",
                            "current_box": [0, 0, 10, 10],
                            "target_box": [0, 0, 12, 12],
                            "character_box": [0, 0, 100, 200],
                        }
                    ],
                }
            )

    def test_solver_rejects_malformed_observations(self):
        with self.assertRaisesRegex(ValueError, "observation missing required"):
            solve_placement(
                {
                    "asset_key": "bad-observation",
                    "category": "unknown",
                    "observations": [
                        {
                            "view": "front",
                            "current_box": [0, 0, 10, 10],
                            "character_box": [0, 0, 100, 200],
                        }
                    ],
                }
            )

    def test_placement_api_allows_explicit_uncataloged_objects(self):
        result = placement_suggestion(
            {
                "asset_key": "magic-orb",
                "allow_uncataloged": True,
                "solve_3d": True,
                "category": "hand_prop",
                "anchor_name": "right_hand:palm",
                "scale_rule": {"metric": "hand_width", "fraction": 1.8, "axis": "width"},
                "placement_rule": {
                    "scale_axis": "width",
                    "target_size_ratio": 0.08,
                    "vertical_center_ratio": 0.42,
                    "target_bone_role": "right_hand",
                },
                "body_metrics": {"hand_width": 40},
                "observations": [
                    {
                        "view": "front",
                        "current_box": [300, 340, 340, 380],
                        "target_box": [308, 332, 348, 372],
                        "character_box": [0, 0, 400, 800],
                    }
                ],
            },
            config_path=ROOT / "config/poly_pizza_assets.json",
        )

        self.assertEqual(result["asset"]["key"], "magic-orb")
        self.assertEqual(result["asset"]["quality"], "review")
        self.assertEqual(result["suggestion"]["anchor"], "right_hand:palm")

    def test_placement_api_rejects_uncataloged_objects_by_default(self):
        with self.assertRaisesRegex(ValueError, "asset not found"):
            placement_suggestion(
                {
                    "asset_key": "magic-orb",
                    "solve_3d": True,
                    "category": "hand_prop",
                    "observations": [
                        {
                            "view": "front",
                            "current_box": [0, 0, 10, 10],
                            "target_box": [0, 0, 12, 12],
                            "character_box": [0, 0, 100, 200],
                        }
                    ],
                },
                config_path=ROOT / "config/poly_pizza_assets.json",
            )


if __name__ == "__main__":
    unittest.main()
