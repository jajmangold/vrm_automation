import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.qa_scoring import expected_renders, score_job


class QAScoringTests(unittest.TestCase):
    def test_expected_renders_uses_angles_and_frames(self):
        self.assertEqual(
            expected_renders(
                {
                    "RENDER_POSE_STILLS": "1",
                    "RENDER_ANGLES": "front,portrait",
                    "RENDER_POSE_FRAMES": "24,72",
                }
            ),
            4,
        )

    def test_good_job_scores_as_ship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "status": "ok",
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "front",
                        "RENDER_POSE_FRAMES": "24",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "head_face"},
                        "fit_check": {
                            "status": "ok",
                            "warnings": [],
                            "metrics": {"width_ratio": 0.22, "height_ratio": 0.04},
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "A")
        self.assertEqual(result["review_priority"], "ship")
        self.assertEqual(result["qa_flags"], [])

    def test_neutral_facial_preset_only_requires_blink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "status": "ok",
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "front",
                        "RENDER_POSE_FRAMES": "24",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"preset": "neutral", "keyed": ["blink"]},
                    "external_outfit": {
                        "classification": {"category": "head_face"},
                        "fit_check": {"status": "ok", "warnings": [], "metrics": {}},
                    },
                },
                root,
            )

        self.assertEqual(result["qa_flags"], [])

    def test_bad_job_flags_missing_outputs_and_fit(self):
        result = score_job(
            {
                "status": "error",
                "environment": {
                    "OUTPUT_GLB": "/workspace/missing.glb",
                    "EXPORT_GLB": "1",
                    "RENDER_POSE_STILLS": "1",
                    "RENDER_ANGLES": "front,portrait",
                    "RENDER_POSE_FRAMES": "24,72",
                    "OUTFIT_CATEGORY": "head_face",
                },
            },
            {
                "status": "error",
                "errors": ["boom"],
                "pose_renders": [],
                "exports": {"glb": False},
                "matched_bones": {},
                "expression_animation": {"keyed": []},
                "external_outfit": {
                    "fit_check": {
                        "status": "review",
                        "warnings": ["wide"],
                        "metrics": {"width_ratio": 0.5, "height_ratio": 0.2},
                    }
                },
            },
            ROOT,
        )

        self.assertEqual(result["qa_grade"], "D")
        self.assertEqual(result["review_priority"], "reject")
        self.assertIn("missing-glb", result["qa_flags"])
        self.assertIn("face-accessory-wide", result["qa_flags"])

    def test_known_visual_qa_issues_affect_review_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "gen-051-female-fedora-google-look-around",
                    "status": "ok",
                    "metadata": {"tags": ["fedora-google", "head-face"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "front",
                        "RENDER_POSE_FRAMES": "24",
                        "OUTFIT_CATEGORY": "head_face",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "head_face"},
                        "fit_check": {"status": "ok", "warnings": [], "metrics": {}},
                    },
                },
                root,
            )

        self.assertIn("known-weak-asset", result["qa_flags"])
        self.assertIn("asset:weak", result["review_tags"])
        self.assertEqual(result["review_priority"], "review")

    def test_complete_torso_back_render_coverage_softens_coarse_fit_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render_dir = root / "outputs/renders"
            glb.parent.mkdir(parents=True)
            render_dir.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render_paths = [
                "/workspace/outputs/renders/pose_0024.png",
                "/workspace/outputs/renders/pose_0072.png",
                "/workspace/outputs/renders/pose_side_0024.png",
                "/workspace/outputs/renders/pose_side_0072.png",
                "/workspace/outputs/renders/pose_back_0024.png",
                "/workspace/outputs/renders/pose_back_0072.png",
                "/workspace/outputs/renders/pose_portrait_0024.png",
                "/workspace/outputs/renders/pose_portrait_0072.png",
            ]
            for path in render_paths:
                (root / path.removeprefix("/workspace/")).write_bytes(b"png")

            result = score_job(
                {
                    "status": "ok",
                    "metadata": {"tags": ["backpack-j-toastie", "torso-back"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "front,side,back,portrait",
                        "RENDER_POSE_FRAMES": "24,72",
                        "OUTFIT_CATEGORY": "torso_back",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": render_paths,
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "torso_back"},
                        "fit_check": {
                            "status": "review",
                            "warnings": ["outfit-depth-large", "outfit-buried-deep"],
                            "metrics": {"width_ratio": 0.13, "height_ratio": 0.16},
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "B")
        self.assertEqual(result["review_priority"], "review")
        self.assertIn("fit-review", result["qa_flags"])
        self.assertIn("fit-warnings", result["qa_flags"])
        self.assertIn("review:torso-back", result["review_tags"])

    def test_single_neck_chest_depth_warning_does_not_block_otherwise_clean_ship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "status": "ok",
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "9",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {
                            "status": "review",
                            "warnings": ["outfit-depth-large"],
                            "metrics": {
                                "width_ratio": 0.14,
                                "height_ratio": 0.12,
                                "vertical_center_ratio": 0.74,
                                "depth_ratio": 0.54,
                            },
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "A")
        self.assertEqual(result["review_priority"], "ship")
        self.assertNotIn("fit-review", result["qa_flags"])
        self.assertNotIn("fit-warnings", result["qa_flags"])

    def test_centered_necktie_surface_penetration_does_not_block_ship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "status": "ok",
                    "metadata": {"tags": ["necktie-jeremy", "neck-chest"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "1",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {
                            "status": "review",
                            "warnings": ["outfit-surface-penetration"],
                            "metrics": {
                                "width_ratio": 0.0396,
                                "height_ratio": 0.082,
                                "vertical_center_ratio": 0.74,
                                "surface_gap_ratio": -0.1914,
                                "surface_penetration_ratio": 0.1914,
                                "buried_depth_ratio": 0.0,
                            },
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "A")
        self.assertEqual(result["review_priority"], "ship")
        self.assertNotIn("fit-review", result["qa_flags"])
        self.assertNotIn("fit-warnings", result["qa_flags"])

    def test_known_large_low_glasses_asset_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "gen-023-male-glasses-jeremy-talk-idle",
                    "status": "ok",
                    "metadata": {"tags": ["glasses-jeremy", "head-face"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "front",
                        "RENDER_POSE_FRAMES": "24",
                        "OUTFIT_CATEGORY": "head_face",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "head_face"},
                        "fit_check": {"status": "ok", "warnings": [], "metrics": {}},
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "B")
        self.assertEqual(result["review_priority"], "review")
        self.assertIn("glasses-large-low", result["qa_flags"])

    def test_face_occluding_mask_candidate_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "anchor-candidate-sam-001-001",
                    "status": "ok",
                    "metadata": {"tags": ["anon-mask-scott-marshall", "head-face"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "24",
                        "OUTFIT_CATEGORY": "head_face",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "head_face"},
                        "fit_check": {"status": "ok", "warnings": [], "metrics": {"width_ratio": 0.14, "height_ratio": 0.15}},
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "B")
        self.assertEqual(result["review_priority"], "review")
        self.assertIn("face-occluding-mask", result["qa_flags"])

    def test_wizard_hat_candidate_requires_review_when_tiny_or_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "anchor-candidate-next-001-005",
                    "status": "ok",
                    "metadata": {"tags": ["wizard-hat-google", "head-face"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "24",
                        "OUTFIT_CATEGORY": "head_face",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "head_face"},
                        "fit_check": {"status": "ok", "warnings": [], "metrics": {}},
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "B")
        self.assertEqual(result["review_priority"], "review")
        self.assertIn("hat-tiny-hidden", result["qa_flags"])

    def test_low_neck_loop_candidate_requires_review_even_with_benign_depth_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "anchor-candidate-sam-001-003",
                    "status": "ok",
                    "metadata": {"tags": ["necklace-quaternius", "anchor:neck-chest-neck-loop"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "24",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {
                            "status": "review",
                            "warnings": ["outfit-depth-large"],
                            "metrics": {
                                "width_ratio": 0.1898,
                                "height_ratio": 0.1538,
                                "vertical_center_ratio": 0.777,
                            },
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "B")
        self.assertEqual(result["review_priority"], "review")
        self.assertIn("neck-loop-low", result["qa_flags"])
        self.assertNotIn("fit-review", result["qa_flags"])

    def test_high_neck_loop_candidate_can_ship_with_benign_depth_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "necklace-high-001",
                    "status": "ok",
                    "metadata": {"tags": ["necklace-quaternius", "anchor:neck-chest-neck-loop"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "72",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {
                            "status": "review",
                            "warnings": ["outfit-depth-large"],
                            "metrics": {
                                "width_ratio": 0.1898,
                                "height_ratio": 0.1538,
                                "vertical_center_ratio": 0.84,
                            },
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "A")
        self.assertEqual(result["review_priority"], "ship")
        self.assertNotIn("neck-loop-low", result["qa_flags"])
        self.assertNotIn("fit-review", result["qa_flags"])

    def test_neck_loop_depth_and_surface_warning_can_be_benign_when_bounds_are_reasonable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "necklace-forward-002",
                    "status": "ok",
                    "metadata": {"tags": ["necklace-quaternius", "anchor:neck-chest-neck-loop"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "72",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {
                            "status": "review",
                            "warnings": ["outfit-depth-large", "outfit-floating-forward"],
                            "metrics": {
                                "width_ratio": 0.1818,
                                "height_ratio": 0.1538,
                                "vertical_center_ratio": 0.84,
                                "surface_gap_ratio": 0.1879,
                                "buried_depth_ratio": 0.008,
                            },
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "A")
        self.assertEqual(result["review_priority"], "ship")
        self.assertNotIn("fit-review", result["qa_flags"])

    def test_necktie_on_head_candidate_requires_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "anchor-review-category-007",
                    "status": "ok",
                    "metadata": {"tags": ["necktie-jeremy", "neck-chest"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "72",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {"status": "ok", "warnings": [], "metrics": {"vertical_center_ratio": 0.9445}},
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "C")
        self.assertEqual(result["review_priority"], "fix")
        self.assertIn("necktie-head-placement", result["qa_flags"])

    def test_necktie_at_collar_can_ship_without_head_placement_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb = root / "outputs/person.glb"
            render = root / "outputs/render.png"
            glb.parent.mkdir(parents=True)
            glb.write_bytes(b"glb")
            render.write_bytes(b"png")

            result = score_job(
                {
                    "id": "necktie-low-001",
                    "status": "ok",
                    "metadata": {"tags": ["necktie-jeremy", "neck-chest"]},
                    "environment": {
                        "OUTPUT_GLB": "/workspace/outputs/person.glb",
                        "EXPORT_GLB": "1",
                        "RENDER_POSE_STILLS": "1",
                        "RENDER_ANGLES": "portrait",
                        "RENDER_POSE_FRAMES": "72",
                        "OUTFIT_CATEGORY": "neck_chest",
                    },
                },
                {
                    "status": "ok",
                    "pose_renders": ["/workspace/outputs/render.png"],
                    "exports": {"glb": True},
                    "matched_bones": {
                        "spine": "spine",
                        "head": "head",
                        "left_arm": "left",
                        "right_arm": "right",
                    },
                    "expression_animation": {"keyed": ["smile", "blink"]},
                    "external_outfit": {
                        "classification": {"category": "neck_chest"},
                        "fit_check": {
                            "status": "ok",
                            "warnings": [],
                            "metrics": {
                                "width_ratio": 0.05,
                                "height_ratio": 0.06,
                                "vertical_center_ratio": 0.74,
                            },
                        },
                    },
                },
                root,
            )

        self.assertEqual(result["qa_grade"], "A")
        self.assertEqual(result["review_priority"], "ship")
        self.assertNotIn("necktie-head-placement", result["qa_flags"])


if __name__ == "__main__":
    unittest.main()
